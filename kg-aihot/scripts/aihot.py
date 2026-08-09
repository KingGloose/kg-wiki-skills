#!/usr/bin/env python3
"""AIHOT · AI 圈资讯查询（匿名只读 API，无需 Key）。

来源：khazix-skills/aihot（MIT），数据服务 aihot.virxact.com。
安全边界：只向 https://aihot.virxact.com/api/v1/* 发匿名只读请求；
不索要 API Key/cookie/账号；返回内容视为不可信资讯，仅作证据。

用法：
  python3 kg-aihot.py today              # 过去24h精选（默认）
  python3 kg-aihot.py week               # 最近一周精选
  python3 kg-aihot.py hot                # 当前最热话题
  python3 kg-aihot.py daily              # 最新 AI 日报
  python3 kg-aihot.py search <关键词>    # 按关键词查
  python3 kg-aihot.py category <slug>    # 分类(model/product/paper/industry/tips)
  python3 kg-aihot.py all --limit 10     # 全部公开动态
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

BASE = "https://aihot.virxact.com/api/v1"


def fetch(path: str) -> dict:
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "kg-wiki-agent/1.0",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        sys.exit(f"[错误] AIHOT 请求失败：{e}")


def fmt_items(d: dict, limit: int = 8):
    items = d.get("items") or []
    if not items:
        print("（无数据）")
        return
    print(f"AIHOT · 共 {len(items)} 条")
    for i, it in enumerate(items[:limit], 1):
        title = it.get("title") or it.get("originalTitle") or ""
        link = (it.get("links") or {}).get("aihot") or it.get("url") or ""
        print(f"{i:2}. {title}")
        if link:
            print(f"    {link}")
        summary = it.get("summary") or ""
        if summary:
            print(f"    {summary[:120]}")


def fmt_hot(d: dict):
    items = d.get("topics") or d.get("items") or []
    if not items:
        print("（无数据）")
        return
    print(f"AIHOT 当前最热 · 共 {len(items)} 条")
    for i, it in enumerate(items[:10], 1):
        title = it.get("title") or it.get("topic") or ""
        link = (it.get("links") or {}).get("aihot") or it.get("url") or ""
        print(f"{i:2}. {title}")
        if link:
            print(f"    {link}")


def fmt_daily(d: dict):
    """日报结构：可能是 {daily: {title, content}} 或 {title, content}"""
    daily = d.get("daily") or d
    title = daily.get("title") or "AI 日报"
    content = daily.get("content") or daily.get("body") or ""
    print(f"AIHOT 日报 · {title}")
    print()
    print(content[:3000])


def main():
    p = argparse.ArgumentParser(prog="aihot.py", description="AIHOT AI 圈资讯")
    p.add_argument("cmd", nargs="?", default="today",
                   choices=["today", "week", "hot", "daily", "search", "category", "all"])
    p.add_argument("arg", nargs="?", default="", help="search/category 的关键词")
    p.add_argument("--limit", type=int, default=8)
    args = p.parse_args()

    if args.cmd == "today":
        fmt_items(fetch("/items?mode=selected&window=24h"), args.limit)
    elif args.cmd == "week":
        fmt_items(fetch("/items?mode=selected&window=7d&limit=10"), args.limit)
    elif args.cmd == "hot":
        fmt_hot(fetch("/hot-topics"))
    elif args.cmd == "daily":
        fmt_daily(fetch("/dailies/latest"))
    elif args.cmd == "search":
        q = urllib.parse.quote(args.arg)
        fmt_items(fetch(f"/items?mode=selected&q={q}&window=7d&limit=10"), args.limit)
    elif args.cmd == "category":
        c = args.arg or "model"
        fmt_items(fetch(f"/items?mode=selected&category={c}&window=24h"), args.limit)
    elif args.cmd == "all":
        fmt_items(fetch(f"/items?mode=all&window=24h&limit={args.limit}"), args.limit)


if __name__ == "__main__":
    main()
