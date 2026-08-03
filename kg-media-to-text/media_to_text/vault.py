"""定位知识库根目录（vault root）。

本模块让 skills 可以住在**任何位置**——库内、独立仓库、全局安装——
都能正确找到用户的知识库。这是 skills 独立开源的前提。

解析优先级（前面命中就不再往下找）：
  1. 命令行显式传入的 --vault
  2. 环境变量 KG_VAULT
  3. 配置文件 ~/.config/kg-wiki/config.json
  4. 从当前工作目录向上找（适合在库里执行命令时）
  5. 从本文件位置向上找（适合 skills 住在库内的传统布局）

"是知识库"的判据：目录下同时有 AGENTS.md 和 wiki/（index.md 可选，新库可能还没建）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "kg-wiki" / "config.json"
_MARKERS_REQUIRED = ("AGENTS.md",)
_MARKERS_DIR = ("wiki",)


class VaultNotFoundError(RuntimeError):
    """找不到知识库时抛出，消息里带可操作的指引。"""


def looks_like_vault(p: Path) -> bool:
    """判断某目录是否是知识库根。"""
    try:
        if not p.is_dir():
            return False
        if not all((p / m).is_file() for m in _MARKERS_REQUIRED):
            return False
        return all((p / d).is_dir() for d in _MARKERS_DIR)
    except OSError:
        return False


def _from_env() -> Path | None:
    v = os.environ.get("KG_VAULT")
    if not v:
        return None
    p = Path(v).expanduser().resolve()
    if looks_like_vault(p):
        return p
    raise VaultNotFoundError(
        f"环境变量 KG_VAULT 指向 {p}，但那里不像知识库"
        f"（需要 AGENTS.md 和 wiki/ 目录）。"
    )


def _from_config() -> Path | None:
    """从配置文件读。支持两种格式：

    单库:  {"vault": "/path/to/vault"}
    多库:  {"default": "work", "vaults": {"work": "/path/a", "personal": "/path/b"}}
    """
    if not CONFIG_PATH.is_file():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # 多库格式
    vaults = data.get("vaults")
    if isinstance(vaults, dict) and vaults:
        name = data.get("default")
        if name:
            v = vaults.get(name)
            if not v:
                raise VaultNotFoundError(f"配置的默认库 '{name}' 不存在。")
            p = Path(v).expanduser().resolve()
            if looks_like_vault(p):
                return p
            raise VaultNotFoundError(
                f"配置里的库 '{name}' 指向 {p}，但那里不像知识库。"
            )

        valid = []
        for key, value in vaults.items():
            p = Path(value).expanduser().resolve()
            if looks_like_vault(p):
                valid.append((key, p))
        if len(valid) == 1:
            return valid[0][1]
        if len(valid) > 1:
            raise VaultNotFoundError(
                "配置里有多个知识库但未指定默认：\n"
                + "\n".join(f"  · {k}: {p}" for k, p in valid)
                + "\n\n【给 AI 的指示】问用户这次要使用哪个库，然后："
                "\n  临时：加 --vault <路径>"
                "\n  长期：kg-vault/scripts/vault_cli.py use <别名>"
            )
        raise VaultNotFoundError("配置里的知识库路径都已失效，请询问用户新的路径。")

    # 单库格式
    v = data.get("vault")
    if not v:
        return None
    p = Path(v).expanduser().resolve()
    if looks_like_vault(p):
        return p
    raise VaultNotFoundError(
        f"配置文件 {CONFIG_PATH} 里的 vault 指向 {p}，但那里不像知识库。"
    )


def list_vaults() -> dict[str, str]:
    """列出配置里的所有库（多库格式时有用）。"""
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    if isinstance(data.get("vaults"), dict):
        out.update({k: str(v) for k, v in data["vaults"].items()})
    if data.get("vault"):
        out.setdefault("default", str(data["vault"]))
    return out


def _walk_up(start: Path, limit: int = 8) -> Path | None:
    cur = start.resolve()
    for _ in range(limit):
        if looks_like_vault(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def find_vault(hint: str | Path | None = None,
               explicit: str | Path | None = None) -> Path:
    """返回知识库根目录。找不到时抛 VaultNotFoundError（带可操作指引）。

    解析优先级：
        explicit（命令行 --vault）→ KG_VAULT 环境变量 → 配置文件
        → 从 cwd 向上找 → 从 hint 向上找

    Args:
        hint: 调用方 __file__，用于向上查找（skills 在库内时有效）
        explicit: 显式指定的路径（通常来自命令行 --vault），优先级最高
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if looks_like_vault(p):
            return p
        raise VaultNotFoundError(
            f"--vault 指向 {p}，但那里不像知识库（需要 AGENTS.md 和 wiki/ 目录）。"
        )

    p = _from_env()
    if p:
        return p
    p = _from_config()
    if p:
        return p

    # 从当前工作目录往上找
    p = _walk_up(Path.cwd())
    if p:
        return p

    # 从调用方文件位置往上找（skills 住在库内时有效）
    if hint:
        p = _walk_up(Path(hint).parent)
        if p:
            return p

    known = list_vaults()
    hint_lines = ""
    if known:
        hint_lines = "\n配置里已有这些库（但当前都不可用，可能路径已变）：\n" + "\n".join(
            f"  · {k}: {v}" for k, v in known.items())

    raise VaultNotFoundError(
        "找不到知识库 —— 不知道该把内容写到哪里。\n"
        f"{hint_lines}\n"
        "\n【给 AI 的指示】不要猜测路径，直接问用户：「你的知识库在哪个目录？」\n"
        "拿到路径后用下面任一方式继续：\n"
        "  1. 本次临时：   加 --vault /path/to/vault 参数\n"
        "  2. 长期注册：   python kg-vault/scripts/vault_cli.py add /path/to/vault\n"
        "  3. 环境变量：   export KG_VAULT=/path/to/vault\n"
        "\n知识库需包含 AGENTS.md 和 wiki/ 目录。"
        "\n没有现成的库？先用 kg-init 建库，再用 kg-vault 注册路径。"
    )


def save_config(vault: str | Path) -> Path:
    """把库路径写进配置文件，返回配置文件路径。"""
    p = Path(vault).expanduser().resolve()
    if not looks_like_vault(p):
        raise VaultNotFoundError(f"{p} 不像知识库（需要 AGENTS.md 和 wiki/）。")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if CONFIG_PATH.is_file():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data["vault"] = str(p)
    CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return CONFIG_PATH
