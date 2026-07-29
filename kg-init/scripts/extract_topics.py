#!/usr/bin/env python3
"""从旧笔记里抽取标题，生成 index.md 的唤醒条目草稿。

用途：改造时旧笔记整体封存进 archive/，但**得让 index 知道里面有什么**——
否则等于把知识埋了。本脚本扫标题结构，产出草稿供 AI 与用户一起精简。

**输出是草稿，不是终稿。** 标题往往冗长、重复、层级混乱，
需要 AI 归并同类、删掉无信息量的（如"总结""其他"），再写进 index.md。

用法:
  python extract_topics.py <archive目录>                  # 按目录分组输出标题
  python extract_topics.py <目录> --level 2               # 只取 h1-h2（默认 2）
  python extract_topics.py <目录> --min-len 3             # 过滤过短标题
  python extract_topics.py <目录> --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".venv", "__pycache__", ".trash"}
# 无信息量的标题，进 index 是噪声
NOISE = {"总结", "其他", "小结", "补充", "note", "notes", "todo", "待办",
         "参考", "参考资料", "附录", "前言", "简介", "介绍", "概述", "目录"}


def is_noise(t: str) -> bool:
    low = t.strip().lower().rstrip("：:")
    if low in NOISE:
        return True
    # 纯数字/纯符号编号
    if re.fullmatch(r"[\d\s.、\-—_()（）]+", low):
        return True
    return False


def scan(root: Path, max_level: int, min_len: int) -> dict:
    by_domain: dict[str, list[dict]] = defaultdict(list)
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        heads = []
        for m in HEADING.finditer(text):
            level = len(m.group(1))
            title = m.group(2).strip()
            # 去掉行内 markdown 与编号前缀
            title = re.sub(r"[*_`~]", "", title)
            title = re.sub(r"^[\d.、]+\s*", "", title).strip()
            if level > max_level or len(title) < min_len or is_noise(title):
                continue
            heads.append({"level": level, "title": title})

        if not heads:
            continue
        domain = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"
        by_domain[domain].append({
            "file": str(rel),
            "stem": p.stem,
            "headings": heads,
            "chars": len(text),
        })
    return dict(by_domain)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--level", type=int, default=2, help="最深取到几级标题（默认 2）")
    ap.add_argument("--min-len", type=int, default=2, help="标题最短字数（默认 2）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"[错误] 目录不存在: {root}", file=sys.stderr)
        return 1

    data = scan(root, args.level, args.min_len)
    if not data:
        print(f"[i] {root} 下没找到含标题的 md 文件")
        return 0

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    total_files = sum(len(v) for v in data.values())
    total_heads = sum(len(f["headings"]) for v in data.values() for f in v)
    print(f"# index.md 唤醒条目草稿\n")
    print(f"> 来源: {root}")
    print(f"> 扫描 {total_files} 个文件，抽出 {total_heads} 个标题（已过滤噪声标题）")
    print(f">")
    print(f"> **这是草稿。** 交给 AI 做三件事再写进 index.md：")
    print(f">   1. 归并同类（同一知识点的多个说法合成一条）")
    print(f">   2. 删掉纯通用且价值低的")
    print(f">   3. 每个领域压缩成几行**可快速扫描**的关键词，不要照抄标题树\n")

    for domain, files in sorted(data.items()):
        print(f"\n## {domain}\n")
        for f in sorted(files, key=lambda x: -x["chars"]):
            tops = [h["title"] for h in f["headings"] if h["level"] == 1]
            subs = [h["title"] for h in f["headings"] if h["level"] > 1]
            label = tops[0] if tops else f["stem"]
            print(f"- **{f['stem']}** (`{f['file']}`)")
            if subs:
                # 一行塞多个，便于扫描
                line, out = "", []
                for s in subs:
                    if len(line) + len(s) > 100:
                        out.append(line.rstrip("、"))
                        line = ""
                    line += s + "、"
                if line:
                    out.append(line.rstrip("、"))
                for l in out[:6]:
                    print(f"    {l}")
                if len(out) > 6:
                    print(f"    …（另有 {len(subs) - sum(len(o.split('、')) for o in out[:6])} 个小节）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
