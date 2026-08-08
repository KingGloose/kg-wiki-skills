#!/usr/bin/env python3
"""知识库注册与切换 —— 只解决"库在哪"这一个问题。

**不负责创建知识库**——建新库或改造旧笔记是 kg-init 的职责（它有模板）。
本 skill 只管：注册路径、切换默认、告诉别人当前用哪个。

所有其他 kg-* skill 都靠这里的配置定位知识库。配置在
`~/.kg-agent-config/config.json`。

用法:
  python vault_cli.py which                    # 当前会用哪个库（AI 拿不准时先跑这个）
  python vault_cli.py list                     # 列出已注册的库
  python vault_cli.py add <路径> [--name 别名]   # 注册已有的知识库
  python vault_cli.py use <别名>                # 切换默认库
  python vault_cli.py remove <别名>             # 移除注册（不删目录）
  python vault_cli.py doctor                   # 检查配置与各库健康

退出码：0 正常；1 出错；2 需要询问用户（多库无默认 / 未配置）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from media_to_text import (
    CONFIG_PATH,
    VaultNotFoundError,
    find_vault,
    load_vault_registry,
    looks_like_vault,
    save_vault_registry,
)
# 判断"是否知识库"用的标记（只读检查，不负责创建——创建归 kg-init）
VAULT_DIRS = ("wiki", "raw", "assets")
VAULT_FILES = ("AGENTS.md", "index.md", "log.md")

# 退出码语义
EXIT_OK = 0
EXIT_ERR = 1
EXIT_ASK_USER = 2


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def all_vaults() -> tuple[dict[str, str], str | None]:
    """返回 (别名→路径, 默认别名)。"""
    return load_vault_registry()


def cmd_which(args) -> int:
    try:
        print(find_vault(__file__))
        return EXIT_OK
    except VaultNotFoundError as exc:
        print(exc)
        return EXIT_ASK_USER


def cmd_list(args) -> int:
    vaults, default = all_vaults()
    if not vaults:
        print("未注册任何知识库。已有知识库用 `add` 注册；没有知识库先用 kg-init 创建。")
        return EXIT_OK
    print(f"# 已注册的知识库（配置：{CONFIG_PATH}）\n")
    for k, v in vaults.items():
        p = Path(v)
        ok = looks_like_vault(p)
        mark = "★" if k == default else " "
        status = "" if ok else "  ← 路径无效"
        extra = ""
        if ok:
            n_wiki = len(list((p / "wiki").rglob("*.md"))) if (p / "wiki").is_dir() else 0
            extra = f"  ({n_wiki} 页 wiki)"
        print(f" {mark} {k:<14} {v}{extra}{status}")
    if default:
        print(f"\n★ = 默认库")
    return EXIT_OK


def _register(path: Path, name: str | None, *, created: bool) -> int:
    vaults, default = load_vault_registry()
    key = name or path.name
    if key in vaults and vaults[key] != str(path):
        eprint(f"[错误] 别名 '{key}' 已被占用（指向 {vaults[key]}）")
        eprint("       换个 --name，或先 remove 旧的")
        return EXIT_ERR
    vaults[key] = str(path)
    save_vault_registry(vaults, default)
    verb = "已创建并注册" if created else "已注册"
    print(f"✅ {verb} '{key}' → {path}")
    if len(vaults) > 1 and not default:
        print("   当前有多个库且未设默认；使用时需选择，或用 `use <别名>` 保存长期选择。")
    return EXIT_OK


def cmd_init(args) -> int:
    """本 skill 不建库 —— 那是 kg-init 的职责。这里只做引导。"""
    path = Path(args.path).expanduser().resolve()
    if looks_like_vault(path):
        eprint(f"[i] {path} 已经是知识库，直接注册")
        return _register(path, args.name, created=False)

    eprint(f"[错误] {path} 还不是知识库，本 skill 不负责创建。")
    eprint("")
    eprint("       建库/改造请用 kg-init（它有模板，且会先给你看计划）：")
    eprint("")
    if path.exists() and any(path.iterdir()):
        eprint(f"       # 这个目录已有内容 → 走「改造」流程")
        eprint(f"       cd ../kg-init")
        eprint(f'       python scripts/analyze_notes.py "{path}"      # 先体检')
        eprint(f'       python scripts/migrate.py plan "{path}"       # 看改造计划')
        eprint(f'       python scripts/migrate.py apply "{path}" --confirm')
    else:
        eprint(f"       # 空目录 → 走「新建」流程")
        eprint(f"       cd ../kg-init")
        eprint(f'       python scripts/migrate.py apply "{path}" --confirm')
    eprint("")
    eprint(f'       完成后注册：python ../kg-vault/scripts/vault_cli.py add "{path}"')
    return EXIT_ERR


def cmd_add(args) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        eprint(f"[错误] 目录不存在: {path}")
        return EXIT_ERR
    if not looks_like_vault(path):
        eprint(f"[错误] {path} 不像知识库（需要 AGENTS.md 和 wiki/ 目录）")
        eprint("       建库/改造旧笔记请先用 kg-init（有模板，会先出计划）,完成后再 add")
        return EXIT_ERR
    return _register(path, args.name, created=False)


def cmd_use(args) -> int:
    vaults, _ = load_vault_registry()
    if args.name not in vaults:
        eprint(f"[错误] 没有别名 '{args.name}'。现有：{', '.join(vaults) or '(空)'}")
        return EXIT_ERR
    save_vault_registry(vaults, args.name)
    print(f"✅ 默认库已切换为 '{args.name}' → {vaults[args.name]}")
    return EXIT_OK


def cmd_remove(args) -> int:
    vaults, default = load_vault_registry()
    if args.name not in vaults:
        eprint(f"[错误] 没有别名 '{args.name}'")
        return EXIT_ERR
    path = vaults.pop(args.name)
    if default == args.name:
        default = None
    save_vault_registry(vaults, default)
    print(f"✅ 已移除注册 '{args.name}'（目录未删除：{path}）")
    if default:
        print(f"   当前默认库：{default}")
    elif len(vaults) > 1:
        print("   默认库已清除；下次使用时需要选择，或用 `use <别名>` 设置。")
    return EXIT_OK


def cmd_doctor(args) -> int:
    print(f"# 配置检查\n")
    print(f"配置文件: {CONFIG_PATH} {'✅ 存在' if CONFIG_PATH.is_file() else '✗ 不存在'}")
    import os
    env = os.environ.get("KG_VAULT")
    if env:
        p = Path(env).expanduser()
        print(f"KG_VAULT: {env} {'✅ 有效（会覆盖配置文件）' if looks_like_vault(p) else '✗ 无效'}")
    else:
        print("KG_VAULT: 未设置（正常，配置文件优先级足够）")

    vaults, default = all_vaults()
    print(f"\n## 已注册 {len(vaults)} 个库\n")
    problems = 0
    for k, v in vaults.items():
        p = Path(v)
        mark = "★" if k == default else " "
        if not looks_like_vault(p):
            print(f" {mark} {k}: {v}\n     ✗ 无效（缺 AGENTS.md 或 wiki/）")
            problems += 1
            continue
        missing = [f for f in VAULT_FILES if not (p / f).is_file()]
        missing += [d + "/" for d in VAULT_DIRS if not (p / d).is_dir()]
        n = len(list((p / "wiki").rglob("*.md")))
        print(f" {mark} {k}: {v}\n     ✅ {n} 页 wiki"
              + (f" | 建议补: {', '.join(missing)}" if missing else ""))
        if missing:
            problems += 1
    if not vaults:
        print(" （空）→ 已有知识库用 add 注册；没有知识库先用 kg-init 创建")
        problems += 1
    print(f"\n{'✅ 配置正常' if problems == 0 else f'⚠️  有 {problems} 处需要注意'}")
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库注册与切换")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("which", help="当前会用哪个库（AI 拿不准时先跑这个）")
    sub.add_parser("list", help="列出已注册的库")
    sub.add_parser("doctor", help="检查配置与各库健康")

    p_init = sub.add_parser("init", help="（已不建库）注册已有库；未建则引导去 kg-init")
    p_init.add_argument("path")
    p_init.add_argument("--name", default=None, help="别名（默认取目录名）")

    p_add = sub.add_parser("add", help="注册已有的知识库目录")
    p_add.add_argument("path")
    p_add.add_argument("--name", default=None)

    p_use = sub.add_parser("use", help="切换默认库")
    p_use.add_argument("name")

    p_rm = sub.add_parser("remove", help="移除注册（不删目录）")
    p_rm.add_argument("name")

    args = ap.parse_args()
    try:
        return {
            "which": cmd_which, "list": cmd_list, "init": cmd_init,
            "add": cmd_add, "use": cmd_use, "remove": cmd_remove,
            "doctor": cmd_doctor,
        }[args.cmd](args)
    except (VaultNotFoundError, ValueError) as exc:
        eprint(f"[错误] {exc}")
        return EXIT_ERR


if __name__ == "__main__":
    sys.exit(main())
