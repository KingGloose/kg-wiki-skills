#!/usr/bin/env python3
"""小红书单篇笔记 → Markdown（图片下载 + 压缩 + 可选 OCR）。

为什么是纯 HTTP 而不是浏览器：
  小红书**单篇笔记页是服务端渲染**的，完整数据就在 HTML 的
  `window.__INITIAL_STATE__` 里。不用调 API，也就不用算 x-s/x-t 签名，
  零 cookie 零登录。分享链接自带 `xsec_token` 作为访问凭证 ——
  本质是「把你有权看的内容导出来」，不是爬虫。

  注意：搜索页和收藏夹**不是** SSR 的（feeds 为空，前端异步拉），
  那两个场景必须走 kg-browser，不在本脚本范围内。

小红书的特点是**图片媒介** —— 正文 desc 常常只有话题标签，
真正的信息在图里。所以 --ocr 不是可选装饰，是刚需。

用法：
  python3 xhs_to_md.py "http://xhslink.cn/o/xxx" --out raw/xhs-xxx.md
  python3 xhs_to_md.py "<url>" --out x.md --ocr        # 顺便 OCR 图片
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# 复用底层库：图片压缩和 OCR 都不自己实现。
# kg-media-to-text 的包在 skill 目录根下（不是 scripts/）；
# 已装进环境时 import 直接命中，没装则靠这条路径兜住。
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent.parent / "kg-media-to-text"))
try:
    from media_to_text import compress_image, summarize_compression, ImageCompressError
except ImportError:  # 底层库不在时降级：不压缩也能跑
    compress_image = None
    summarize_compression = None
    ImageCompressError = Exception

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = 30


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def extract_url(text: str) -> str:
    """从分享文本里提取链接。

    用户通常直接粘贴 App 分享的整段话：
      「给openai付的钱要用起来 http://xhslink.cn/o/xxx 复制一下，然后打开【小红书】…」
    所以不能假设输入是干净的 URL。
    """
    text = (text or "").strip()
    m = re.search(r"https?://(?:[\w-]+\.)*(?:xhslink\.(?:cn|com)|xiaohongshu\.com)"
                  r"[^\s\u4e00-\u9fff，。！？【】、]*", text)
    if m:
        return m.group(0).rstrip("，。！？、)）]】")
    # 没匹配到小红书域名，但整体看着像 URL 就原样放行（便于调试别的域名）
    if re.match(r"^https?://\S+$", text):
        return text
    raise SystemExit(
        "[错误] 没在输入里找到小红书链接。\n"
        "  期望形如 http://xhslink.cn/o/xxx 或 https://www.xiaohongshu.com/explore/xxx\n"
        f"  实际收到：{text[:120]}"
    )


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_state(html: str) -> dict:
    """从 SSR 的 window.__INITIAL_STATE__ 里取出笔记数据。"""
    m = re.search(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", html, re.S)
    if not m:
        raise SystemExit(
            "[错误] 页面里没有 __INITIAL_STATE__。可能原因：\n"
            "  · 链接失效或 xsec_token 过期（重新从 App 分享一次）\n"
            "  · 笔记已删除/被设为私密\n"
            "  · 小红书改成了客户端渲染（那本方案需要重写，改走 kg-browser）"
        )
    raw = m.group(1).strip().rstrip(";")
    # 小红书塞的是 JS 字面量，undefined 不是合法 JSON
    return json.loads(raw.replace("undefined", "null"))


def extract_note(state: dict) -> dict:
    nd = (state.get("note") or {}).get("noteDetailMap") or {}
    ids = [k for k in nd if k != "currentNoteId"]
    if not ids:
        raise SystemExit("[错误] noteDetailMap 为空，笔记可能不可见（非公开或已删除）")
    note = (nd[ids[0]] or {}).get("note") or {}
    if not note:
        raise SystemExit("[错误] 拿到 noteDetailMap 但 note 为空")
    note["_id"] = ids[0]
    return note


def sniff_ext(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "jpg"


def download_images(note: dict, assets_dir: Path, prefix: str,
                    compress: bool = True) -> tuple[list, list]:
    """下载图片。小红书 CDN 无防盗链，直连即可。"""
    imgs = note.get("imageList") or []
    if not imgs:
        return [], []
    assets_dir.mkdir(parents=True, exist_ok=True)
    rels, comp = [], []
    nid = note.get("_id", "note")[:12]
    for i, im in enumerate(imgs, 1):
        url = im.get("urlDefault") or im.get("url") or ""
        if not url:
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                data = r.read()
        except Exception as e:
            eprint(f"[warn] 图 {i} 下载失败: {type(e).__name__}: {e}")
            rels.append((i, url))          # 失败就留原链接
            continue
        saved = assets_dir / f"xhs-{nid}-{i:02d}.{sniff_ext(data)}"
        saved.write_bytes(data)
        if compress and compress_image is not None:
            try:
                res = compress_image(saved)
                comp.append(res)
                # 库在「压完反而更大」时会保留原图并置 changed=False
                if getattr(res, "changed", False) and getattr(res, "path", None):
                    saved = Path(res.path)
            except ImageCompressError as e:
                eprint(f"[warn] 图 {i} 压缩失败（保留原图）: {e}")
        rels.append((i, f"{prefix}/{saved.name}"))
    return rels, comp


def ocr_images(rels: list, assets_dir: Path) -> dict:
    """对下载好的图做 OCR。小红书正文常为空，信息在图里。

    走底层库的统一入口 to_text（库里没有单独的 image_to_text）。
    """
    try:
        from media_to_text import to_text, UnsupportedSourceError
    except ImportError:
        eprint("[warn] 底层库不可用（先装 kg-media-to-text），跳过 OCR")
        return {}
    out = {}
    for i, rel in rels:
        p = assets_dir / Path(rel).name
        if not p.is_file():
            continue
        try:
            res = to_text(p)
            txt = (getattr(res, "text", None) or "").strip()
            if txt:
                out[i] = txt
                eprint(f"[ok] 图 {i} OCR {len(txt)} 字")
            else:
                eprint(f"[warn] 图 {i} OCR 无文字")
        except UnsupportedSourceError as e:
            # kg-media-to-text 目前还没实现图片 OCR（规划中的 L2）。
            # 一张失败就都会失败，没必要继续试。
            eprint(f"[!] 底层库暂不支持图片 OCR：{e}")
            eprint("[!] 小红书图片笔记的文字暂时提不出来 —— "
                   "沉淀时需要人工看图，或等底层库补上 OCR")
            return out
        except Exception as e:
            eprint(f"[warn] 图 {i} OCR 失败: {type(e).__name__}: {e}")
    return out


def clean_desc(desc: str) -> str:
    """去掉 desc 末尾那串 #话题[话题]# 标记，话题另有结构化字段。"""
    return re.sub(r"#[^#\[\]]+\[话题\]#", "", desc or "").strip()


