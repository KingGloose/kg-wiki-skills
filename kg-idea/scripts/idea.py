#!/usr/bin/env python3
"""灵感库读写。纯文件操作，判断交给 AI。

## 设计取舍

**不做 frontmatter。** 库里现有的 wiki 页都没有 —— 用 `> 引用块` 写元信息，
靠 `[[双链]]` 关联。灵感页跟着同一套契约，这样 Obsidian 里表现一致，
`kg-ask` 也能直接搜到。

**不做图谱生成。** 参考过 Win1011/ideabubble（MIT，审计通过），
它的 build_graph.py 有 1915 行，比 Obsidian 自带 graph view 多的只有
时间线视图和「继续聊聊」。后者实际是字符串模板：

    f"如果把「{title}」做成一个最小产品，第一屏应该让用户看到什么？"

五句固定句式填标题，跟灵感内容无关。AI 读了正文再发散，比这个准得多。
而且它的图谱是静态快照（记完要重跑脚本），Obsidian 的是实时的。
所以只借「幽灵」这个概念 —— 而它连实现都不用借，Obsidian 本来就把
指向不存在文件的双链显示成虚节点。

## 用法

    idea.py new "标题" --body "正文" [--topics 产品,AI] [--links 别的灵感]
    idea.py list [--days 30]
    idea.py ghosts              提过但还没展开的（双链指向不存在的页）
    idea.py next                抽一个旧灵感（AI 读完再发散，脚本不写话术）
    idea.py show "标题"
    idea.py append "标题" --body "补充内容"
    idea.py graduate "标题" --to "wiki/AI/xxx.md"
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "kg-media-to-text"))
from media_to_text import find_vault, VaultNotFoundError   # noqa: E402

CN = timezone(timedelta(hours=8))
IDEAS = "ideas"


def ideas_dir(vault: Path) -> Path:
    d = vault / IDEAS
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(title: str) -> str:
    """文件名 = 标题，不加日期前缀。

    为什么不加：双链是这套东西的核心，`[[日报通知反选]]` 比
    `[[2026-08-08-日报通知反选]]` 好写得多。日期写在正文的元信息行里。
    """
    name = re.sub(r'[/\\:*?"<>|]', "-", title).strip()
    return (name or "未命名")[:80]


def parse(path: Path) -> dict:
    """读一篇灵感。元信息在开头的 `> ` 引用块里。"""
    text = path.read_text(encoding="utf-8")
    meta = {"title": path.stem, "path": path, "body": text}
    m = re.search(r"^>\s*\*\*记于\*\*[：:]\s*(\S+)", text, re.M)
    if m:
        meta["created"] = m.group(1)
    m = re.search(r"^>\s*\*\*主题\*\*[：:]\s*(.+)$", text, re.M)
    if m:
        meta["topics"] = [t.strip() for t in re.split(r"[、,，]", m.group(1))
                          if t.strip()]
    m = re.search(r"^>\s*\*\*已毕业\*\*[：:]\s*\[\[([^\]]+)\]\]", text, re.M)
    if m:
        meta["graduated_to"] = m.group(1)
    # 双链（排除元信息行里的毕业指向）
    body_only = re.sub(r"^>.*$", "", text, flags=re.M)
    meta["links"] = re.findall(r"\[\[([^\]|]+)", body_only)
    # 有没有被追问过
    meta["has_followup"] = "## 追问" in text or "## 补充" in text
    return meta


def load_all(vault: Path) -> list:
    out = []
    for p in sorted(ideas_dir(vault).glob("*.md")):
        if p.name.lower() in {"readme.md", "index.md"}:
            continue
        try:
            out.append(parse(p))
        except OSError:
            pass
    return out


def cmd_new(vault: Path, args) -> int:
    d = ideas_dir(vault)
    path = d / f"{safe_name(args.title)}.md"
    now = datetime.now(CN)

    if path.exists():
        print(f"⚠ 已存在同名灵感：{path.name}", file=sys.stderr)
        print(f"   要补充内容用：idea.py append \"{args.title}\" --body \"...\"",
              file=sys.stderr)
        return 1

    lines = [f"# {args.title}", ""]
    meta = [f"> **记于**：{now.strftime('%Y-%m-%d %H:%M')}"]
    if args.topics:
        meta.append(f"> **主题**：{args.topics}")
    if args.source:
        meta.append(f"> **触发**：{args.source}")
    lines += meta + [""]
    lines.append(args.body or "（还没写正文）")
    lines.append("")

    if args.quote:
        lines += ["原话：", f"> {args.quote}", ""]

    if args.links:
        rel = "、".join(f"[[{x.strip()}]]" for x in args.links.split(",")
                        if x.strip())
        lines += [f"关联：{rel}", ""]

    path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"ok": True, "path": str(path),
                      "rel": f"{IDEAS}/{path.name}"}, ensure_ascii=False))
    return 0


def cmd_append(vault: Path, args) -> int:
    path = ideas_dir(vault) / f"{safe_name(args.title)}.md"
    if not path.is_file():
        print(f"✗ 找不到灵感「{args.title}」", file=sys.stderr)
        return 1
    now = datetime.now(CN).strftime("%Y-%m-%d %H:%M")
    section = args.section or "补充"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n## {section}（{now}）\n\n{args.body}\n")
    print(f"✓ 已追加到 {IDEAS}/{path.name}")
    return 0


def cmd_list(vault: Path, args) -> int:
    rows = load_all(vault)
    if args.days:
        cutoff = (datetime.now(CN) - timedelta(days=args.days)).strftime("%Y-%m-%d")
        rows = [r for r in rows if (r.get("created") or "9999") >= cutoff]
    rows.sort(key=lambda r: r.get("created") or "", reverse=True)

    if args.json:
        print(json.dumps([{k: (str(v) if isinstance(v, Path) else v)
                           for k, v in r.items() if k != "body"}
                          for r in rows], ensure_ascii=False, indent=2))
        return 0

    if not rows:
        print("灵感库还是空的")
        return 0
    print(f"# 灵感 · {len(rows)} 条\n")
    for r in rows:
        flags = []
        if r.get("graduated_to"):
            flags.append("已毕业")
        elif not r.get("has_followup"):
            flags.append("待追问")
        if r.get("links"):
            flags.append(f"{len(r['links'])} 链")
        tag = f"  [{' · '.join(flags)}]" if flags else ""
        print(f"  {r.get('created', '?')[:10]}  {r['title']}{tag}")
        if r.get("topics"):
            print(f"              主题：{'、'.join(r['topics'])}")
    return 0


def cmd_ghosts(vault: Path, args) -> int:
    """双链指向了不存在的页 —— 你提过但还没展开的东西。

    这是从 ideabubble 借来的唯一概念。Obsidian 里这些会显示成虚节点，
    但它不会告诉你「哪些虚节点最该被展开」（被指向次数最多的）。
    """
    rows = load_all(vault)
    existing = {r["title"] for r in rows}
    # wiki/ 里的页也算存在
    for p in (vault / "wiki").rglob("*.md"):
        existing.add(p.stem)

    ghost = {}
    for r in rows:
        for link in r["links"]:
            name = link.split("/")[-1].replace(".md", "").strip()
            if name and name not in existing:
                ghost.setdefault(name, []).append(r["title"])

    if args.json:
        print(json.dumps([{"name": k, "referred_by": v, "count": len(v)}
                          for k, v in sorted(ghost.items(),
                                             key=lambda x: -len(x[1]))],
                         ensure_ascii=False, indent=2))
        return 0

    if not ghost:
        print("没有幽灵 —— 所有双链都指向已存在的页")
        return 0
    print(f"# 幽灵 · {len(ghost)} 个提过但没展开的\n")
    for name, refs in sorted(ghost.items(), key=lambda x: -len(x[1])):
        print(f"  {name}（被 {len(refs)} 处提到）")
        for r in refs[:3]:
            print(f"      ← {r}")
    return 0


def cmd_next(vault: Path, args) -> int:
    """抽一个旧灵感出来。**发散角度由 AI 读完正文后自己想。**

    ideabubble 用固定模板生成五句发散话题，跟内容无关。这里只负责挑，
    输出完整正文让 AI 现场判断。
    """
    rows = [r for r in load_all(vault) if not r.get("graduated_to")]
    if not rows:
        print("灵感库里没有可发散的（都毕业了或者是空的）")
        return 0

    # 优先没被追问过的，其次最久没动的
    pending = [r for r in rows if not r.get("has_followup")]
    pool = pending or rows
    pick = random.choice(pool) if args.random else min(
        pool, key=lambda r: r.get("created") or "")

    if args.json:
        print(json.dumps({"title": pick["title"],
                          "created": pick.get("created"),
                          "topics": pick.get("topics"),
                          "links": pick["links"],
                          "body": pick["body"],
                          "rel": f"{IDEAS}/{pick['path'].name}",
                          "never_followed_up": not pick.get("has_followup")},
                         ensure_ascii=False, indent=2))
        return 0
    print(pick["body"])
    return 0


def cmd_show(vault: Path, args) -> int:
    path = ideas_dir(vault) / f"{safe_name(args.title)}.md"
    if not path.is_file():
        cands = [r["title"] for r in load_all(vault) if args.title in r["title"]]
        print(f"✗ 找不到「{args.title}」" +
              (f"，你是指：{'、'.join(cands[:5])}？" if cands else ""),
              file=sys.stderr)
        return 1
    print(path.read_text(encoding="utf-8"))
    return 0


def cmd_graduate(vault: Path, args) -> int:
    """灵感想清楚了 → 提升成 wiki 页。

    为什么要有这一步：ideabubble 里泡泡永远是泡泡，库会越堆越多。
    这个库有 wiki/ 那层，灵感该有毕业路径。原灵感页保留（记录来路），
    加一行指向沉淀页。
    """
    path = ideas_dir(vault) / f"{safe_name(args.title)}.md"
    if not path.is_file():
        print(f"✗ 找不到灵感「{args.title}」", file=sys.stderr)
        return 1
    target = (vault / args.to)
    if not target.is_file():
        print(f"✗ 目标沉淀页不存在：{args.to}", file=sys.stderr)
        print("   先把 wiki 页写好，再来毕业", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    if "**已毕业**" in text:
        print(f"⚠ 「{args.title}」已经毕业过了", file=sys.stderr)
        return 1

    now = datetime.now(CN).strftime("%Y-%m-%d")
    # 相对 ideas/ 的路径，Obsidian 双链能跳
    rel = "../" + args.to
    lines = text.split("\n")
    # 插在元信息块最后一行之后
    last_meta = max((i for i, l in enumerate(lines[:12]) if l.startswith("> ")),
                    default=1)
    lines.insert(last_meta + 1,
                 f"> **已毕业**：[[{rel}]]（{now}）—— 想清楚了，沉淀在那边")
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✓ 「{args.title}」已标记毕业 → {args.to}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="灵感库（判断交给 AI，脚本只管读写）")
    ap.add_argument("--vault", default=None, help="库根，默认自动定位")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("new", help="记一条灵感")
    p.add_argument("title")
    p.add_argument("--body", default="")
    p.add_argument("--topics", default="", help="逗号分隔")
    p.add_argument("--links", default="", help="关联的灵感标题，逗号分隔")
    p.add_argument("--quote", default="", help="用户的原话")
    p.add_argument("--source", default="", help="什么场景下想到的")

    p = sub.add_parser("append", help="补充内容")
    p.add_argument("title")
    p.add_argument("--body", required=True)
    p.add_argument("--section", default="", help="小节标题，默认「补充」")

    p = sub.add_parser("list")
    p.add_argument("--days", type=int, default=0)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("ghosts", help="提过但没展开的")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("next", help="抽一个旧灵感发散")
    p.add_argument("--random", action="store_true")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("show")
    p.add_argument("title")

    p = sub.add_parser("graduate", help="提升成 wiki 页")
    p.add_argument("title")
    p.add_argument("--to", required=True, help="wiki/AI/xxx.md")

    args = ap.parse_args()
    try:
        vault = find_vault(__file__, explicit=args.vault)
    except VaultNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2

    return {"new": cmd_new, "append": cmd_append, "list": cmd_list,
            "ghosts": cmd_ghosts, "next": cmd_next, "show": cmd_show,
            "graduate": cmd_graduate}[args.cmd](vault, args)


if __name__ == "__main__":
    sys.exit(main())
