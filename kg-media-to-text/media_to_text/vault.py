"""定位知识库根目录（vault root）。

本模块让 skills 可以住在**任何位置**——库内、独立仓库、全局安装——
都能正确找到用户的知识库。这是 skills 独立开源的前提。

解析优先级（前面命中就不再往下找）：
  1. 命令行显式传入的 --vault
  2. 环境变量 KG_VAULT
  3. 配置文件 ~/.kg-agent-config/config.json
  4. 从当前工作目录向上找（适合在库里执行命令时）
  5. 从本文件位置向上找（适合 skills 住在库内的传统布局）

"是知识库"的判据：目录下同时有 AGENTS.md 和 wiki/（index.md 可选，新库可能还没建）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# 统一配置目录。KG_AGENT_CONFIG_DIR 可覆盖（测试用）。
_CFG_DIR = Path(os.environ.get("KG_AGENT_CONFIG_DIR",
                               Path.home() / ".kg-agent-config"))
CONFIG_PATH = _CFG_DIR / "config.json"
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


def _read_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VaultNotFoundError(f"配置文件 {CONFIG_PATH} 不是合法 JSON：{exc}") from exc
    except OSError as exc:
        raise VaultNotFoundError(f"无法读取配置文件 {CONFIG_PATH}：{exc}") from exc
    if not isinstance(data, dict):
        raise VaultNotFoundError(f"配置文件 {CONFIG_PATH} 的顶层必须是 JSON 对象。")
    return data


def load_vault_registry() -> tuple[dict[str, str], str | None]:
    """读取知识库注册表，兼容旧格式但不修改配置文件。

    规范格式位于共享配置的 ``vault`` 分域：
    ``{"vault": {"default": "personal", "paths": {"personal": "/path"}}}``。
    """
    data = _read_config()

    def default_name(value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise VaultNotFoundError("配置中的 vault.default 必须是字符串或 null。")
        return value

    vnode = data.get("vault")
    if isinstance(vnode, dict) and isinstance(vnode.get("paths"), dict):
        paths = {str(k): str(v) for k, v in vnode["paths"].items()
                 if isinstance(v, (str, os.PathLike))}
        return paths, default_name(vnode.get("default"))

    vaults = data.get("vaults")
    if isinstance(vaults, dict) and vaults:
        return ({str(k): str(v) for k, v in vaults.items()
                 if isinstance(v, (str, os.PathLike))},
                default_name(data.get("default")))

    if isinstance(vnode, (str, os.PathLike)):
        return {"default": str(vnode)}, "default"
    return {}, None


def load_vault_descriptions() -> dict[str, str]:
    """读取别名对应的用途描述；旧配置没有 descriptions 时返回空。"""
    data = _read_config()
    vnode = data.get("vault")
    if not isinstance(vnode, dict):
        return {}
    descriptions = vnode.get("descriptions")
    if not isinstance(descriptions, dict):
        return {}
    return {
        str(key): value.strip()
        for key, value in descriptions.items()
        if isinstance(value, str) and value.strip()
    }


def save_vault_registry(paths: dict[str, str], default: str | None,
                        descriptions: dict[str, str] | None = None) -> Path:
    """原子写入规范 vault 分域，同时保留 collect/report 等其他配置。"""
    clean = {str(k): str(Path(v).expanduser()) for k, v in paths.items()}
    if default is not None and default not in clean:
        raise ValueError(f"默认库 '{default}' 不在 paths 中")

    data = _read_config()
    if descriptions is None:
        vnode = data.get("vault")
        raw_descriptions = vnode.get("descriptions") if isinstance(vnode, dict) else None
        descriptions = raw_descriptions if isinstance(raw_descriptions, dict) else {}
    clean_descriptions = {
        str(key): value.strip()
        for key, value in descriptions.items()
        if str(key) in clean and isinstance(value, str) and value.strip()
    }
    data.setdefault("version", 1)
    data["vault"] = {
        "default": default,
        "paths": clean,
        "descriptions": clean_descriptions,
    }
    # 只在写操作时迁移旧格式，避免同一份配置存在两个真相。
    data.pop("vaults", None)
    data.pop("default", None)

    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_PATH.parent.chmod(0o700)
    except OSError:
        pass
    tmp = CONFIG_PATH.with_name(f".{CONFIG_PATH.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    tmp.replace(CONFIG_PATH)
    return CONFIG_PATH


def _from_config() -> Path | None:
    """从共享配置的 vault 分域读取并验证知识库路径。"""
    paths, default = load_vault_registry()
    if not paths:
        return None

    if default:
        value = paths.get(default)
        if value is None:
            raise VaultNotFoundError(f"配置的默认库 '{default}' 不存在。")
        p = Path(value).expanduser().resolve()
        if looks_like_vault(p):
            return p
        raise VaultNotFoundError(
            f"配置里的库 '{default}' 指向 {p}，但那里不像知识库。")

    valid = []
    for key, value in paths.items():
        p = Path(value).expanduser().resolve()
        if looks_like_vault(p):
            valid.append((key, p))
    if len(valid) == 1:
        return valid[0][1]
    if len(valid) > 1:
        descriptions = load_vault_descriptions()
        raise VaultNotFoundError(
            "配置里有多个知识库但未指定默认：\n"
            + "\n".join(
                f"  · {k}: {p}"
                + (f" — {descriptions[k]}" if descriptions.get(k) else "")
                for k, p in valid)
            + "\n\n【给 AI 的指示】运行 kg-vault list --json，按 desc 判断本次内容最适合的库，"
            "然后给原命令显式加 --vault <路径>。不要仅因为有多个库就询问用户。")
    raise VaultNotFoundError("配置里的知识库路径都已失效，请询问用户新的路径。")


def list_vaults() -> dict[str, str]:
    """列出配置里的所有库（多库格式时有用）。"""
    return load_vault_registry()[0]


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
    """注册并设为默认库；保留共享配置中的其他分域。"""
    p = Path(vault).expanduser().resolve()
    if not looks_like_vault(p):
        raise VaultNotFoundError(f"{p} 不像知识库（需要 AGENTS.md 和 wiki/）。")
    paths, _ = load_vault_registry()
    name = p.name
    paths[name] = str(p)
    return save_vault_registry(paths, name)
