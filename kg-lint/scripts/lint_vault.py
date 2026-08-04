#!/usr/bin/env python3
"""学习笔记库健康检查：找出知识网的断点与账目不一致。

用法:
  python lint_vault.py              # 全部检查，人类可读报告
  python lint_vault.py --json       # 结构化输出
  python lint_vault.py --only orphan,deadlink   # 只跑指定检查

检查项:
  deadlink   死链：[[xxx]] 指向不存在的页/文件
  orphan     孤儿页：没有任何其他 wiki 页链接到它（知识网断点）
  rawlink    raw 原文未被任何 wiki 页引用（存了但没用上）
  indexsync  wiki 有页但 index.md 没提到对应领域/关键词
  logsync    wiki 页没在 log.md 里留下痕迹（无摄入记录）
  empty      内容过短的页（可能是没写完的坑）
  image      图片体积：孤儿图、图片死链、超大图、未压缩图

退出码：0 = 无问题；1 = 有发现（供 CI/脚本判断）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote

from media_to_text import find_vault, VaultNotFoundError


VAULT = None  # 在 main() 里按 --vault 解析
WIKI = None  # 随 VAULT 在 main() 里初始化
RAW = None  # 随 VAULT 在 main() 里初始化
INDEX = None  # 随 VAULT 在 main() 里初始化
LOG = None  # 随 VAULT 在 main() 里初始化

LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
# 代码块（围栏与行内）里的 [[xxx]] 是**示例而非真双链**。
# 写“怎么写 Obsidian 引用”这类页时不剔掉会报一堆假死链。
FENCE_RE = re.compile(r"^(?P<fence>```+|~~~+).*?^(?P=fence)", re.S | re.M)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
MIN_CHARS = 400  # 低于此字符数视为“可能没写完”

# ---- 图片体检用 ----
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif"}
DOC_EXT = {".md", ".canvas"}
IMG_SKIP_DIRS = {".git", "node_modules", ".trash", ".obsidian", ".venv", "__pycache__"}
BIG_IMAGE_KB = 500  # 单张超过此值算“超大图”
# 未压缩判定：非 webp 且超过这个体积。小图转 webp 常反而变大，不该报。
UNCOMPRESSED_MIN_KB = 100
# 图片引用的三种写法：Obsidian 内链 / Markdown / HTML
IMG_REF_RES = [
    re.compile(r"!\[\[([^\]\|#]+)"),
    re.compile(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)"),
    re.compile(r'<img[^>]*?\ssrc\s*=\s*["\']([^"\']+)["\']', re.I),
]


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def _human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def strip_code(text: str) -> str:
    """把代码块/行内代码抿成空白，保留换行以不错位。

    为什么不直接删：删了会让后续行号与原文对不上，不好报位置。
    """
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return INLINE_CODE_RE.sub(blank, FENCE_RE.sub(blank, text))


def wiki_pages() -> list[Path]:
    return sorted(WIKI.rglob("*.md")) if WIKI.is_dir() else []


def page_key(p: Path) -> str:
    """页的规范标识：领域/页名（不含 .md）。"""
    return str(p.relative_to(WIKI).with_suffix(""))


def resolve_link(target: str, from_page: Path) -> Path | None:
    """把双链目标解析成实际文件路径。支持三种写法：
    1. 纯页名          [[同源策略与 CORS]]        → 在 wiki 下按文件名找
    2. 相对路径        [[../网络/同源策略与 CORS]] → 相对 from_page 所在目录
    3. 指向 raw 等     [[../../raw/xxx.md]]
    找不到返回 None。
    """
    t = target.strip()
    # 剥掉块锚点：[[页名#小节标题]] 只取页名部分
    if "#" in t:
        t = t.split("#", 1)[0].strip()
        if not t:
            return from_page  # [[#本页小节]] 指向自己，视为有效
    base = from_page.parent

    cands: list[Path] = []
    if "/" in t:
        # 相对路径写法
        cands.append((base / t))
        cands.append((base / t).with_suffix(".md"))
        cands.append(VAULT / t)
        cands.append((VAULT / t).with_suffix(".md"))
    else:
        # 纯页名：全 wiki 搜同名文件
        for p in wiki_pages():
            if p.stem == t:
                return p
        cands.append((base / t).with_suffix(".md"))

    for c in cands:
        try:
            if c.exists() and c.is_file():
                return c.resolve()
        except OSError:
            continue
    return None


def collect_links() -> tuple[dict[str, list[tuple[str, str]]], list[dict]]:
    """扫所有 wiki 页的双链。

    返回 (被链接映射, 死链列表)
      被链接映射: {被指向页的 page_key: [(来源页, 原始链接文本)]}
    """
    inbound: dict[str, list[tuple[str, str]]] = {}
    dead: list[dict] = []
    for p in wiki_pages():
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            dead.append({"page": page_key(p), "link": "(读取失败)", "reason": str(e)})
            continue
        for m in LINK_RE.finditer(strip_code(text)):
            target = m.group(1)
            resolved = resolve_link(target, p)
            if resolved is None:
                dead.append({"page": page_key(p), "link": target})
            else:
                try:
                    if WIKI in resolved.parents:
                        k = page_key(resolved)
                        inbound.setdefault(k, []).append((page_key(p), target))
                except Exception:
                    pass
    return inbound, dead


def check_orphan(inbound) -> list[dict]:
    out = []
    for p in wiki_pages():
        k = page_key(p)
        if not inbound.get(k):
            out.append({"page": k})
    return out


def check_rawlink() -> list[dict]:
    """raw 文件是否被任何 wiki 页引用（双链或纯文本提到文件名）。"""
    if not RAW.is_dir():
        return []
    all_wiki_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in wiki_pages()
    )
    log_text = LOG.read_text(encoding="utf-8", errors="ignore") if LOG.is_file() else ""
    out = []
    for f in sorted(RAW.glob("*.md")):
        name = f.stem
        if name in all_wiki_text or f.name in all_wiki_text:
            continue
        out.append({"raw": f.name, "in_log": name in log_text or f.name in log_text})
    return out


def _mentioned(stem: str, haystack: str, haystack_low: str) -> bool:
    """判断页名是否在某文本里被“提到过”。

    三级匹配，从严到宽：
    1. 页名全称
    2. 按分隔符拆词（对含空白/标点的页名有效）
    3. 中文子串滑窗（中文页名往往无空白，如「泛域名与相关概念辨析」，
       index 里只写「泛域名」，故取长度>=3 的连续子串去碰）
    """
    if stem in haystack:
        return True

    tokens = [t for t in re.split(r"[\s\u3000/\-—·:：、（）()\[\]]+", stem) if len(t) >= 2]
    if any(t.lower() in haystack_low for t in tokens):
        return True

    # 中文子串滑窗：只对纯中文段做，避免英文短词误匹配
    for seg in re.findall(r"[\u4e00-\u9fff]{3,}", stem):
        for size in range(len(seg), 2, -1):
            for i in range(len(seg) - size + 1):
                if seg[i:i + size] in haystack:
                    return True
    return False


def check_indexsync() -> list[dict]:
    """wiki 页是否在 index.md 里有唤醒条目。

    index 的写法是“关键词”而非页名全称（页名「QuillJs 换行与 embed 光标问题」，
    index 里只写「QuillJs」），所以用宽松的 _mentioned 判定，宁可漏报不要误报。
    """
    if not INDEX.is_file():
        return [{"issue": "index.md 不存在"}]
    idx = INDEX.read_text(encoding="utf-8", errors="ignore")
    idx_low = idx.lower()
    out = []

    domains = {p.relative_to(WIKI).parts[0] for p in wiki_pages()
               if len(p.relative_to(WIKI).parts) > 1}
    for d in sorted(domains):
        if f"wiki/{d}" not in idx and d not in idx:
            out.append({"domain": d, "issue": "index.md 未提及该领域"})

    for p in wiki_pages():
        if not _mentioned(p.stem, idx, idx_low):
            out.append({"page": page_key(p), "issue": "index.md 里找不到相关关键词"})
    return out


def check_logsync() -> list[dict]:
    if not LOG.is_file():
        return [{"issue": "log.md 不存在"}]
    log = LOG.read_text(encoding="utf-8", errors="ignore")
    log_low = log.lower()
    return [{"page": page_key(p)} for p in wiki_pages()
            if not _mentioned(p.stem, log, log_low)]


def check_empty() -> list[dict]:
    out = []
    for p in wiki_pages():
        try:
            n = len(p.read_text(encoding="utf-8", errors="ignore").strip())
        except OSError:
            continue
        if n < MIN_CHARS:
            out.append({"page": page_key(p), "chars": n})
    return out


def _nfc(s: str) -> str:
    """macOS 文件系统用 NFD，md 正文里常是 NFC，比较前先归一。"""
    return unicodedata.normalize("NFC", s)


def _walk_files(exts: set[str]):
    """遍历全库（**含 archive**）指定后缀的文件。

    注意：其他检查项按 AGENTS.md 不看 archive，但体积问题必须看——
    旧库图片就是膨胀的主体（实测某库 958 MB 图片里 906 MB 在 archive）。
    """
    for p in VAULT.rglob("*"):
        if p.is_dir():
            continue
        if any(part in IMG_SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() in exts:
            yield p


def check_image() -> list[dict]:
    """图片体积体检。

    为什么需要这项：知识库最大的膨胀源是 Obsidian 粘贴截图直落原始 PNG。
    早期六项检查全是文字层面的，结果某真实库悄悄涨到 2.6 GB（.git 1.6 GB）
    都没人报警，clone 一次要十几分钟。

    四个子项：
      orphan_image  磁盘上有、但没任何 md/canvas 引用
      dead_image    md 引用了、但磁盘上找不到
      big_image     单张超阈值
      uncompressed  非 WebP 且超 100KB（小图转 WebP 反而变大，不报）
      dup_image     内容完全相同
    """
    images = list(_walk_files(IMG_EXT))
    if not images:
        return []

    # basename 建索引：md 里的引用路径写法五花八门（相对/绝对/仅文件名/URL编码），
    # 而图片 basename 基本唯一，按 basename 匹最稳。
    on_disk: dict[str, Path] = {}
    for p in images:
        on_disk.setdefault(_nfc(p.name).lower(), p)

    referenced: set[str] = set()
    dead: list[dict] = []
    for doc in _walk_files(DOC_EXT):
        try:
            text = doc.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # 同样要剔代码块：写图片引用示例的页不应报假死链
        text = strip_code(text)
        for pat in IMG_REF_RES:
            for ref in pat.findall(text):
                if re.match(r"^[a-z]+://", ref, re.I):
                    continue
                clean = _nfc(unquote(ref.split("|")[0].split("#")[0])).strip()
                name = Path(clean).name.lower()
                if not name or Path(name).suffix not in IMG_EXT:
                    continue
                if name in on_disk:
                    referenced.add(name)
                else:
                    dead.append({
                        "kind": "dead_image",
                        "page": str(doc.relative_to(VAULT)),
                        "ref": ref,
                    })

    out: list[dict] = []

    for name, p in sorted(on_disk.items()):
        if name not in referenced:
            out.append({
                "kind": "orphan_image",
                "image": str(p.relative_to(VAULT)),
                "bytes": p.stat().st_size,
            })

    out.extend(dead)

    for p in images:
        size = p.stat().st_size
        if size > BIG_IMAGE_KB * 1024:
            out.append({
                "kind": "big_image",
                "image": str(p.relative_to(VAULT)),
                "bytes": size,
            })
        elif p.suffix.lower() not in (".webp", ".svg") and size > UNCOMPRESSED_MIN_KB * 1024:
            out.append({
                "kind": "uncompressed",
                "image": str(p.relative_to(VAULT)),
                "bytes": size,
            })

    by_hash: dict[str, list[Path]] = defaultdict(list)
    for p in images:
        try:
            by_hash[hashlib.md5(p.read_bytes()).hexdigest()].append(p)
        except OSError:
            continue
    for group in by_hash.values():
        if len(group) > 1:
            out.append({
                "kind": "dup_image",
                "image": str(group[0].relative_to(VAULT)),
                "copies": len(group),
                "bytes": group[0].stat().st_size * (len(group) - 1),
            })

    return out


CHECKS = ("deadlink", "orphan", "rawlink", "indexsync", "logsync", "empty", "image")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="结构化输出")
    ap.add_argument("--only", default=None,
                    help=f"只跑指定检查，逗号分隔。可选: {','.join(CHECKS)}")
    ap.add_argument("--vault", default=None,
                    help="知识库路径（默认自动解析：KG_VAULT / 配置文件 / 向上查找）")
    args = ap.parse_args()

    global VAULT, WIKI, RAW, INDEX, LOG
    try:
        VAULT = find_vault(__file__, explicit=args.vault)
    except VaultNotFoundError as exc:
        eprint(f"[错误] {exc}")
        return 2
    WIKI = VAULT / "wiki"
    RAW = VAULT / "raw"
    INDEX = VAULT / "index.md"
    LOG = VAULT / "log.md"

    if not WIKI.is_dir():
        eprint(f"[错误] 找不到 wiki 目录: {WIKI}")
        return 2

    todo = CHECKS
    if args.only:
        todo = tuple(x.strip() for x in args.only.split(",") if x.strip() in CHECKS)
        if not todo:
            eprint(f"[错误] --only 无有效检查项。可选: {','.join(CHECKS)}")
            return 2

    inbound, dead = collect_links()
    result: dict[str, list] = {}
    if "deadlink" in todo:
        result["deadlink"] = dead
    if "orphan" in todo:
        result["orphan"] = check_orphan(inbound)
    if "rawlink" in todo:
        result["rawlink"] = check_rawlink()
    if "indexsync" in todo:
        result["indexsync"] = check_indexsync()
    if "logsync" in todo:
        result["logsync"] = check_logsync()
    if "empty" in todo:
        result["empty"] = check_empty()
    if "image" in todo:
        result["image"] = check_image()

    total = sum(len(v) for v in result.values())

    if args.json:
        print(json.dumps({
            "vault": str(VAULT),
            "wiki_pages": len(wiki_pages()),
            "total_findings": total,
            "findings": result,
        }, ensure_ascii=False, indent=2))
        return 1 if total else 0

    # 人类可读报告
    print(f"# 库健康检查 · {VAULT.name}")
    print(f"\nwiki 页数: {len(wiki_pages())}  |  发现问题: {total}\n")

    titles = {
        "deadlink": ("死链（指向不存在的页/文件）", "修：改正链接目标，或补上缺失的页"),
        "orphan": ("孤儿页（没有其他页链接到它）", "修：从相关页建双链，让它接入知识网"),
        "rawlink": ("raw 原文未被 wiki 引用", "修：若有价值则蒸馏成 wiki 页；否则确认它只是留档"),
        "indexsync": ("index.md 唤醒条目缺失", "修：在 index 对应领域补关键词（唤醒是 index 的职责）"),
        "logsync": ("log.md 无摄入记录", "修：补一条 log，或确认是早期页无需追记"),
        "empty": (f"内容过短（<{MIN_CHARS} 字符，可能没写完）", "修：补完或删除占位页"),
        "image": ("图片体积问题", "修：压缩或删除（见下方按类型分组）"),
    }

    img_labels = {
        "orphan_image": "孤儿图（无人引用）",
        "dead_image": "图片死链（引用了不存在的图）",
        "big_image": f"超大图（>{BIG_IMAGE_KB}KB）",
        "uncompressed": f"未压缩（非 WebP 且 >{UNCOMPRESSED_MIN_KB}KB）",
        "dup_image": "重复图（内容相同）",
    }

    for k in todo:
        items = result.get(k, [])
        title, hint = titles[k]
        mark = "✅" if not items else "⚠️"
        print(f"## {mark} {title} — {len(items)}")
        if items and k == "image":
            # image 项按子类型分组，并给出可回收的体积（体积才是这项的重点）
            grouped: dict[str, list[dict]] = defaultdict(list)
            for it in items:
                grouped[it["kind"]].append(it)
            for kind in ("orphan_image", "dead_image", "big_image",
                         "uncompressed", "dup_image"):
                sub = grouped.get(kind)
                if not sub:
                    continue
                total_bytes = sum(x.get("bytes", 0) for x in sub)
                size_note = f"，{_human(total_bytes)}" if total_bytes else ""
                print(f"   [{img_labels[kind]}] {len(sub)} 项{size_note}")
                for it in sorted(sub, key=lambda x: -x.get("bytes", 0))[:8]:
                    if kind == "dead_image":
                        print(f"     · {it['page']}  →  {it['ref']}")
                    elif kind == "dup_image":
                        print(f"     · {it['image']}  ({it['copies']} 份)")
                    else:
                        print(f"     · {_human(it['bytes']):>9}  {it['image']}")
                if len(sub) > 8:
                    print(f"     … 另有 {len(sub) - 8} 项")
            print(f"   建议：{hint}")
            print("   压缩：库内 scripts/compress-images.sh，"
                  "或代码调 from media_to_text import compress_dir")
        elif items:
            print(f"   建议：{hint}")
            for it in items[:30]:
                if k == "deadlink":
                    print(f"   · {it['page']}  →  [[{it['link']}]]")
                elif k == "rawlink":
                    tag = "（log 里有记录）" if it.get("in_log") else "（log 里也没记）"
                    print(f"   · {it['raw']} {tag}")
                elif k == "empty":
                    print(f"   · {it['page']}  ({it['chars']} 字符)")
                else:
                    print(f"   · {it.get('page') or it.get('domain') or it}"
                          + (f"  — {it['issue']}" if it.get("issue") else ""))
            if len(items) > 30:
                print(f"   … 另有 {len(items) - 30} 条")
        print()

    if total == 0:
        print("库很健康，没发现问题。")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
