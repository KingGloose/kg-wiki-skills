#!/usr/bin/env python3
"""按 .compress-map.tsv 改写 md/canvas 里的图片引用。

覆盖三种写法：
  Obsidian 内链   ![[path/to/img.png]]  含 |宽度 和 #anchor 后缀
  Markdown 图片   ![alt](path/to/img.png)  含 <>包裹、"title"、URL 编码
  HTML            <img src="path/to/img.png">

匹配策略：映射表按 basename 建索引。知识库里图片 basename 基本唯一（已校验
6958 张零冲突），而 md 里的引用路径写法五花八门（相对/绝对/仅文件名/URL编码），
只按 basename 匹配最稳。同名多份时按「与引用同目录优先」消歧。

用法:
  python3 scripts/fix-refs.py              # 就地改写
  python3 scripts/fix-refs.py --dry-run    # 只报告不落盘
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
from collections import defaultdict
from urllib.parse import quote, unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_FILE = os.path.join(REPO, '.compress-map.tsv')
TEXT_EXT = {'.md', '.canvas'}
SKIP_DIRS = {'.git', 'node_modules', '.trash', '.obsidian', '.venv'}


def nfc(s: str) -> str:
    """macOS 文件系统用 NFD，md 文本里常是 NFC，统一归一化再比。"""
    return unicodedata.normalize('NFC', s)


def load_map() -> dict[str, list[tuple[str, str]]]:
    """basename(小写) -> [(旧相对路径, 新相对路径)]"""
    if not os.path.exists(MAP_FILE):
        sys.exit(f'找不到映射表 {MAP_FILE}，先跑 scripts/compress-images.sh')
    by_base: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with open(MAP_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if not line or '\t' not in line:
                continue
            old, new = line.split('\t', 1)
            by_base[nfc(os.path.basename(old)).lower()].append((nfc(old), nfc(new)))
    return by_base


def resolve(ref_path: str, doc_dir: str, by_base) -> str | None:
    """给定引用路径，返回替换后的新路径（保持原写法风格），无需改则 None。"""
    decoded = nfc(unquote(ref_path))
    base = os.path.basename(decoded).lower()
    cands = by_base.get(base)
    if not cands:
        return None

    if len(cands) == 1:
        old, new = cands[0]
    else:
        # 同名多份：优先选和引用路径尾部最匹配的那个
        doc_rel = os.path.relpath(doc_dir, REPO)
        best, best_score = None, -1
        for old, new in cands:
            score = 0
            if nfc(decoded).lstrip('./') and old.endswith(nfc(decoded).lstrip('./')):
                score += 10
            if os.path.dirname(old) == doc_rel:
                score += 5
            if score > best_score:
                best, best_score = (old, new), score
        old, new = best  # type: ignore[misc]

    old_base = os.path.basename(old)
    new_base = os.path.basename(new)
    if old_base == new_base:
        return None

    # 只换最后那一段文件名，前面的路径写法（相对/绝对/编码）原样保留
    idx = ref_path.rfind(quote(old_base))
    if idx != -1:
        return ref_path[:idx] + quote(new_base) + ref_path[idx + len(quote(old_base)):]
    idx = ref_path.rfind(old_base)
    if idx != -1:
        return ref_path[:idx] + new_base + ref_path[idx + len(old_base):]
    # 编码形式不一致时的兜底：整体重写
    prefix = os.path.dirname(ref_path)
    return f'{prefix}/{new_base}' if prefix else new_base


WIKI_RE = re.compile(r'(!\[\[)([^\]\|#]+)([^\]]*)(\]\])')
# <> 包裹形式得单独一条：这种写法就是为了容纳带空格的路径，
# 不能用 [^)>\s]+ 去匹（空格会断）。
MD_ANGLE_RE = re.compile(r'(!\[[^\]]*\]\(\s*<)([^>]+)(>\s*(?:"[^"]*"|\'[^\']*\')?\s*\))')
MD_RE = re.compile(r'(!\[[^\]]*\]\(\s*)([^)<>\s]+)(\s*(?:"[^"]*"|\'[^\']*\')?\s*\))')
IMG_RE = re.compile(r'(<img[^>]*?\ssrc\s*=\s*["\'])([^"\']+)(["\'])', re.I)


def process(path: str, by_base, dry: bool) -> int:
    try:
        with open(path, encoding='utf-8') as f:
            text = original = f.read()
    except (UnicodeDecodeError, OSError):
        return 0

    doc_dir = os.path.dirname(path)
    count = 0

    def make_sub(group_idx: int):
        def sub(m: re.Match) -> str:
            nonlocal count
            groups = list(m.groups())
            ref = groups[group_idx]
            if re.match(r'^[a-z]+://', ref, re.I):
                return m.group(0)
            new = resolve(ref, doc_dir, by_base)
            if new is None or new == ref:
                return m.group(0)
            count += 1
            groups[group_idx] = new
            return ''.join(groups)
        return sub

    text = WIKI_RE.sub(make_sub(1), text)
    text = MD_ANGLE_RE.sub(make_sub(1), text)
    text = MD_RE.sub(make_sub(1), text)
    text = IMG_RE.sub(make_sub(1), text)

    if text != original and not dry:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return count


def main() -> None:
    dry = '--dry-run' in sys.argv
    by_base = load_map()
    print(f'映射表 {sum(len(v) for v in by_base.values())} 条')

    total_refs = total_files = 0
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if os.path.splitext(name)[1].lower() not in TEXT_EXT:
                continue
            p = os.path.join(root, name)
            n = process(p, by_base, dry)
            if n:
                total_refs += n
                total_files += 1
                print(f'  {n:4d}  {os.path.relpath(p, REPO)}')

    print(f'\n{"[dry-run] " if dry else ""}改写 {total_refs} 处引用，涉及 {total_files} 个文件')


if __name__ == '__main__':
    main()
