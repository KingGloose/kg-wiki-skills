#!/usr/bin/env python3
"""百度地图 Web 服务 API 封装。

能力：
  geocode    地名 → 经纬度(地理编码)
  reverse    经纬度 → 地名/周边(逆地理编码)
  search     关键词 + 区域/坐标 → POI 列表(地点检索, 支持评分/距离排序)
  around     坐标周边检索(沿途美食/景点)
  transit    公交路线规划(A→B 静态方案: 坐哪路/几站/多久)
  driving    驾车路线规划
  walk       步行路线规划
  bike       骑行路线规划

凭据：~/.kg-agent-config/credentials.json 的 baidu_map.ak（统一配置目录, 不进 git）。
用法：
  python3 baidu_map.py geocode "天安门"
  python3 baidu_map.py search "烤鸭" --region 北京 --limit 5
  python3 baidu_map.py around "39.915119,116.403963" "美食" --radius 2000 --limit 5
  python3 baidu_map.py transit "39.915119,116.403963" "39.9088,116.3975" --city 北京
  python3 baidu_map.py transit --origin 天安门 --dest 故宫 --city 北京
"""
import argparse
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

API = "https://api.map.baidu.com"

def load_ak():
    cfg_dir = pathlib.Path(os.environ.get(
        "KG_AGENT_CONFIG_DIR", pathlib.Path.home() / ".kg-agent-config"))
    cred_file = cfg_dir / "credentials.json"
    ak = os.environ.get("BAIDU_MAP_AK")
    if cred_file.is_file():
        try:
            cfg = json.loads(cred_file.read_text(encoding="utf-8"))
            ak = (cfg.get("baidu_map") or {}).get("ak") or ak
        except ValueError as e:
            sys.exit(f"[错误] {cred_file} 不是合法 JSON：{e}")
    if not ak:
        sys.exit(
            "[错误] 未找到百度地图 AK。请在 ~/.kg-agent-config/credentials.json "
            "写入 {\"baidu_map\": {\"ak\": \"...\"}}，或用 BAIDU_MAP_AK 环境变量。")
    return ak


def http_get(path, params):
    ak = load_ak()
    params = dict(params, output="json", ak=ak)
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"[错误] 请求失败：{e}")


def check_status(d):
    if d.get("status") != 0:
        sys.exit(f"[错误] 百度地图返回 status={d.get('status')}: {d.get('message')}")
    return d


def resolve_coord(text):
    """把 地名 或 'lng,lat' 解析成 (lat, lng)。"""
    text = text.strip()
    if "," in text:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) == 2:
            try:
                lng, lat = float(parts[0]), float(parts[1])
                return lat, lng
            except ValueError:
                pass
    d = check_status(http_get("/geocoding/v3/", {"address": text}))
    r = d.get("result") or {}
    loc = r.get("location") or {}
    if not loc:
        sys.exit(f"[错误] 无法解析地点：{text}")
    return loc["lat"], loc["lng"]


def fmt_poi(r):
    di = r.get("detail_info") or {}
    parts = [f"· {r.get('name')}"]
    if di.get("overall_rating"):
        parts.append(f"评分{di['overall_rating']}")
    if r.get("address"):
        parts.append(r["address"])
    if di.get("price"):
        parts.append(f"参考价{di['price']}")
    return " | ".join(parts)


# ── 子命令实现 ──────────────────────────────────────────────

def cmd_geocode(args):
    d = check_status(http_get("/geocoding/v3/", {"address": args.address}))
    r = d.get("result") or {}
    loc = r.get("location") or {}
    print(json.dumps({
        "name": args.address,
        "lng": loc.get("lng"),
        "lat": loc.get("lat"),
        "level": r.get("level"),
        "confidence": r.get("confidence"),
    }, ensure_ascii=False, indent=2))


def cmd_reverse(args):
    lng, lat = args.coord.split(",")
    d = check_status(http_get("/reverse_geocoding/v3/", {
        "location": f"{lat},{lng}",
        "extensions_poi": "1" if args.poi else "0",
    }))
    r = d.get("result") or {}
    print(json.dumps({
        "formatted_address": r.get("formatted_address"),
        "province": r.get("province"),
        "city": r.get("city"),
        "district": r.get("district"),
        "pois": [p.get("name") for p in (r.get("pois") or [])[:5]],
    }, ensure_ascii=False, indent=2))