def build_md(note: dict, url: str, rels: list, ocr: dict) -> str:
    from datetime import datetime, timezone, timedelta
    CN = timezone(timedelta(hours=8))

    title = (note.get("title") or "无标题").strip()
    user = note.get("user") or {}
    ts = note.get("time")
    when = (datetime.fromtimestamp(ts / 1000, CN).strftime("%Y-%m-%d %H:%M")
            if isinstance(ts, (int, float)) else "")
    tags = [t.get("name") for t in (note.get("tagList") or []) if t.get("name")]
    ia = note.get("interactInfo") or {}
    desc = clean_desc(note.get("desc", ""))

    L = ["---",
         f"title: {title}",
         f"source: {url}",
         f"platform: 小红书",
         f"author: {user.get('nickname', '')}",
         f"published: {when}",
         f"note_id: {note.get('_id', '')}",
         f"tags: [{', '.join(tags)}]" if tags else "tags: []",
         f"likes: {ia.get('likedCount', '')}",
         f"collects: {ia.get('collectedCount', '')}",
         f"images: {len(rels)}",
         "---", "",
         f"# {title}", "",
         f"> 作者：{user.get('nickname','')} · {when} · "
         f"赞 {ia.get('likedCount','?')} / 藏 {ia.get('collectedCount','?')}",
         f"> 原文：{url}", ""]

    if tags:
        L += ["**话题**：" + " ".join(f"#{t}" for t in tags), ""]

    if desc:
        L += ["## 正文", "", desc, ""]
    else:
        L += ["## 正文", "",
              "_（这篇笔记的 desc 只有话题标签，内容在图片里）_", ""]

    if rels:
        L += ["## 图片", ""]
        for i, rel in rels:
            L.append(f"![图 {i}]({rel})")
            if i in ocr:
                L += ["", f"> **图 {i} OCR**：", ""]
                L += ["> " + ln for ln in ocr[i].splitlines() if ln.strip()]
            L.append("")

    if not desc and not ocr:
        L += ["---", "",
              "> ⚠️ 正文为空且未做 OCR。这篇笔记的信息在图片里，",
              "> 直接沉淀会丢内容 —— 加 `--ocr` 重跑，或人工看图补充。", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="小红书单篇笔记 → Markdown（读 SSR 数据，零 cookie）")
    ap.add_argument("url", help="分享链接（xhslink.cn/... 或 xiaohongshu.com/...）")
    ap.add_argument("--out", default=None, help="输出 md；不给则打到 stdout")
    ap.add_argument("--assets", default=None, help="图片目录；默认 <out同级>/assets")
    ap.add_argument("--asset-prefix", default="assets", help="md 里的图片相对前缀")
    ap.add_argument("--no-images", action="store_true", help="不下载图片")
    ap.add_argument("--no-compress", action="store_true", help="不压缩成 WebP")
    ap.add_argument("--ocr", action="store_true",
                    help="对图片做 OCR（小红书多为图片笔记，通常需要）")
    ap.add_argument("--json", action="store_true", help="额外把原始 note 数据打到 stderr")
    args = ap.parse_args()

    url = extract_url(args.url)
    if url != args.url.strip():
        eprint(f"[..] 从分享文本里提取到链接")
    eprint(f"[..] 抓取 {url}")
    try:
        html = fetch_html(url)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"[错误] HTTP {e.code}：链接可能失效或需要重新分享")
    except Exception as e:
        raise SystemExit(f"[错误] 抓取失败：{type(e).__name__}: {e}")

    note = extract_note(parse_state(html))
    eprint(f"[ok] {note.get('title','无标题')} / "
           f"{(note.get('user') or {}).get('nickname','?')} / "
           f"图 {len(note.get('imageList') or [])} 张")

    rels, comp = [], []
    assets_dir = None
    if not args.no_images:
        if args.assets:
            assets_dir = Path(args.assets)
        elif args.out:
            assets_dir = Path(args.out).resolve().parent / args.asset_prefix
        else:
            assets_dir = Path.cwd() / args.asset_prefix
        rels, comp = download_images(note, assets_dir, args.asset_prefix,
                                    compress=not args.no_compress)
        eprint(f"[ok] 图片 {len(rels)} 张 -> {assets_dir}")
        if comp and summarize_compression:
            eprint("[ok] " + summarize_compression(comp))

    ocr = ocr_images(rels, assets_dir) if (args.ocr and rels and assets_dir) else {}

    md = build_md(note, url, rels, ocr)
    if args.json:
        eprint(json.dumps(note, ensure_ascii=False, indent=2)[:3000])

    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md, encoding="utf-8")
        eprint(f"[ok] 写入 {p}")
        if not clean_desc(note.get("desc", "")) and not ocr:
            eprint("[!] 正文为空且没 OCR —— 这篇的信息在图里，加 --ocr 重跑")
    else:
        print(md)


if __name__ == "__main__":
    main()
