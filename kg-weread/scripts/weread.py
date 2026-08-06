#!/usr/bin/env python3
"""微信读书：书架体检 + 划线摄入。

跟 vendor/WeChatReading（腾讯官方 skill）的分工：
  官方那套是**被动应答** —— 你问哪本书它查哪本，教 agent 怎么打 curl。
  本 skill 补两件它没有的事：
    1. 主动扫全架做聚合分析（哪些书在吃灰、读了一半扔了、投入多没读完）
    2. 划线导出成 Markdown，接知识库的 raw/ → wiki/ 沉淀契约

## 一个实测得出的关键结论

`readUpdateTime` **不是「最后阅读时间」，而是「书架条目更新时间」**。
实测：四本 readUpdateTime 显示 73 天前的书，progress 全是 0%、
readingTime 只有 0～43 秒、isStartReading=0 —— 那天是批量加入书架，不是读了。

所以判断「有没有真读过」必须看 progress / readingTime / isStartReading，
只看 readUpdateTime 会把「囤了没翻」误判成「读过但搁下了」。

用法：
  weread.py shelf                     # 书架体检（分类：吃灰/半途/读完…）
  weread.py notes <bookId|书名关键词>  # 某本书的划线 → Markdown
  weread.py notebooks                 # 哪些书有笔记
  weread.py stats [--mode monthly]    # 阅读统计
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

CN = timezone(timedelta(hours=8))
GATEWAY = "https://i.weread.qq.com/api/agent/gateway"
KEYCHAIN_SERVICE = "kg-weread-apikey"
KEYCHAIN_ACCOUNT = "weread"

# 官方 skill 要求每次请求必带 skill_version，从 vendor 的 SKILL.md 里读，
# 避免上游升版本后这里写死的值失效。
_VENDOR_SKILL = (Path(__file__).resolve().parent.parent.parent
                 / "vendor" / "WeChatReading" / "skills" / "SKILL.md")
FALLBACK_VERSION = "1.0.4"

# 判定阈值
MIN_INTERVAL = 1.2       # 两次请求最小间隔（秒）。实测连发会被限流
CACHE_TTL = 6 * 3600     # 进度缓存有效期，避免反复跑 shelf 打满配额

STALE_DAYS = 60          # 超过这么久没动就算「搁下了」
TOUCHED_SECONDS = 300    # 累计不到 5 分钟，基本等于没翻过
HALFWAY_MIN = 5          # progress 在 5%~85% 之间算「读了一半」
HALFWAY_MAX = 85


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def skill_version() -> str:
    try:
        m = re.search(r"skill_version[\"']?\s*[:=]\s*[\"']?(\d+\.\d+\.\d+)",
                      _VENDOR_SKILL.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
        m = re.search(r"version:\s*(\d+\.\d+\.\d+)",
                      _VENDOR_SKILL.read_text(encoding="utf-8"))
        if m:
            return m.group(1)
    except OSError:
        pass
    return FALLBACK_VERSION


def api_key() -> str:
    k = os.environ.get("WEREAD_API_KEY")
    if k:
        return k.strip()
    try:
        out = subprocess.run(
            ["security", "find-generic-password",
             "-a", KEYCHAIN_ACCOUNT, "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=15, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    raise SystemExit(
        "[错误] 没找到 API Key。两种给法：\n"
        "  1. 存进 Keychain（推荐，不落明文）：\n"
        f"     security add-generic-password -a {KEYCHAIN_ACCOUNT} "
        f"-s {KEYCHAIN_SERVICE} -w '<wrk-xxx>' -U\n"
        "  2. export WEREAD_API_KEY=wrk-xxx\n"
        "  Key 从 https://weread.qq.com/r/weread-skills 扫码获取")


_LAST_CALL = [0.0]


def call(api_name: str, retries: int = 3, **params) -> dict:
    """打 gateway。带节流和重试 —— 微信读书对连续请求限得很紧
    （实测逐本查 19 本进度会大面积 errcode -2014「请求频率超限」）。"""
    gap = time.time() - _LAST_CALL[0]
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _LAST_CALL[0] = time.time()

    body = {"api_name": api_name, "skill_version": skill_version(), **params}
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key()}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:200]
        if e.code == 401:
            raise SystemExit("[错误] API Key 无效或已失效，去 "
                             "https://weread.qq.com/r/weread-skills 重新获取")
        # 499 + errcode -2014 是频率超限，退避重试
        if ("-2014" in detail or e.code in (429, 499)) and retries > 0:
            wait = (4 - retries) * 3 + 3
            eprint(f"[..] 频率超限，等 {wait}s 重试")
            time.sleep(wait)
            return call(api_name, retries=retries - 1, **params)
        raise SystemExit(f"[错误] HTTP {e.code}: {detail}")
    except Exception as e:
        raise SystemExit(f"[错误] 请求失败：{type(e).__name__}: {e}")
    if data.get("errcode") not in (None, 0):
        raise SystemExit(f"[错误] 接口返回 errcode={data.get('errcode')}: "
                         f"{data.get('errmsg') or data}")
    return data


def cache_path() -> Path:
    d = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    d = d / "kg-weread"
    d.mkdir(parents=True, exist_ok=True)
    return d / "progress.json"


def load_cache() -> dict:
    try:
        raw = json.loads(cache_path().read_text(encoding="utf-8"))
        if time.time() - raw.get("_ts", 0) < CACHE_TTL:
            return raw.get("data") or {}
    except (OSError, ValueError):
        pass
    return {}


def save_cache(data: dict) -> None:
    try:
        cache_path().write_text(
            json.dumps({"_ts": time.time(), "data": data}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass


def days_since(ts: Optional[int]) -> Optional[int]:
    if not ts:
        return None
    return int((time.time() - ts) / 86400)


def fmt_dur(sec: Optional[int]) -> str:
    sec = sec or 0
    if sec < 60:
        return f"{sec} 秒"
    if sec < 3600:
        return f"{sec // 60} 分钟"
    return f"{sec / 3600:.1f} 小时"


def fmt_day(ts: Optional[int]) -> str:
    return datetime.fromtimestamp(ts, CN).strftime("%Y-%m-%d") if ts else "-"


# ------------------------------------------------------------------ shelf

def cmd_shelf(args) -> str:
    shelf = call("/shelf/sync")
    books = shelf.get("books") or []
    albums = shelf.get("albums") or []
    if not books:
        return "书架是空的。"

    cache = {} if args.refresh else load_cache()
    todo = [b for b in books if str(b.get("bookId")) not in cache]
    if cache:
        eprint(f"[..] 命中缓存 {len(cache)} 本"
               + (f"，还需查 {len(todo)} 本" if todo else "，无需请求"))
    if todo:
        eprint(f"[..] 逐本查进度（{len(todo)} 次请求，每次间隔 "
               f"{MIN_INTERVAL}s 防频控）…")
    rows = []
    for i, b in enumerate(books, 1):
        bid = str(b.get("bookId"))
        prog = cache.get(bid)
        if prog is None:
            try:
                prog = (call("/book/getprogress", bookId=bid).get("book") or {})
                cache[bid] = prog
            except SystemExit as e:
                eprint(f"[warn] {b.get('title','')[:16]} 进度查询失败：{e}")
                prog = {}
        rows.append({
            "title": b.get("title", ""),
            "author": b.get("author", ""),
            "bookId": bid,
            "finished": bool(b.get("finishReading")),
            "shelf_time": b.get("readUpdateTime"),
            "progress": prog.get("progress") or 0,
            "reading_time": prog.get("readingTime") or 0,
            "started": bool(prog.get("isStartReading")),
            "chapter": prog.get("chapterIdx"),
            "read_time": prog.get("updateTime"),
        })
        if todo and i % 5 == 0:
            eprint(f"    {i}/{len(books)}")
    save_cache(cache)

    # 分类。注意用 reading_time/progress 判断，不用 shelf_time ——
    # 后者只是加入书架的时间，实测会把「囤了没翻」误判成「读过」。
    # 微信读书允许手动「标记已读」，那种 readingTime 极短。
    # 混在「读完了」里会给人虚假的成就感，单独拎出来。
    finished = [r for r in rows
                if r["finished"] and r["reading_time"] >= TOUCHED_SECONDS]
    marked_only = [r for r in rows
                   if r["finished"] and r["reading_time"] < TOUCHED_SECONDS]
    untouched = [r for r in rows
                 if not r["finished"] and r["reading_time"] < TOUCHED_SECONDS]
    halfway = [r for r in rows
               if not r["finished"] and r["reading_time"] >= TOUCHED_SECONDS
               and HALFWAY_MIN <= r["progress"] <= HALFWAY_MAX]
    invested = [r for r in rows
                if not r["finished"] and r["reading_time"] >= 3600
                and r not in halfway]
    other = [r for r in rows
             if r not in finished + marked_only + untouched + halfway + invested]

    total_time = sum(r["reading_time"] for r in rows)
    L = ["---",
         f"title: 书架体检（{len(books)} 本）",
         "source: 微信读书",
         "platform: 微信读书",
         f"fetched: {datetime.now(CN).strftime('%Y-%m-%d %H:%M')}",
         f"books: {len(books)}",
         f"finished: {len(finished)}",
         "---", "",
         f"# 书架体检 · {len(books)} 本"
         + (f" + {len(albums)} 个有声" if albums else ""), "",
         f"> 累计阅读 {fmt_dur(total_time)} · 真读完 {len(finished)} 本 · "
         f"没真正翻过 {len(untouched)} 本", "",
         "> ⚠️ 判断依据是 `readingTime`/`progress`，不是书架里显示的时间 —— ",
         "> `readUpdateTime` 其实是「加入书架时间」，囤书那天会批量刷新。", ""]

    def block(name: str, rs: list, note: str = "", show=("time", "prog")) -> None:
        nonlocal L          # 否则 L.append 之外的赋值会让 Python 当成局部变量
        if not rs:
            return
        L.append(f"## {name} · {len(rs)} 本")
        L.append("")
        if note:
            L += [f"> {note}", ""]
        for r in sorted(rs, key=lambda x: -(x["reading_time"])):
            bits = []
            if "prog" in show and r["progress"]:
                bits.append(f"{r['progress']}%")
            if "time" in show and r["reading_time"]:
                bits.append(fmt_dur(r["reading_time"]))
            if r["chapter"]:
                bits.append(f"第 {r['chapter']} 章")
            d = days_since(r["read_time"] or r["shelf_time"])
            if d is not None:
                bits.append(f"{d} 天前")
            tail = ("（" + " · ".join(bits) + "）") if bits else ""
            t = r["title"]
            if len(t) > 34:                 # 有些书名带一长串宣传语
                t = t[:34] + "…"
            L.append(f"- **{t}** {tail}")
        L.append("")

    block("读完了", finished, show=("time",))
    block("标记了已读，但没什么阅读时长", marked_only,
          "微信读书可以手动标「已读」。这些是标记过但 readingTime 很短的，"
          "要么在别处读的（纸书/其他 App），要么当时只是标记一下。",
          show=("time",))
    block("读了一半搁下的", halfway,
          "这类最值得处理 —— 已经投入过，接着读的成本比重新开始低。")
    block("投入不少但没读完", invested, "累计超过 1 小时。")
    block("囤了没真正翻过", untouched,
          f"累计阅读不足 {TOUCHED_SECONDS // 60} 分钟。买了/加了书架但没开始。",
          show=())
    block("其他", other)

    L += ["---", "",
          "_由 kg-weread 生成。想看某本的划线：`weread.py notes <书名>`_", ""]
    return "\n".join(L)


# ------------------------------------------------------------------ notes

def resolve_book(keyword: str) -> tuple:
    """书名关键词 → (bookId, title)。已经是 bookId 就直接用。"""
    if re.fullmatch(r"[A-Za-z0-9_]{6,}", keyword):
        return keyword, keyword
    books = (call("/shelf/sync").get("books") or [])
    hits = [b for b in books if keyword in (b.get("title") or "")]
    if not hits:
        titles = "、".join((b.get("title") or "")[:14] for b in books[:8])
        raise SystemExit(f"[错误] 书架里没找到「{keyword}」。\n  书架前几本：{titles}…")
    if len(hits) > 1:
        opts = "\n".join(f"  - {b['title']}（{b['bookId']}）" for b in hits)
        raise SystemExit(f"[错误] 「{keyword}」匹配到多本，指定完整书名或 bookId：\n{opts}")
    return hits[0]["bookId"], hits[0].get("title", "")


def cmd_notes(args) -> str:
    bid, title = resolve_book(args.book)
    eprint(f"[..] 取划线：{title}")
    data = call("/book/bookmarklist", bookId=bid)
    marks = data.get("updated") or data.get("bookmarks") or []
    reviews = []
    try:
        rv = call("/review/list", bookId=bid, listType=11)
        reviews = rv.get("reviews") or []
    except SystemExit as e:
        eprint(f"[warn] 想法拉取失败：{e}")

    if not marks and not reviews:
        # 自己没划线时退到「社区热门划线」—— 对没读过的书反而更有用，
        # 能快速看到这本书里别人认为重要的是什么。
        eprint("[..] 你在这本书没有划线，取社区热门划线")
        try:
            best = call("/book/bestbookmarks", bookId=bid).get("items") or []
        except SystemExit as e:
            best = []
            eprint(f"[warn] 热门划线也没取到：{e}")
        if not best:
            return f"# {title}\n\n_这本书没有划线，社区热门划线也没取到。_\n"
        L = ["---",
             f"title: {title} · 社区热门划线",
             f"source: https://weread.qq.com/web/reader/{bid}",
             "platform: 微信读书",
             f"book_id: {bid}",
             f"fetched: {datetime.now(CN).strftime('%Y-%m-%d %H:%M')}",
             "kind: 社区热门（非本人划线）",
             f"marks: {len(best)}",
             "---", "",
             f"# {title} · 社区热门划线", "",
             "> ⚠️ **这不是你的划线** —— 你在这本书没有划线记录。",
             "> 以下是社区里被划得最多的段落，可以当作「这本书讲什么」的快速预览，",
             "> 但沉淀时要写明来源，别混成自己的阅读所得。", ""]
        for it in best:
            txt = (it.get("markText") or "").strip()
            cnt = it.get("totalCount") or it.get("count")
            if txt:
                L += ["> " + txt.replace("\n", "\n> "),
                      f"> — {cnt} 人划过" if cnt else "", ""]
        return "\n".join(L)

    # 按章节归组，章节内按位置排序，尽量还原阅读顺序
    by_chapter: dict = {}
    for m in marks:
        ch = m.get("chapterUid") or 0
        by_chapter.setdefault(ch, []).append(m)

    chap_titles = {}
    try:
        ci = call("/book/chapterinfo", bookId=bid)
        for c in (ci.get("data") or [{}])[0].get("updated", []) if ci.get("data") else []:
            chap_titles[c.get("chapterUid")] = c.get("title", "")
    except SystemExit:
        pass

    L = ["---",
         f"title: {title} · 划线摘录",
         f"source: https://weread.qq.com/web/reader/{bid}",
         "platform: 微信读书",
         f"book_id: {bid}",
         f"fetched: {datetime.now(CN).strftime('%Y-%m-%d %H:%M')}",
         f"marks: {len(marks)}",
         f"thoughts: {len(reviews)}",
         "---", "",
         f"# {title}", "",
         f"> 划线 {len(marks)} 条"
         + (f" · 想法 {len(reviews)} 条" if reviews else ""), ""]

    for ch in sorted(by_chapter):
        ms = sorted(by_chapter[ch], key=lambda m: m.get("range") or "")
        name = chap_titles.get(ch) or (f"第 {ch} 章" if ch else "未分章")
        L += [f"## {name}", ""]
        for m in ms:
            txt = (m.get("markText") or "").strip()
            if txt:
                L += ["> " + txt.replace("\n", "\n> "), ""]

    if reviews:
        L += ["## 我的想法", ""]
        for r in reviews:
            content = (r.get("review") or {}).get("content") or r.get("content") or ""
            abstract = (r.get("review") or {}).get("abstract") or ""
            if not content.strip():
                continue
            if abstract:
                L += [f"> {abstract.strip()}", ""]
            L += [f"**想法**：{content.strip()}", ""]

    L += ["---", "",
          "_原文摘录，沉淀时请提炼而非照搬 —— 划线是当时的注意力，"
          "结论要你自己下。_", ""]
    return "\n".join(L)


# ------------------------------------------------------------- notebooks

def cmd_notebooks(args) -> str:
    data = call("/user/notebooks")
    books = data.get("books") or []
    if not books:
        return "还没有任何笔记。"
    rows = []
    for it in books:
        b = it.get("book") or {}
        rows.append((it.get("noteCount") or 0, it.get("reviewCount") or 0,
                     it.get("bookmarkCount") or 0, b.get("title", ""),
                     b.get("bookId", "")))
    rows.sort(reverse=True)
    L = [f"# 有笔记的书（{len(rows)} 本）", "",
         "| 书名 | 划线 | 想法 | 书签 |", "|---|---|---|---|"]
    for note, review, mark, title, _ in rows:
        L.append(f"| {title} | {note} | {review} | {mark} |")
    L += ["", "_看某本的划线内容：`weread.py notes <书名>`_"]
    return "\n".join(L)


# ------------------------------------------------------------------ stats

def cmd_stats(args) -> str:
    d = call("/readdata/detail", mode=args.mode)
    total = d.get("totalReadTime") or 0
    L = [f"# 阅读统计 · {args.mode}", "",
         f"- 总时长：{fmt_dur(total)}",
         f"- 有效阅读天数：{d.get('readDays', 0)}",
         f"- 日均：{fmt_dur(d.get('dayAverageReadTime'))}"]
    if d.get("compare") is not None:
        c = d["compare"]
        L.append(f"- 与上一周期比：{'+' if c >= 0 else ''}{c * 100:.0f}%")
    longest = d.get("readLongest") or []
    if longest:
        L += ["", "## 读得最多", ""]
        for it in longest[:10]:
            b = it.get("book") or {}
            L.append(f"- {b.get('title', '?')} — {fmt_dur(it.get('readTime'))}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(
        description="微信读书：书架体检 + 划线摄入（补 vendor/WeChatReading 缺的聚合分析与沉淀）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("shelf", help="书架体检：吃灰 / 半途 / 读完 分类")
    p.add_argument("--refresh", action="store_true",
                   help="忽略缓存重新拉进度（默认缓存 6 小时）")
    p.set_defaults(fn=cmd_shelf)

    p = sub.add_parser("notes", help="某本书的划线 → Markdown")
    p.add_argument("book", help="书名关键词或 bookId")
    p.set_defaults(fn=cmd_notes)

    p = sub.add_parser("notebooks", help="哪些书有笔记")
    p.set_defaults(fn=cmd_notebooks)

    p = sub.add_parser("stats", help="阅读统计")
    p.add_argument("--mode", default="monthly",
                   choices=["weekly", "monthly", "annually", "overall"])
    p.set_defaults(fn=cmd_stats)

    for s in sub.choices.values():
        s.add_argument("--out", default=None, help="输出 md；不给则打到 stdout")

    args = ap.parse_args()
    md = args.fn(args)
    if args.out:
        pth = Path(args.out)
        pth.parent.mkdir(parents=True, exist_ok=True)
        pth.write_text(md, encoding="utf-8")
        eprint(f"[ok] 写入 {pth}（{len(md)} 字符）")
    else:
        print(md)


if __name__ == "__main__":
    main()
