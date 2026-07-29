#!/usr/bin/env python3
"""挑几页出来回顾——让沉淀过的知识被重新唤醒。

Karpathy LLM Wiki 模式的隐含前提:知识要被**反复唤醒**才有价值。
写完就存着 = 死档案。本脚本负责"挑哪几页",实际回顾靠 AI 和用户对话完成。

挑选策略(默认 stale,可组合):
  stale     最久没被回顾的优先(靠 .review-log.json 记录上次回顾时间)
  recent    最近沉淀的(巩固新知识)
  random    随机(打破惯性,可能翻出意外的老页)
  orphanish 双链最少的(知识网边缘,容易被遗忘)

用法:
  python pick_review.py                      # 默认挑 3 页(stale 策略)
  python pick_review.py --count 5
  python pick_review.py --strategy random
  python pick_review.py --strategy recent --domain AI     # 只看某领域
  python pick_review.py --mark "wiki/AI/xxx.md"           # 标记已回顾
  python pick_review.py --status                          # 看各页回顾情况
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------- 库根解析（内联，保持本脚本零依赖） ----------
def _looks_like_vault(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "AGENTS.md").is_file() and (p / "wiki").is_dir()
    except OSError:
        return False


def _walk_up(start: Path, limit: int = 8) -> Path | None:
    cur = start.resolve()
    for _ in range(limit):
        if _looks_like_vault(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def find_vault(explicit: str | None = None) -> Path:
    """定位知识库根。

    优先级：explicit(--vault) → KG_VAULT 环境变量 → 配置文件 → cwd 向上 → 本文件向上。
    """
    import os
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if _looks_like_vault(p):
            return p
        sys.exit(f"[错误] --vault 指向 {p}，但那里不像知识库（需 AGENTS.md + wiki/）")
    v = os.environ.get("KG_VAULT")
    if v:
        p = Path(v).expanduser().resolve()
        if _looks_like_vault(p):
            return p
        sys.exit(f"[错误] KG_VAULT 指向 {p}，但那里不像知识库（需 AGENTS.md + wiki/）")

    cfg = Path.home() / ".config" / "kg-wiki" / "config.json"
    if cfg.is_file():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            # 多库格式：{"default": "名字", "vaults": {"名字": "路径"}}
            vaults = data.get("vaults")
            if isinstance(vaults, dict) and vaults:
                name = data.get("default") or (next(iter(vaults)) if len(vaults) == 1 else None)
                if name is None:
                    sys.exit(
                        "[错误] 配置里有多个知识库但未指定默认：\n"
                        + "\n".join(f"  · {k}: {v}" for k, v in vaults.items())
                        + "\n\n【给 AI 的指示】问用户这次要写哪个库，然后："
                        "\n  临时：加 --vault <路径>"
                        "\n  长期：kg-vault/scripts/vault_cli.py use <别名>"
                    )
                v = vaults.get(name)
                if v:
                    p = Path(v).expanduser().resolve()
                    if _looks_like_vault(p):
                        return p
            # 单库格式（向后兼容）
            v = data.get("vault")
            if v:
                p = Path(v).expanduser().resolve()
                if _looks_like_vault(p):
                    return p
        except (json.JSONDecodeError, OSError):
            pass

    for start in (Path.cwd(), Path(__file__).parent):
        p = _walk_up(start)
        if p:
            return p

    sys.exit(
        "[错误] 找不到知识库 —— 不知道该读写哪里。\n"
        "\n【给 AI 的指示】不要猜路径，直接问用户「你的知识库在哪个目录？」\n"
        "拿到路径后任选一种方式：\n"
        "  1. 本次临时：  加 --vault /path/to/vault\n"
        f"  2. 长期配置：  写入 {cfg}\n"
        '                 内容 {"vault": "/path/to/vault"}\n'
        "  3. 环境变量：  export KG_VAULT=/path/to/vault\n"
        "\n知识库需包含 AGENTS.md 和 wiki/ 目录。没有的话用仓库 templates/ 新建。"
    )



VAULT = None  # 在 main() 里按 --vault 解析
WIKI = None  # 随 VAULT 在 main() 里初始化
REVIEW_LOG = Path(__file__).resolve().parent.parent / ".review-log.json"

STRATEGIES = ("stale", "recent", "random", "orphanish")


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def load_log() -> dict:
    if REVIEW_LOG.is_file():
        try:
            return json.loads(REVIEW_LOG.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"reviews": {}}


def save_log(log: dict) -> None:
    REVIEW_LOG.parent.mkdir(parents=True, exist_ok=True)
    REVIEW_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def pages(domain: str | None) -> list[Path]:
    if not WIKI.is_dir():
        return []
    out = sorted(WIKI.rglob("*.md"))
    if domain:
        out = [p for p in out if p.relative_to(WIKI).parts[0].lower() == domain.lower()]
    return out


def link_count(p: Path, all_text: str) -> int:
    """有多少其他页链接到它（衡量它在知识网里的中心度）。"""
    stem = p.stem
    return all_text.count(f"[[{stem}]]") + all_text.count(f"/{stem}]]")


def days_since(ts: float | None) -> float | None:
    if not ts:
        return None
    return (time.time() - ts) / 86400


# 标记「含个人判断」的信号词——回顾这类页时要问"现在还认同吗"
_JUDGMENT_MARKERS = (
    "⭐",                                    # 库约定的个人实践标记
    "我的判断", "我认为", "我倾向", "我原以为",
    "个人判断", "对照观察", "自己的判断", "我的看法",
    "踩坑", "教训", "现在回看",
)


def _has_own_judgment(text: str) -> bool:
    """粗判这页是否含作者自己的判断（而非纯转述）。

    不依赖特定称谓（原实现硬编码了"用户"，换个库就失效）。
    """
    return any(m in text for m in _JUDGMENT_MARKERS)


def summarize(p: Path) -> dict:
    """提取页面概要，供 AI 组织回顾问题。"""
    text = p.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    # 一句话主旨：找 "## x.1 一句话主旨" 或首个非标题非引用段
    gist = ""
    for i, l in enumerate(lines):
        if "一句话主旨" in l or "一句话" in l and l.startswith("#"):
            for nxt in lines[i + 1:i + 8]:
                s = nxt.strip()
                if s and not s.startswith(("#", ">", "-", "|")):
                    gist = s
                    break
            break
    if not gist:
        for l in lines[1:25]:
            s = l.strip()
            if s.startswith(">") and len(s) > 12:
                gist = s.lstrip("> ").strip()
                break
    # 小节标题作为"考点"
    heads = [re.sub(r"^#+\s*[\d.]*\s*", "", l).strip()
             for l in lines if re.match(r"^##\s", l)]
    return {
        "chars": len(text),
        "gist": gist[:200],
        "sections": heads[:12],
        "has_own_judgment": _has_own_judgment(text),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=3, help="挑几页（默认 3）")
    ap.add_argument("--strategy", default="stale", choices=STRATEGIES)
    ap.add_argument("--domain", default=None, help="限定领域，如 AI / 前端 / 网络")
    ap.add_argument("--mark", default=None, help="标记某页已回顾（传相对路径）")
    ap.add_argument("--status", action="store_true", help="显示所有页的回顾情况")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--vault", default=None,
                    help="知识库路径（默认自动解析：KG_VAULT / 配置文件 / 向上查找）")
    args = ap.parse_args()

    global VAULT, WIKI
    VAULT = find_vault(args.vault)
    WIKI = VAULT / "wiki"

    log = load_log()
    reviews: dict = log["reviews"]

    # 标记已回顾
    if args.mark:
        key = args.mark.replace("\\", "/")
        rec = reviews.setdefault(key, {"count": 0, "last": None})
        rec["count"] += 1
        rec["last"] = time.time()
        save_log(log)
        print(f"✅ 已标记回顾: {key}（累计 {rec['count']} 次）")
        return 0

    ps = pages(args.domain)
    if not ps:
        eprint(f"[错误] 没找到 wiki 页{'（领域: ' + args.domain + '）' if args.domain else ''}")
        return 1

    all_text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in ps)

    items = []
    for p in ps:
        rel = str(p.relative_to(VAULT))
        rec = reviews.get(rel, {})
        items.append({
            "path": rel,
            "title": p.stem,
            "domain": p.relative_to(WIKI).parts[0] if len(p.relative_to(WIKI).parts) > 1 else "",
            "mtime": p.stat().st_mtime,
            "review_count": rec.get("count", 0),
            "last_review": rec.get("last"),
            "inbound_links": link_count(p, all_text),
        })

    # 状态总览
    if args.status:
        print("# 回顾状态\n")
        items.sort(key=lambda x: (x["review_count"], -(x["mtime"])))
        for it in items:
            d = days_since(it["last_review"])
            last = f"{d:.0f} 天前" if d is not None else "从未回顾"
            print(f"  {it['review_count']:>2} 次 | {last:>10} | 链入 {it['inbound_links']:>2} | {it['path']}")
        never = sum(1 for i in items if i["review_count"] == 0)
        print(f"\n  共 {len(items)} 页，其中 {never} 页从未回顾")
        return 0

    # 挑选
    if args.strategy == "stale":
        # 从未回顾的优先，其次最久没回顾的
        items.sort(key=lambda x: (x["review_count"], x["last_review"] or 0))
    elif args.strategy == "recent":
        items.sort(key=lambda x: -x["mtime"])
    elif args.strategy == "orphanish":
        items.sort(key=lambda x: (x["inbound_links"], x["review_count"]))
    else:
        random.shuffle(items)

    picked = items[: args.count]
    for it in picked:
        it.update(summarize(VAULT / it["path"]))

    if args.json:
        print(json.dumps({"strategy": args.strategy, "picked": picked},
                         ensure_ascii=False, indent=2))
        return 0

    print(f"# 回顾 {len(picked)} 页（策略: {args.strategy}）\n")
    for i, it in enumerate(picked, 1):
        d = days_since(it["last_review"])
        last = f"{d:.0f} 天前回顾过" if d is not None else "**从未回顾**"
        print(f"## {i}. {it['title']}")
        print(f"   `{it['path']}` | {it['chars']} 字符 | 链入 {it['inbound_links']} | "
              f"回顾 {it['review_count']} 次 | {last}")
        if it["gist"]:
            print(f"   主旨: {it['gist']}")
        if it["sections"]:
            print(f"   小节: {' / '.join(it['sections'][:6])}")
        if it.get("has_own_judgment"):
            print(f"   ⭐ 含个人判断——回顾时重点确认这部分还认同吗")
        print()

    print("---")
    print("回顾方式（给 AI 的提示）:")
    print("  1. 先只看标题和主旨，问用户「还记得这页讲什么吗」——先回想再看答案，")
    print("     这才是唤醒（直接把内容念一遍等于没回顾）。")
    print("  2. 对含个人判断的页，问「现在还认同当时的判断吗」——知识会过时，判断会变。")
    print("  3. 回顾完用 --mark <路径> 记一笔。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
