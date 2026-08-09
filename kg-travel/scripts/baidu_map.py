#!/usr/bin/env python3
"""百度地图 Web 服务 API 封装。

能力：
  weather    天气查询(实时+7天预报+生活指数+预警)
  geocode    地名 → 经纬度(地理编码)
  reverse    经纬度 → 地名/周边(逆地理编码)
  search     关键词 + 区域/坐标 → POI 列表(地点检索, 支持评分/距离排序)
  around     坐标周边检索(沿途美食/景点)
  transit    公交路线规划(A→B 静态方案: 坐哪路/几站/多久)
  driving    驾车路线规划
  walk       步行路线规划
  bike       骑行路线规划
  navlink    生成百度地图导航跳转链接(飞书里点击直接导航)

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
    """带全局限流的 HTTP 请求。百度个人认证 QPS=3（账号级共享），
    用文件锁强制请求间隔 ≥400ms，跨进程串行化防止打爆配额。"""
    throttle_baidu()
    ak = load_ak()
    params = dict(params, output="json", ak=ak)
    url = f"{API}{path}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"[错误] 请求失败：{e}")


def throttle_baidu():
    """跨进程令牌桶：两次请求之间至少间隔 BAIDU_MIN_INTERVAL 秒。"""
    import fcntl
    import time
    cfg_dir = pathlib.Path(os.environ.get(
        "KG_AGENT_CONFIG_DIR", pathlib.Path.home() / ".kg-agent-config"))
    lock_path = cfg_dir / ".baidu_throttle.lock"
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        lock_path.touch()
    except OSError:
        pass
    min_interval = float(os.environ.get("BAIDU_MIN_INTERVAL", "0.4"))
    try:
        with open(lock_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                last = float(f.read().strip() or "0")
            except ValueError:
                last = 0.0
            now = time.monotonic()
            wait = last + min_interval - now
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            f.seek(0)
            f.write(str(now))
            f.truncate()
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass


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

COMMON_DISTRICTS = {
    "110101": "东城区", "110102": "西城区", "110105": "朝阳区",
    "110106": "丰台区", "110107": "石景山区", "110108": "海淀区",
    "110109": "门头沟区", "110111": "房山区", "110112": "通州区",
    "110113": "顺义区", "110114": "昌平区", "110115": "大兴区",
    "110116": "怀柔区", "110117": "平谷区", "110118": "密云区",
    "110119": "延庆区",
    "310101": "黄浦区", "310104": "徐汇区", "310105": "长宁区",
    "310106": "静安区", "310107": "普陀区", "310109": "虹口区",
    "310110": "杨浦区", "310112": "闵行区", "310113": "宝山区",
    "310114": "嘉定区", "310115": "浦东新区",
    "440103": "荔湾区", "440104": "越秀区", "440106": "天河区",
    "440105": "海珠区", "440111": "白云区", "440112": "黄埔区",
    "440306": "宝安区", "440305": "南山区", "440304": "福田区",
    "440303": "罗湖区",
}

CITY_EN_ZH = {
    "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
    "shenzhen": "深圳", "chengdu": "成都", "hangzhou": "杭州",
    "wuhan": "武汉", "xian": "西安", "nanjing": "南京",
    "tianjin": "天津", "chongqing": "重庆", "suzhou": "苏州",
    "haidian": "海淀", "chaoyang": "朝阳", "dongcheng": "东城",
    "xicheng": "西城", "pudong": "浦东", "changping": "昌平",
}


def resolve_district(city: str):
    """城市名 → 区县编码（weather 接口需要 district_id）。"""
    if city.isdigit() and len(city) >= 6:
        return city[:6]
    cn = CITY_EN_ZH.get(city.strip().lower())
    if cn:
        city = cn
    for code, name in COMMON_DISTRICTS.items():
        if city in name or name in city:
            return code
    d = check_status(http_get("/api_region_search/v1/", {
        "keyword": city, "sub_admin": "1", "extensions_code": "1"}))
    for dist in d.get("districts") or []:
        subs = dist.get("districts") or []
        if subs:
            return subs[0].get("code", "")
    return ""


def cmd_weather(args):
    district = args.district or resolve_district(args.city or "北京")
    if not district:
        sys.exit(f"[错误] 无法确定行政区划编码：{args.city}")
    data_type = args.data or "all"
    d = check_status(http_get("/weather/v1/", {
        "district_id": district, "data_type": data_type}))
    r = d.get("result") or {}
    loc = r.get("location") or {}
    parts = [p for p in [loc.get("province"), loc.get("city"), loc.get("name")] if p]
    uniq = []
    for p in parts:
        if not uniq or uniq[-1] != p:
            uniq.append(p)
    print(f"📍 {''.join(uniq)}（{district}）")
    now = r.get("now")
    if now:
        print(f"  现在: {now.get('text')} {now.get('temp')}°C 体感{now.get('feels_like')}°C "
              f"湿度{now.get('rh')}% {now.get('wind_dir')}{now.get('wind_class')} "
              f"AQI{now.get('aqi')} 紫外线{now.get('uvi')}")
    for f in (r.get("forecasts") or [])[: args.days]:
        print(f"  {f.get('date', '')} {f.get('text_day')}/{f.get('text_night')} "
              f"{f.get('high')}°/{(f.get('low') or '')}° {f.get('wd_day', '')}")
    for i in (r.get("indexes") or [])[: args.index_limit]:
        print(f"  · {i.get('name')}: {i.get('brief')} — {i.get('detail', '')[:40]}")
    for a in (r.get("alerts") or []):
        print(f"  ⚠️ {a.get('title', '')}: {a.get('desc', '')[:60]}")


def cmd_navlink(args):
    dest = args.dest
    if "," in dest and dest.replace(".", "").replace(",", "").replace("-", "").isdigit():
        lng, lat = dest.split(",")
        dest = f"latlng:{lat},{lng}|name:目的地"
    params = {
        "origin": args.origin or "我的位置",
        "destination": dest,
        "mode": args.mode,
        "region": args.city,
        "output": "html",
        "src": "webapp.kgwiki.personal",
    }
    url = "http://api.map.baidu.com/direction?" + urllib.parse.urlencode(params)
    print(url)
    print(f"\n[提示] 手机/电脑浏览器打开此链接即可导航到 {args.dest}。"
          f"（{args.mode} 方式，起点 {params['origin']}）")


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

    g = sub.add_parser("weather", help="天气查询(实时+预报+指数+预警)")
    g.add_argument("--city", help="城市名(中文/英文/区县编码)")
    g.add_argument("--district", help="区县编码(6位, 如 110108)")
    g.add_argument("--data", choices=["now", "fc", "index", "alert", "all"], default="all")
    g.add_argument("--days", type=int, default=3)
    g.add_argument("--index-limit", type=int, default=6)
    g.set_defaults(fn=cmd_weather)

    g = sub.add_parser("navlink", help="生成导航跳转链接")
    g.add_argument("dest", help="目的地: 地名或 lng,lat")
    g.add_argument("--origin", help="起点(默认我的位置)")
    g.add_argument("--mode", default="transit", choices=["transit", "driving", "walking"])
    g.add_argument("--city", default="北京")
    g.set_defaults(fn=cmd_navlink)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
