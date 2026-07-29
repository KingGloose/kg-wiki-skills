#!/usr/bin/env python3
"""扫描现有笔记目录，产出改造前的体检报告。

这是 kg-init 的第一步：**先看清家底，再决定怎么改造**。
只读不写，不动任何文件。

用法:
  python analyze_notes.py <笔记目录>              # 人类可读报告
  python analyze_notes.py <笔记目录> --json       # 结构化输出
  python analyze_notes.py <笔记目录> --top 30     # 显示更多大文件/领域
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# 常见笔记/资源扩展名
NOTE_EXT = {".md", ".markdown", ".txt"}
DOC_EXT = {".doc", ".docx", ".pdf", ".ppt", ".pptx", ".xls", ".xlsx", ".mht", ".mhtml"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg", ".tiff"}
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".venv", "__pycache__",
             ".trash", ".DS_Store", "archive"}

IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)|!\[\[([^\]]+)\]\]")
WIKILINK = re.compile(r"\[\[([^\]|]+)")


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def scan(root: Path) -> dict:
    notes, docs, imgs, others = [], [], [], []
    by_dir: dict[str, int] = Counter()
    img_names: set[str] = set()
    referenced: set[str] = set()
    wikilinks = 0
    total_chars = 0

    for p in root.rglob("*"):
        if any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts[:-1]):
            continue
        if p.name.startswith("."):
            continue
        if p.is_dir():
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        rel = p.relative_to(root)
        ext = p.suffix.lower()
        top = rel.parts[0] if len(rel.parts) > 1 else "(根目录)"

        if ext in NOTE_EXT:
            notes.append((str(rel), size))
            by_dir[top] += 1
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                total_chars += len(text)
                wikilinks += len(WIKILINK.findall(text))
                for m in IMG_REF.finditer(text):
                    target = (m.group(1) or m.group(2) or "").split("|")[0].strip()
                    if target:
                        referenced.add(Path(target).name)
            except OSError:
                pass
        elif ext in DOC_EXT:
            docs.append((str(rel), size))
        elif ext in IMG_EXT:
            imgs.append((str(rel), size))
            img_names.add(p.name)
        else:
            others.append((str(rel), size))

    orphan_imgs = img_names - referenced
    orphan_size = sum(s for r, s in imgs if Path(r).name in orphan_imgs)

    # 已经是 LLM Wiki 结构了吗
    existing = {
        "AGENTS.md": (root / "AGENTS.md").is_file(),
        "index.md": (root / "index.md").is_file(),
        "log.md": (root / "log.md").is_file(),
        "wiki/": (root / "wiki").is_dir(),
        "raw/": (root / "raw").is_dir(),
        "archive/": (root / "archive").is_dir(),
    }

    return {
        "root": str(root),
        "notes": {"count": len(notes), "size": sum(s for _, s in notes),
                  "chars": total_chars,
                  "biggest": sorted(notes, key=lambda x: -x[1])[:50]},
        "docs": {"count": len(docs), "size": sum(s for _, s in docs),
                 "list": sorted(docs, key=lambda x: -x[1])[:50]},
        "images": {"count": len(imgs), "size": sum(s for _, s in imgs),
                   "orphan_count": len(orphan_imgs), "orphan_size": orphan_size},
        "others": {"count": len(others), "size": sum(s for _, s in others)},
        "by_domain": dict(by_dir.most_common()),
        "wikilinks": wikilinks,
        "existing_structure": existing,
    }


def report(d: dict, top: int) -> None:
    print(f"# 笔记体检报告\n")
    print(f"目录: {d['root']}\n")

    n, doc, img = d["notes"], d["docs"], d["images"]
    total = n["size"] + doc["size"] + img["size"] + d["others"]["size"]
    print("## 家底\n")
    print(f"  笔记(md/txt)  {n['count']:>5} 个   {human(n['size']):>8}   约 {n['chars']//1000}k 字")
    print(f"  文档(doc/pdf) {doc['count']:>5} 个   {human(doc['size']):>8}")
    print(f"  图片          {img['count']:>5} 个   {human(img['size']):>8}"
          f"   其中 {img['orphan_count']} 张未被引用({human(img['orphan_size'])})")
    print(f"  其他          {d['others']['count']:>5} 个   {human(d['others']['size']):>8}")
    print(f"  ─────────────────────────────")
    print(f"  合计                      {human(total):>8}")
    print(f"\n  现有双链(`[[...]]`): {d['wikilinks']} 处"
          + ("  ← 已有关联意识" if d["wikilinks"] > 10 else "  ← 基本是孤立笔记"))

    print(f"\n## 领域分布（按笔记数）\n")
    for k, v in list(d["by_domain"].items())[:top]:
        bar = "█" * min(int(v / max(d["by_domain"].values()) * 30), 30)
        print(f"  {k[:28]:<30} {bar} {v}")
    if len(d["by_domain"]) > top:
        print(f"  … 另有 {len(d['by_domain']) - top} 个目录")

    print(f"\n## 最大的笔记（图多或内容长，改造时优先关注）\n")
    for rel, size in n["biggest"][:top]:
        print(f"  {human(size):>8}  {rel}")

    if doc["count"]:
        print(f"\n## 非 md 文档（需要转换才能被 AI 读）\n")
        for rel, size in doc["list"][:top]:
            print(f"  {human(size):>8}  {rel}")
        print(f"\n  → 这些可用 kg-doc 转成 Markdown 后再沉淀")

    ex = d["existing_structure"]
    done = [k for k, v in ex.items() if v]
    print(f"\n## 已有的 LLM Wiki 结构\n")
    if done:
        for k, v in ex.items():
            print(f"  {'✅' if v else '⬜'} {k}")
    else:
        print("  （全新目录，什么都还没有）")

    print(f"\n---\n")
    print("## 改造建议\n")
    if all(ex[k] for k in ("AGENTS.md", "wiki/")):
        print("  已经是 LLM Wiki 结构了。若要补齐缺失项，见上方清单。")
    else:
        big = n["size"] + doc["size"] + img["size"]
        print(f"  建议走「整体归档 + 向前新建」：")
        print(f"    1. 现有 {n['count']} 个笔记 + {img['count']} 张图整体移进 `archive/`（原样封存，不逐篇整理）")
        print(f"    2. 新建 wiki/ raw/ assets/ 与 AGENTS.md / index.md / log.md")
        print(f"    3. 扫 archive 里的标题，生成 index.md 的唤醒条目")
        print(f"    4. 旧笔记按需 just-in-time 升级——**用到才蒸馏**，不批量")
        if img["orphan_count"] > 0:
            pct = img["orphan_count"] / max(img["count"], 1) * 100
            verdict = "占比小，不值得清理" if pct < 20 else "占比不小，可考虑清理"
            print(f"\n  未引用图片 {img['orphan_count']} 张({human(img['orphan_size'])}，{pct:.0f}%)"
                  f" —— {verdict}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="要分析的笔记目录")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--top", type=int, default=15, help="各清单显示条数")
    args = ap.parse_args()

    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        print(f"[错误] 目录不存在: {root}", file=sys.stderr)
        return 1

    d = scan(root)
    if args.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
    else:
        report(d, args.top)
    return 0


if __name__ == "__main__":
    sys.exit(main())
