"""公共工具：加载 cookie、构造 Credential。跨平台（Mac/WSL/Windows）通用。"""
import os
import json
import pathlib
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = SKILL_DIR / ".env"


def select_http_client():
    """注册并选中 curl_cffi 作为 HTTP client。

    bilibili-api-python 的 HTTP client 是可插拔的，裸装不带任何 client，
    必须显式选一个才能发请求。curl_cffi 是官方推荐（可模拟浏览器指纹绕风控）。
    每个用到网络的脚本在 load_credential 前调用一次即可。
    """
    from bilibili_api import select_client
    select_client("curl_cffi")


def load_credential():
    """读 B 站 cookie，返回 bilibili_api.Credential。

    凭据统一放 ~/.kg-agent-config/credentials.json 的 bilibili 段：
        "bilibili": {"SESSDATA": "...", "BILI_JCT": "...", "BUVID3": "..."}

    为什么不再用 skill 目录下的 .env：凭据散在各 skill 里既难找也容易
    误提交，统一到 home 下的配置目录后物理上不可能被 git 带走。
    """
    from bilibili_api import Credential

    cfg_dir = pathlib.Path(os.environ.get("KG_AGENT_CONFIG_DIR",
                                          pathlib.Path.home() / ".kg-agent-config"))
    cred_file = cfg_dir / "credentials.json"
    cfg = {}
    if cred_file.is_file():
        try:
            cfg = (json.loads(cred_file.read_text(encoding="utf-8"))
                   .get("bilibili") or {})
        except ValueError as e:
            sys.exit(f"[错误] {cred_file} 不是合法 JSON：{e}")

    # 兼容：环境变量可临时覆盖
    sessdata = (os.environ.get("BILI_SESSDATA")
                or cfg.get("SESSDATA") or "").strip()
    if not sessdata:
        sys.exit(
            f"[错误] 没有 B 站 SESSDATA。\n"
            f"  在 {cred_file} 里加：\n"
            f'    "bilibili": {{"SESSDATA": "...", "BILI_JCT": "...", "BUVID3": "..."}}\n'
            f"  值从浏览器 F12 → Application → Cookies → bilibili.com 复制，\n"
            f"  或跑 login.py 扫码登录。")

    return Credential(
        sessdata=sessdata,
        bili_jct=(cfg.get("BILI_JCT") or "").strip() or None,
        buvid3=(cfg.get("BUVID3") or "").strip() or None,
    )


def eprint(*args, **kwargs):
    """打到 stderr，避免污染 stdout 的 JSON 输出。"""
    print(*args, file=sys.stderr, **kwargs)
