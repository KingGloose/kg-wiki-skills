#!/usr/bin/env python3
"""知识库注册与切换 —— 解决"往哪写"这一个问题。

所有其他 kg-* skill 都靠这里的配置定位知识库。配置在
`~/.config/kg-wiki/config.json`。

用法:
  python vault_cli.py which                    # 当前会用哪个库（AI 拿不准时先跑这个）
  python vault_cli.py list                     # 列出已注册的库
  python vault_cli.py init <路径> [--name 别名]  # 从模板建新库并注册
  python vault_cli.py add <路径> [--name 别名]   # 把已有目录注册进来
  python vault_cli.py use <别名>                # 切换默认库
  python vault_cli.py remove <别名>             # 移除注册（不删目录）
  python vault_cli.py doctor                   # 检查配置与各库健康

退出码：0 正常；1 出错；2 需要询问用户（多库无默认 / 未配置）
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "kg-wiki" / "config.json"
TEMPLATES = Path(__file__).resolve().parent.parent.parent / "templates"
VAULT_DIRS = ("wiki", "raw", "assets")
VAULT_FILES = ("AGENTS.md", "index.md", "log.md")

# 退出码语义
EXIT_OK = 0
EXIT_ERR = 1
EXIT_ASK_USER = 2


def eprint(*a, **k):
    print(*a, file=sys.stderr, **k)


def looks_like_vault(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "AGENTS.md").is_file() and (p / "wiki").is_dir()
    except OSError:
        return False


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")


def normalize(data: dict) -> dict:
    """把旧的单库格式 {"vault": path} 升级成多库格式，保持兼容。"""
    if "vaults" not in data:
        data["vaults"] = {}
    old = data.pop("vault", None)
    if old and old not in data["vaults"].values():
        data["vaults"]["default"] = old
        data.setdefault("default", "default")
    return data


def all_vaults() -> tuple[dict[str, str], str | None]:
    """返回 (别名→路径, 默认别名)。"""
    data = normalize(load_config())
    return data.get("vaults", {}), data.get("default")


def cmd_which(args) -> int:
    vaults, default = all_vaults()
    valid = {k: v for k, v in vaults.items() if looks_like_vault(Path(v))}
    invalid = {k: v for k, v in vaults.items() if k not in valid}

    if not vaults:
        print("未注册任何知识库。")
        print("\n【给 AI 的指示】问用户「你的知识库在哪个目录？」")
        print("  · 已有库 → python vault_cli.py add <路径>")
        print("  · 没有库 → python vault_cli.py init <路径>（从模板创建）")
        return EXIT_ASK_USER

    if not valid:
        print("已注册的库路径都无效（可能已移动或删除）：")
        for k, v in invalid.items():
            print(f"  ✗ {k}: {v}")
        print("\n【给 AI 的指示】问用户新路径，然后 add / remove 修正。")
        return EXIT_ASK_USER

    # 有默认且有效 → 直接给答案
    if default and default in valid:
        print(valid[default])
        eprint(f"[i] 使用默认库 '{default}'")
        if invalid:
            eprint(f"[warn] 另有 {len(invalid)} 个注册路径已失效：{', '.join(invalid)}")
        return EXIT_OK

    # 只有一个有效库 → 无歧义
    if len(valid) == 1:
        k, v = next(iter(valid.items()))
        print(v)
        eprint(f"[i] 只有一个有效库 '{k}'")
        return EXIT_OK

    # 多个有效库但无明确默认 → 必须问用户
    print("有多个已注册的知识库，但没有指定默认：")
    for k, v in valid.items():
        print(f"  · {k}: {v}")
    print("\n【给 AI 的指示】问用户「这次要写到哪个库？」")
    print("  临时指定：其他脚本加 --vault <路径>")
    print(f"  设为默认：python vault_cli.py use <别名>")
    return EXIT_ASK_USER


def cmd_list(args) -> int:
    vaults, default = all_vaults()
    if not vaults:
        print("未注册任何知识库。用 `init` 或 `add` 添加。")
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
    data = normalize(load_config())
    key = name or path.name
    if key in data["vaults"] and data["vaults"][key] != str(path):
        eprint(f"[错误] 别名 '{key}' 已被占用（指向 {data['vaults'][key]}）")
        eprint("       换个 --name，或先 remove 旧的")
        return EXIT_ERR
    data["vaults"][key] = str(path)
    data.setdefault("default", key)
    save_config(data)
    verb = "已创建并注册" if created else "已注册"
    print(f"✅ {verb} '{key}' → {path}")
    if data.get("default") == key:
        print("   （已设为默认库）")
    return EXIT_OK


def cmd_init(args) -> int:
    path = Path(args.path).expanduser().resolve()
    if looks_like_vault(path):
        eprint(f"[i] {path} 已经是知识库，直接注册（不覆盖任何文件）")
        return _register(path, args.name, created=False)
    if path.exists() and any(path.iterdir()):
        eprint(f"[错误] {path} 已存在且非空，但不像知识库。")
        eprint("       为安全起见不动它。请换个空目录，或手动补 AGENTS.md + wiki/ 后用 add。")
        return EXIT_ERR
    if not TEMPLATES.is_dir():
        eprint(f"[错误] 找不到模板目录 {TEMPLATES}")
        return EXIT_ERR

    for d in VAULT_DIRS:
        (path / d).mkdir(parents=True, exist_ok=True)
    for f in VAULT_FILES:
        src = TEMPLATES / f
        if src.is_file():
            shutil.copy2(src, path / f)
    print(f"✅ 已创建知识库结构于 {path}")
    print(f"   目录: {', '.join(VAULT_DIRS)}")
    print(f"   文件: {', '.join(VAULT_FILES)}（来自 templates/）")
    print("\n下一步：按自己的习惯改 AGENTS.md（尤其「写作约定」和「领域划分」）")
    return _register(path, args.name, created=True)


def cmd_add(args) -> int:
    path = Path(args.path).expanduser().resolve()
    if not path.is_dir():
        eprint(f"[错误] 目录不存在: {path}")
        return EXIT_ERR
    if not looks_like_vault(path):
        eprint(f"[错误] {path} 不像知识库（需要 AGENTS.md 和 wiki/ 目录）")
        eprint("       想新建请用 init；已有内容请手动补齐这两项再 add")
        return EXIT_ERR
    return _register(path, args.name, created=False)


def cmd_use(args) -> int:
    data = normalize(load_config())
    if args.name not in data.get("vaults", {}):
        eprint(f"[错误] 没有别名 '{args.name}'。现有：{', '.join(data.get('vaults', {})) or '(空)'}")
        return EXIT_ERR
    data["default"] = args.name
    save_config(data)
    print(f"✅ 默认库已切换为 '{args.name}' → {data['vaults'][args.name]}")
    return EXIT_OK


def cmd_remove(args) -> int:
    data = normalize(load_config())
    if args.name not in data.get("vaults", {}):
        eprint(f"[错误] 没有别名 '{args.name}'")
        return EXIT_ERR
    path = data["vaults"].pop(args.name)
    if data.get("default") == args.name:
        data["default"] = next(iter(data["vaults"]), None)
        if data["default"] is None:
            data.pop("default", None)
    save_config(data)
    print(f"✅ 已移除注册 '{args.name}'（目录未删除：{path}）")
    if data.get("default"):
        print(f"   当前默认库：{data['default']}")
    return EXIT_OK


def cmd_doctor(args) -> int:
    print(f"# 配置检查\n")
    print(f"配置文件: {CONFIG_PATH} {'✅ 存在' if CONFIG_PATH.is_file() else '✗ 不存在'}")
    print(f"模板目录: {TEMPLATES} {'✅ 存在' if TEMPLATES.is_dir() else '✗ 不存在'}")
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
        print(" （空）→ 用 init 或 add 添加")
        problems += 1
    print(f"\n{'✅ 配置正常' if problems == 0 else f'⚠️  有 {problems} 处需要注意'}")
    return EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description="知识库注册与切换")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("which", help="当前会用哪个库（AI 拿不准时先跑这个）")
    sub.add_parser("list", help="列出已注册的库")
    sub.add_parser("doctor", help="检查配置与各库健康")

    p_init = sub.add_parser("init", help="从模板创建新库并注册")
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
    return {
        "which": cmd_which, "list": cmd_list, "init": cmd_init,
        "add": cmd_add, "use": cmd_use, "remove": cmd_remove,
        "doctor": cmd_doctor,
    }[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
