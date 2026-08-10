#!/usr/bin/env python3
"""二维码登录 B 站，把 cookie 写进 skill 目录的 .env。

用法:
  python login.py

流程: 终端打印二维码 → 手机 B 站 APP 扫码确认 → 自动轮询 → 成功后写 .env。
跨平台通用（Mac/WSL/Windows 终端都能显示二维码）。
"""
import asyncio
import os
import pathlib
import sys
import time
from pathlib import Path

from bilibili_api import login_v2, sync
from _common import select_http_client, SKILL_DIR, ENV_PATH, eprint


def write_env(cred):
    cookies = cred.get_cookies()  # dict: SESSDATA / bili_jct / buvid3 / DedeUserID ...
    sessdata = cookies.get("SESSDATA", "")
    bili_jct = cookies.get("bili_jct", "")
    buvid3 = cookies.get("buvid3", "")
    dedeuserid = cookies.get("DedeUserID", "")

    # 写进统一凭据文件（原子写，避免写一半崩掉丢掉其他凭据）
    import json, os, tempfile
    cfg_dir = pathlib.Path(os.environ.get(
        "KG_AGENT_CONFIG_DIR", pathlib.Path.home() / ".kg-agent-config"))
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cred_file = cfg_dir / "credentials.json"
    data = {}
    if cred_file.is_file():
        try:
            data = json.loads(cred_file.read_text(encoding="utf-8"))
        except ValueError:
            pass          # 坏文件不覆盖用户其他凭据，交由下面报错
    data["bilibili"] = {
        "//": "由 kg-ingest/references/bilibili/login.py 扫码登录写入。SESSDATA 约一个月过期。",
        "SESSDATA": sessdata,
        "BILI_JCT": bili_jct,
        "BUVID3": buvid3,
        "DEDEUSERID": dedeuserid,
    }
    tmp = cred_file.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(cred_file)
    eprint(f"[ok] cookie 已写入 {cred_file}")
    return sessdata


async def run():
    select_http_client()
    qr = login_v2.QrCodeLogin(platform=login_v2.QrCodeLoginChannel.WEB)
    await qr.generate_qrcode()

    # 存二维码图片（终端 ANSI 色块在很多环境无法扫描，图片更通用）
    qr_path = SKILL_DIR / "qrcode.png"
    pic = qr.get_qrcode_picture()
    pic.to_file(str(qr_path))
    eprint(f"[qr] 二维码图片已保存: {qr_path}")
    # WSL：文件在 Linux 侧，用 Windows 看图得走 \\wsl$ 路径，这里直接给出来
    try:
        if "microsoft" in Path("/proc/version").read_text().lower():
            distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
            eprint(f"[qr] WSL 提示：在 Windows 资源管理器打开 "
                   f"\\\\wsl$\\{distro}{str(qr_path).replace('/', chr(92))}")
            eprint("[qr]   或直接扫下方终端二维码（Windows Terminal 显示正常）")
    except OSError:
        pass
    print(qr.get_qrcode_terminal())
    eprint("[..] 请用手机 B 站 APP 扫描二维码并确认登录（限时约 3 分钟）")

    while not qr.has_done():
        state = await qr.check_state()
        if state == login_v2.QrCodeLoginEvents.TIMEOUT:
            eprint("[x] 二维码已过期，请重新运行 login.py")
            sys.exit(1)
        elif state == login_v2.QrCodeLoginEvents.SCAN:
            pass  # 还没扫
        elif state == login_v2.QrCodeLoginEvents.CONF:
            eprint("[..] 已扫描，请在手机上点击确认")
        await asyncio.sleep(2)

    cred = qr.get_credential()
    cookies = cred.get_cookies()
    sessdata = (cookies.get("SESSDATA") or "").strip()
    if not sessdata:
        eprint("[x] 未拿到 SESSDATA（登录未成功），**不覆盖**现有 cookie。")
        eprint("[x] 请重新运行 login.py 再试（可能上次确认晚了/二维码过期）。")
        sys.exit(1)
    write_env(cred)
    eprint(f"[ok] 登录成功，cookie 已写入 {ENV_PATH}")
    try:
        (SKILL_DIR / "qrcode.png").unlink(missing_ok=True)
    except Exception:
        pass


if __name__ == "__main__":
    sync(run())
