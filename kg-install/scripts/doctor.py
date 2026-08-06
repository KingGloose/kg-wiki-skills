#!/usr/bin/env python3
"""环境体检 —— 只诊断，不安装。

设计意图：把"这台机器现在是什么状况"变成 AI 可读的结构化事实，
让 AI 自己决定装什么、怎么装。本脚本刻意不做任何安装动作，
因为安装决策依赖用户的需求（他要处理什么内容），那是对话里才能问清的。

用法:
  python doctor.py            # 人类可读报告
  python doctor.py --json     # 结构化输出（AI 优先用这个）
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


# ---------- 探测：平台 ----------

def probe_platform() -> dict:
    system = platform.system()
    machine = platform.machine()
    is_wsl = False
    if system == "Linux":
        try:
            is_wsl = "microsoft" in Path("/proc/version").read_text().lower()
        except OSError:
            pass

    apple_silicon = system == "Darwin" and machine in ("arm64", "aarch64")

    if system == "Darwin":
        label = f"macOS {'Apple Silicon' if apple_silicon else 'Intel'}"
        pkg_mgr = "brew"
    elif is_wsl:
        label = "Windows WSL2"
        pkg_mgr = "apt"
    elif system == "Linux":
        label = "Linux"
        pkg_mgr = "apt"
    elif system == "Windows":
        label = "Windows（原生）"
        pkg_mgr = "winget"
    else:
        label = f"{system}（未适配）"
        pkg_mgr = None

    if system == "Windows":
        activate = r".venv\Scripts\Activate.ps1  (PowerShell) / .venv\Scripts\activate.bat  (CMD)"
    else:
        activate = "source .venv/bin/activate"

    info = {
        "activate_cmd": activate,
        "system": system,
        "machine": machine,
        "label": label,
        "is_wsl": is_wsl,
        "apple_silicon": apple_silicon,
        "pkg_manager": pkg_mgr,
        "supported": system in ("Darwin", "Linux", "Windows"),
    }

    # 内存与核数——决定本地 ASR 跑不跑得动
    try:
        if system == "Darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=5)
            if out.returncode == 0:
                info["ram_gb"] = round(int(out.stdout.strip()) / 1024**3)
        elif system == "Linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    info["ram_gb"] = round(int(line.split()[1]) / 1024**2)
                    break
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    info["cpu_count"] = os.cpu_count()
    return info


def probe_gpu(plat: dict) -> dict:
    """GPU 决定本地 ASR 的速度档位。"""
    if plat["apple_silicon"]:
        return {"kind": "apple-metal", "usable_for_asr": True,
                "note": "Apple Silicon 统一内存 + Metal，mlx-whisper 可用 GPU 加速"}

    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi and platform.system() == "Windows":
        # Windows 上 nvidia-smi 常不在 PATH，试默认安装位置
        fallback = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if fallback.is_file():
            nvidia_smi = str(fallback)
    if not nvidia_smi:
        return {"kind": "none", "usable_for_asr": False,
                "note": "未检测到 NVIDIA GPU，本地 ASR 只能跑 CPU（慢，约实时的 1-3 倍耗时）"}

    try:
        out = subprocess.run(
            [nvidia_smi, "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return {"kind": "nvidia-broken", "usable_for_asr": False,
                    "note": "nvidia-smi 存在但执行失败，驱动可能有问题"}
        first = out.stdout.strip().splitlines()[0]
        parts = [p.strip() for p in first.split(",")]
        return {"kind": "nvidia", "usable_for_asr": True, "name": parts[0],
                "memory": parts[1] if len(parts) > 1 else None,
                "driver": parts[2] if len(parts) > 2 else None,
                "note": "faster-whisper 可走 CUDA（需 CUDA 12 + cuDNN 9）"}
    except (subprocess.SubprocessError, IndexError):
        return {"kind": "unknown", "usable_for_asr": False,
                "note": "GPU 探测失败"}


# ---------- 探测：工具链 ----------

def probe_tools() -> dict:
    tools = {}
    for name, why in [
        ("uv", "Python 环境管理（必需）"),
        ("ffmpeg", "音视频抽轨/转码（音视频转写必需）"),
        ("git", "版本管理（可选，但强烈建议库用 git 管）"),
        ("nvidia-smi", "NVIDIA GPU 查询"),
    ]:
        path = shutil.which(name)
        entry = {"found": path is not None, "path": path, "why": why}
        # ffmpeg 用单横线 -version，别的用 --version
        flag = "-version" if name == "ffmpeg" else "--version"
        if path and name in ("uv", "ffmpeg", "git"):
            try:
                out = subprocess.run([path, flag], capture_output=True,
                                     text=True, timeout=10)
                if out.returncode == 0 and out.stdout.strip():
                    entry["version"] = out.stdout.strip().splitlines()[0][:80]
            except subprocess.SubprocessError:
                pass
        tools[name] = entry
    return tools


# ---------- 探测：Python 环境与已装包 ----------

def probe_venv() -> dict:
    venv = REPO / ".venv"
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    info = {"path": str(venv), "exists": venv.is_dir(), "python_ok": py.is_file()}
    if not info["python_ok"]:
        return info
    try:
        out = subprocess.run([str(py), "--version"], capture_output=True,
                             text=True, timeout=10)
        info["python_version"] = out.stdout.strip() or out.stderr.strip()
    except subprocess.SubprocessError:
        pass

    # 按「能力」分组检查，而不是按包名——AI 关心的是"能不能干这事"
    caps = {
        "基础抓取": ["curl_cffi", "bs4", "lxml"],
        "B站": ["bilibili_api"],
        "公众号": ["markdownify"],
        "文档解析": ["docling", "markitdown"],
        "音视频转写": ["mlx_whisper"] if platform.system() == "Darwin" else ["faster_whisper"],
        "音视频下载": ["yt_dlp"],
        "底层库": ["media_to_text"],
    }
    probe_src = "import importlib.util,json;print(json.dumps({m:importlib.util.find_spec(m) is not None for m in %r}))" % (
        sorted({m for ms in caps.values() for m in ms}),)
    found = {}
    try:
        out = subprocess.run([str(py), "-c", probe_src],
                             capture_output=True, text=True, timeout=60)
        if out.returncode == 0:
            found = json.loads(out.stdout.strip())
    except (subprocess.SubprocessError, json.JSONDecodeError):
        pass

    info["capabilities"] = {
        cap: {"ready": all(found.get(m, False) for m in mods),
              "missing": [m for m in mods if not found.get(m, False)]}
        for cap, mods in caps.items()
    }
    return info


def probe_vault() -> dict:
    """知识库定位 —— 装好了但不知道往哪写,等于没装。"""
    info = {"env_KG_VAULT": os.environ.get("KG_VAULT"),
            "config_path": str(Path.home() / ".kg-agent-config/config.json")}
    cfg = Path(info["config_path"])
    info["config_exists"] = cfg.is_file()
    if info["config_exists"]:
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            info["config"] = data
            info["registered"] = list(data.get("vaults", {}).keys()) or (
                ["<单库格式>"] if data.get("vault") else [])
        except (json.JSONDecodeError, OSError) as e:
            info["config_error"] = str(e)

    py = REPO / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if py.is_file():
        try:
            out = subprocess.run(
                [str(py), "-c",
                 "from media_to_text import find_vault; print(find_vault())"],
                capture_output=True, text=True, timeout=20, cwd=str(REPO))
            if out.returncode == 0:
                info["resolved"] = out.stdout.strip()
            else:
                info["resolve_error"] = out.stderr.strip().splitlines()[-1] if out.stderr.strip() else "解析失败"
        except subprocess.SubprocessError:
            pass
    return info


def probe_registration() -> dict:
    """是否注册到全局,决定 AI 能否在任意目录发现这些 skill。"""
    candidates = [Path.home() / ".agents/skills", Path.home() / ".claude/skills"]
    result = {}
    for base in candidates:
        entry = {"dir_exists": base.is_dir(), "linked": False}
        if base.is_dir():
            for child in base.iterdir():
                try:
                    if child.is_symlink() and child.resolve() == REPO:
                        entry["linked"] = True
                        entry["link_name"] = child.name
                        break
                except OSError:
                    continue
        result[str(base)] = entry
    return result


def _ffmpeg_hint(plat: dict) -> str:
    """各平台装 ffmpeg 的方式。"""
    return {
        "Darwin": "brew install ffmpeg",
        "Windows": "winget install ffmpeg  (或 scoop install ffmpeg)",
    }.get(plat["system"], "sudo apt install -y ffmpeg")


# ---------- 报告 ----------

def human_report(d: dict) -> str:
    L = []
    p, gpu = d["platform"], d["gpu"]
    L.append("# 环境体检\n")
    L.append(f"平台: {p['label']} ({p['machine']})"
             + (f" · {p['ram_gb']}GB 内存" if p.get("ram_gb") else "")
             + (f" · {p['cpu_count']} 核" if p.get("cpu_count") else ""))
    if not p["supported"]:
        L.append(f"  ⚠️  {p['system']} 未适配（支持 macOS / Linux / WSL2）")
    L.append(f"GPU: {gpu['kind']}" + (f" · {gpu.get('name')}" if gpu.get("name") else ""))
    L.append(f"     {gpu['note']}")

    L.append("\n## 工具链")
    for name, t in d["tools"].items():
        if name == "nvidia-smi" and not t["found"]:
            continue
        mark = "✅" if t["found"] else ("❌" if name == "uv" else "○ ")
        L.append(f"  {mark} {name:12s} {t.get('version') or ('缺失 —— ' + t['why'])}")

    v = d["venv"]
    L.append(f"\n## Python 环境  {'✅ ' + v.get('python_version', '') if v['python_ok'] else '❌ 未创建'}")
    L.append(f"  激活: {p['activate_cmd']}")
    if v.get("capabilities"):
        for cap, s in v["capabilities"].items():
            L.append(f"  {'✅' if s['ready'] else '○ '} {cap}"
                     + ("" if s["ready"] else f"  (缺 {', '.join(s['missing'])})"))

    vault = d["vault"]
    L.append("\n## 知识库定位")
    if vault.get("resolved"):
        L.append(f"  ✅ {vault['resolved']}")
    else:
        L.append("  ❌ 未配置 —— skills 不知道往哪写")
        if vault.get("registered"):
            L.append(f"     配置里已注册: {', '.join(vault['registered'])}")

    L.append("\n## 全局注册")
    any_linked = False
    for base, r in d["registration"].items():
        if r["linked"]:
            L.append(f"  ✅ {base}/{r.get('link_name')} → 本仓库")
            any_linked = True
    if not any_linked:
        L.append("  ○  未注册 —— AI 只能在本仓库目录内发现这些 skill")

    if d["blockers"]:
        L.append("\n## 阻塞项（必须先解决）")
        for b in d["blockers"]:
            L.append(f"  ❌ {b}")
    if d["notes"]:
        L.append("\n## 提示")
        for n in d["notes"]:
            L.append(f"  · {n}")

    L.append("\n---\n**给 AI**：这只是体检。装什么取决于用户要处理的内容——")
    L.append("先问他（视频/播客/文章/文档/纯写作），再按 SKILL.md 的能力矩阵裁剪，")
    L.append("**不要默认装全套**（文档解析 ~1GB、Whisper 模型 ~1.5GB）。")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="环境体检（只诊断，不安装）")
    ap.add_argument("--json", action="store_true", help="结构化输出")
    args = ap.parse_args()

    plat = probe_platform()
    data = {
        "repo": str(REPO),
        "platform": plat,
        "gpu": probe_gpu(plat),
        "tools": probe_tools(),
        "venv": probe_venv(),
        "vault": probe_vault(),
        "registration": probe_registration(),
        "blockers": [],
        "notes": [],
    }

    if not plat["supported"]:
        data["blockers"].append(
            f"{plat['system']} 未适配（支持 macOS / Linux / WSL2 / Windows）。")
    if not data["tools"]["uv"]["found"]:
        data["blockers"].append(
            "uv 未安装（必需）。装法: curl -LsSf https://astral.sh/uv/install.sh | sh，"
            "装完重开终端。")

    if not data["tools"]["ffmpeg"]["found"]:
        data["notes"].append(
            f"ffmpeg 未装 —— 只有音视频转写需要它。要装: {_ffmpeg_hint(plat)}")
    if plat["system"] == "Windows":
        data["notes"].append(
            "原生 Windows：本地 ASR 用 faster-whisper（mlx 仅 Apple Silicon）。"
            "有 NVIDIA 卡需 CUDA 12 + cuDNN 9，否则降级 CPU。"
            "**若遇到 CUDA/cuDNN 配置困难，WSL2 通常更省事**。")
        data["notes"].append(
            "原生 Windows 上 Docling（文档解析）偶有依赖编译问题；"
            "若装不上可改用 WSL2，或先跳过文档能力。")
    if plat["system"] == "Darwin" and not plat["apple_silicon"]:
        data["notes"].append(
            "Intel Mac 无 Metal 加速，本地转写只能跑 CPU（1 小时音频约 20-40 分钟）。"
            "内容量大的话建议先只装文本类能力。")
    if data["gpu"]["kind"] == "none" and plat["system"] == "Linux":
        data["notes"].append(
            "无 NVIDIA GPU，faster-whisper 会降级 CPU。可先跳过转写，用平台现成字幕（L0）。")
    if plat.get("ram_gb") and plat["ram_gb"] < 8:
        data["notes"].append(
            f"内存仅 {plat['ram_gb']}GB —— large-v3 模型吃紧，建议改用 small/medium 模型。")
    if not data["vault"].get("resolved"):
        data["notes"].append(
            "知识库未配置。有旧笔记要改造走 kg-init；已有标准结构走 kg-vault add。")

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(human_report(data))
    return 1 if data["blockers"] else 0


if __name__ == "__main__":
    sys.exit(main())
