#!/usr/bin/env python3
"""把现有笔记目录归一化成 LLM Wiki 结构。

**两段式设计（这是本脚本最重要的约束）：**
  1. `plan`   —— 只输出改造计划，说明每一步做什么、为什么。**不动任何文件。**
  2. `apply`  —— 执行。必须带 --confirm，否则拒绝运行。

用法:
  python migrate.py plan <笔记目录>                    # 看计划（默认，安全）
  python migrate.py apply <笔记目录> --confirm         # 执行改造
  python migrate.py apply <目录> --confirm --dry-run   # 演练，只打印不落地
  python migrate.py rollback <目录>                    # 看如何回滚

改造策略「整体归档 + 向前新建」：
  旧笔记**原样移进 archive/**，不逐篇整理、不改内容；
  新建三层结构；旧知识靠 index 唤醒，按需 just-in-time 升级。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 模板是本 skill 的自带资源 —— 建结构是 kg-init 的职责
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
NEW_DIRS = ("wiki", "raw", "assets")
NEW_FILES = ("AGENTS.md", "index.md", "log.md")
ARCHIVE = "archive"
# 这些不该被归档（工具/配置/版本控制）
KEEP_AT_ROOT = {".git", ".gitignore", ".obsidian", ".trash", ".DS_Store",
                "node_modules", ".venv", "__pycache__", ".vscode", ".idea"}


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def dir_size(p: Path) -> int:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def survey(root: Path) -> dict:
    """看清现状：哪些要归档、哪些已存在、哪些保持不动。"""
    to_archive, keep, already = [], [], []
    for item in sorted(root.iterdir()):
        name = item.name
        if name in KEEP_AT_ROOT or name.startswith("."):
            keep.append(name)
        elif name == ARCHIVE:
            already.append(name)
        elif name in NEW_DIRS or name in NEW_FILES:
            already.append(name)
        else:
            size = dir_size(item) if item.is_dir() else item.stat().st_size
            n_files = sum(1 for _ in item.rglob("*") if _.is_file()) if item.is_dir() else 1
            to_archive.append({"name": name, "is_dir": item.is_dir(),
                               "size": size, "files": n_files})
    missing_dirs = [d for d in NEW_DIRS if not (root / d).is_dir()]
    missing_files = [f for f in NEW_FILES if not (root / f).is_file()]
    return {
        "root": str(root),
        "to_archive": to_archive,
        "keep_at_root": keep,
        "already_llm_wiki": already,
        "missing_dirs": missing_dirs,
        "missing_files": missing_files,
    }


def cmd_plan(args) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        eprint(f"[错误] 目录不存在: {root}")
        return 1
    s = survey(root)

    print(f"# 改造计划：{root.name}\n")
    print(f"目录: {root}\n")
    print("> **本命令只看不动。** 确认后用 `apply <目录> --confirm` 执行。\n")

    # ---- 为什么这么改 ----
    print("## 为什么这么改造\n")
    print("目标是把笔记变成 **LLM Wiki**：AI 时代笔记的价值不在\"存了多少\"，")
    print("而在两件事——**唤醒**(知道某知识点存在，能判断 AI 答得对不对) +")
    print("**沉淀**(只存 AI 给不出的：个人判断、项目上下文、踩过的坑)。\n")
    print("因此采用「**整体归档 + 向前新建**」，而不是逐篇重写：\n")
    print("  · 旧笔记**原样封存**进 `archive/`，一个字不改 —— 历史资产不该被破坏，")
    print("    而且逐篇整理几百个文件不现实，多半半途而废")
    print("  · 新知识写进 `wiki/`，从零开始按新规矩来")
    print("  · 旧知识靠 `index.md` **唤醒**：知道 archive 里有什么，需要时再翻")
    print("  · 真正用到某篇旧笔记时才**按需蒸馏**成 wiki 页(just-in-time)，不批量\n")

    # ---- 具体动作 ----
    total_size = sum(i["size"] for i in s["to_archive"])
    total_files = sum(i["files"] for i in s["to_archive"])
    print("## 会做什么\n")

    step = 1
    if s["to_archive"]:
        print(f"**{step}. 移动现有内容到 `archive/`**（{len(s['to_archive'])} 项，"
              f"{total_files} 个文件，{human(total_size)}）\n")
        for i in s["to_archive"][:20]:
            kind = "目录" if i["is_dir"] else "文件"
            print(f"     {i['name']}/" if i["is_dir"] else f"     {i['name']}", end="")
            print(f"    ({kind}, {i['files']} 文件, {human(i['size'])})")
        if len(s["to_archive"]) > 20:
            print(f"     … 另有 {len(s['to_archive']) - 20} 项")
        print(f"\n     **用 `git mv`/`mv` 移动，内容不做任何修改。**")
        step += 1
    else:
        print("**（无需归档：根目录下没有待整理的内容）**\n")

    if s["missing_dirs"]:
        print(f"\n**{step}. 新建目录**：{', '.join(d + '/' for d in s['missing_dirs'])}\n")
        print("     · `wiki/`   —— AI 沉淀的知识，按领域分子目录")
        print("     · `raw/`    —— 原始资料留档(转写稿、文章原文)，只读")
        print("     · `assets/` —— 新库图片池，与旧图隔离")
        step += 1

    if s["missing_files"]:
        print(f"\n**{step}. 新建根文件**（从 `templates/` 复制）：{', '.join(s['missing_files'])}\n")
        print("     · `AGENTS.md` —— **维护契约，最重要**。AI 每次开工必读，")
        print("       所有 kg-* skill 都依赖它。改造后你要按自己习惯改它")
        print("     · `index.md`  —— 知识点唤醒索引")
        print("     · `log.md`    —— 流水账，记录每次摄入/沉淀")
        step += 1

    print(f"\n**{step}. 生成 index.md 的唤醒条目**（改造后由 AI 完成）\n")
    print("     用 `extract_topics.py` 扫 archive 里的标题 → 草稿 →")
    print("     AI 归并同类、删噪声 → 写进 `index.md`。")
    print("     **这一步不自动做**，因为需要判断哪些值得唤醒。")

    # ---- 不会做什么 ----
    print(f"\n## 不会做什么（重要）\n")
    print("  ✗ 不修改任何笔记内容 —— 归档是移动，不是转换")
    print("  ✗ 不删除任何文件")
    print("  ✗ 不动 `.git` / `.obsidian` 等工具目录"
          + (f"（检测到：{', '.join(s['keep_at_root'][:5])}）" if s["keep_at_root"] else ""))
    print("  ✗ 不批量蒸馏旧笔记 —— 那是按需做的事")

    if s["already_llm_wiki"]:
        print(f"\n## 已存在（不会覆盖）\n")
        for n in s["already_llm_wiki"]:
            print(f"  ✅ {n}")

    # ---- 风险与回滚 ----
    print(f"\n## 风险与回滚\n")
    is_git = (root / ".git").is_dir()
    if is_git:
        print("  · 这是 git 仓库 → **改造前先提交当前状态**，出问题可 `git reset --hard`")
        print("  · 归档会用 `git mv` 保留历史")
    else:
        print("  · **不是 git 仓库** → 强烈建议先手动备份整个目录：")
        print(f"    `cp -a \"{root}\" \"{root}.backup\"`")
    print("  · 归档是移动而非复制，磁盘占用不变")
    print(f"  · 回滚方式见 `migrate.py rollback \"{root}\"`")

    print(f"\n---\n")
    print("## 确认后执行\n")
    print(f"```bash")
    print(f"python migrate.py apply \"{root}\" --confirm")
    print(f"python migrate.py apply \"{root}\" --confirm --dry-run   # 先演练看动作")
    print(f"```")
    print(f"\n**给 AI 的提示**：把上面的计划讲给用户，特别是「为什么这么改」和")
    print(f"「不会做什么」，**等用户明确同意后**再执行 apply。不要自作主张。")
    return 0


def cmd_apply(args) -> int:
    root = Path(args.path).expanduser().resolve()
    if not root.is_dir():
        eprint(f"[错误] 目录不存在: {root}")
        return 1
    if not args.confirm:
        eprint("[错误] 拒绝执行：必须带 --confirm。")
        eprint(f"       先看计划：python migrate.py plan \"{root}\"")
        return 1
    if not TEMPLATES.is_dir():
        eprint(f"[错误] 找不到模板目录 {TEMPLATES}")
        eprint("       检查仓库是否完整（应有 kg-init/templates/）")
        return 1

    s = survey(root)
    dry = args.dry_run
    tag = "[演练] " if dry else ""

    def do(desc: str, fn):
        print(f"{tag}{desc}")
        if not dry:
            fn()

    # 1. 归档
    if s["to_archive"]:
        arc = root / ARCHIVE
        do(f"创建 {ARCHIVE}/", lambda: arc.mkdir(exist_ok=True))
        for i in s["to_archive"]:
            src = root / i["name"]
            dst = arc / i["name"]
            if dst.exists():
                eprint(f"[跳过] {ARCHIVE}/{i['name']} 已存在")
                continue
            do(f"移动 {i['name']} → {ARCHIVE}/", lambda s=src, d=dst: shutil.move(str(s), str(d)))

    # 2. 新目录
    for d in s["missing_dirs"]:
        do(f"新建目录 {d}/", lambda p=root / d: p.mkdir(parents=True, exist_ok=True))

    # 3. 新文件（从模板）
    for f in s["missing_files"]:
        src = TEMPLATES / f
        if not src.is_file():
            eprint(f"[跳过] 模板里没有 {f}")
            continue
        do(f"复制模板 {f}", lambda s=src, d=root / f: shutil.copy2(s, d))

    # 4. log 记一条
    if not dry:
        log = root / "log.md"
        if log.is_file():
            entry = (f"\n## [{datetime.now().strftime('%Y-%m-%d')}] setup | LLM Wiki 改造初始化\n\n"
                     f"- 由 kg-init 执行「整体归档 + 向前新建」。\n"
                     f"- 归档 {len(s['to_archive'])} 项"
                     f"（{sum(i['files'] for i in s['to_archive'])} 个文件，"
                     f"{human(sum(i['size'] for i in s['to_archive']))}）到 `archive/`，内容未修改。\n"
                     f"- 新建 {', '.join(s['missing_dirs']) or '(无)'} 目录与 "
                     f"{', '.join(s['missing_files']) or '(无)'}。\n"
                     f"- 待办：① 按自己习惯改 AGENTS.md ② 用 extract_topics.py 生成 index 唤醒条目\n")
            log.write_text(log.read_text(encoding="utf-8") + entry, encoding="utf-8")
            print(f"{tag}在 log.md 记录本次改造")

    print(f"\n{'演练结束（未改动任何文件）' if dry else '✅ 改造完成'}\n")
    if not dry:
        print("下一步（都需要你和 AI 一起做，脚本不自动做）：")
        print(f"  1. **改 AGENTS.md** —— 按自己习惯调整「写作约定」和「领域划分」")
        print(f"  2. **生成 index 唤醒条目**：")
        print(f"     python extract_topics.py \"{root / ARCHIVE}\"")
        print(f"     → 交给 AI 归并精简 → 写进 index.md")
        print(f"  3. **注册知识库**（让其他 skill 能找到）：")
        print(f"     python ../kg-vault/scripts/vault_cli.py add \"{root}\"")
        print(f"  4. Obsidian 用户：图谱视图建议过滤 `-path:archive` 隐藏旧笔记")
    return 0


def cmd_rollback(args) -> int:
    root = Path(args.path).expanduser().resolve()
    arc = root / ARCHIVE
    print(f"# 如何回滚 {root.name} 的改造\n")
    if (root / ".git").is_dir():
        print("这是 git 仓库，最简单：\n")
        print("```bash")
        print(f"cd \"{root}\"")
        print("git status                    # 先看改动")
        print("git reset --hard HEAD         # 丢弃未提交的改动")
        print("# 若已提交：git revert <commit> 或 git reset --hard <改造前的commit>")
        print("```")
    else:
        print("不是 git 仓库，手动回滚：\n")
        print("```bash")
        print(f"cd \"{root}\"")
        if arc.is_dir():
            print(f"mv {ARCHIVE}/* .              # 把归档内容移回根目录")
            print(f"rmdir {ARCHIVE}")
        print(f"# 删掉新建的（确认里面没有你写的新内容再删！）")
        print(f"rm -rf wiki raw assets AGENTS.md index.md log.md")
        print("```")
        print(f"\n**警告**：如果改造后已经在 `wiki/` 写过内容，删除会丢失。先检查。")
    print(f"\n有备份的话直接用备份最稳：`rm -rf \"{root}\" && mv \"{root}.backup\" \"{root}\"`")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="把现有笔记归一化成 LLM Wiki 结构")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="输出改造计划（只看不动，默认用这个）")
    p_plan.add_argument("path")

    p_apply = sub.add_parser("apply", help="执行改造（需 --confirm）")
    p_apply.add_argument("path")
    p_apply.add_argument("--confirm", action="store_true", help="确认执行")
    p_apply.add_argument("--dry-run", action="store_true", help="演练，只打印不落地")

    p_rb = sub.add_parser("rollback", help="显示回滚方法")
    p_rb.add_argument("path")

    args = ap.parse_args()
    return {"plan": cmd_plan, "apply": cmd_apply, "rollback": cmd_rollback}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