def cmd_search(args):
    params = {"query": args.query, "scope": "2"}
    if args.region:
        params["region"] = args.region
        params["region_limit"] = "true"
    if args.center:
        params["center"] = args.center
    if args.filter:
        params["filter"] = args.filter
    d = check_status(http_get("/place/v3/region", params))
    results = d.get("results") or []
    print(f"共 {len(results)} 条结果（关键词: {args.query}）")
    for r in results[: args.limit]:
        print(fmt_poi(r))


def cmd_around(args):
    # CLI 约定 lng,lat（与路线规划一致），API 需要 lat,lng
    lng, lat = args.coord.split(",")
    filt = f"industry_type:{args.industry}|sort_name:{args.sort}|sort_rule:{args.rule}"
    d = check_status(http_get("/place/v3/around", {
        "query": args.query,
        "location": f"{lat},{lng}",
        "radius": args.radius,
        "scope": "2",
        "radius_limit": "true",
        "filter": filt,
    }))
    results = d.get("results") or []
    print(f"坐标 {args.coord} 周边 {args.radius}m 内「{args.query}」共 {len(results)} 条（按{args.sort}排序）：")
    for r in results[: args.limit]:
        print(fmt_poi(r))


def cmd_route(args, mode):
    """mode: transit/driving/walking/riding"""
    o_lat, o_lng = resolve_coord(args.origin)
    d_lat, d_lng = resolve_coord(args.dest)
    params = {
        "origin": f"{o_lat},{o_lng}",
        "destination": f"{d_lat},{d_lng}",
    }
    if mode == "transit":
        params["city1"] = args.city or "北京"
        params["city2"] = args.city or "北京"
    d = check_status(http_get(f"/direction/v2/{mode}", params))
    r = d.get("result") or {}
    routes = r.get("routes") or []
    if not routes:
        print("[提示] 没有可用的路线方案。")
        return
    rt = routes[0]
    print(f"路线: {args.origin} → {args.dest}")
    if rt.get("distance"):
        print(f"距离: {rt['distance']} 米 | 预计: {rt.get('duration', 0) / 60:.0f} 分钟")
    if rt.get("traffic_condition"):
        print(f"路况: {rt['traffic_condition']}")
    steps = rt.get("steps") or []
    for st in steps[:10]:
        if isinstance(st, list):
            st = st[0] if st and isinstance(st[0], dict) else {}
        if not isinstance(st, dict):
            continue
        instr = (st.get("instructions") or "").replace("<[^>]+>", "")
        if st.get("vehicle"):
            v = st["vehicle"]
            line = f"  → 坐{v.get('name', '公交')}({v.get('start_name', '')}→{v.get('end_name', '')})"
            if v.get("stop_num"):
                line += f" {v['stop_num']}站"
            print(line)
        elif instr:
            print(f"  → {instr[:60]}")
    if rt.get("walking_distance"):
        print(f"总步行: {rt['walking_distance']} 米")


def main():
    p = argparse.ArgumentParser(prog="baidu_map.py", description="百度地图 Web API")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("geocode", help="地名→经纬度")
    g.add_argument("address")
    g.set_defaults(fn=cmd_geocode)

    g = sub.add_parser("reverse", help="经纬度→地名")
    g.add_argument("coord", help="lng,lat")
    g.add_argument("--poi", action="store_true", help="附带周边 POI")
    g.set_defaults(fn=cmd_reverse)

    g = sub.add_parser("search", help="行政区划检索")
    g.add_argument("query")
    g.add_argument("--region", help="区域(城市/区县)")
    g.add_argument("--center", help="辅助按距离排序的坐标 lng,lat")
    g.add_argument("--filter", help="如 sort_name:overall_rating|sort_rule:0")
    g.add_argument("--limit", type=int, default=5)
    g.set_defaults(fn=cmd_search)

    g = sub.add_parser("around", help="周边检索(圆形区域)")
    g.add_argument("coord", help="lng,lat")
    g.add_argument("query")
    g.add_argument("--radius", type=int, default=2000)
    g.add_argument("--industry", default="cater", help="hotel/cater/life")
    g.add_argument("--sort", default="overall_rating", help="overall_rating/distance/price")
    g.add_argument("--rule", default="0", help="0降序 1升序")
    g.add_argument("--limit", type=int, default=5)
    g.set_defaults(fn=cmd_around)

    for name, mode in [("transit", "transit"), ("driving", "driving"),
                       ("walk", "walking"), ("bike", "riding")]:
        g = sub.add_parser(name, help=f"{name} 路线规划")
        g.add_argument("origin", help="起点: 地名或 lng,lat")
        g.add_argument("dest", help="终点: 地名或 lng,lat")
        g.add_argument("--city", default="北京")
        g.set_defaults(fn=lambda a, m=mode: cmd_route(a, m))

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
