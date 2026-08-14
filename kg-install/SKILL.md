---
name: kg-install
description: 安装和诊断 kg-wiki-skills 环境。先检查 Node、可选 Python 后端、ffmpeg、知识库路由与项目或用户级软链，再按用户真正需要的内容安装依赖。当用户说「帮我装一下」「配置环境」「skill 跑不起来」「缺依赖」「ModuleNotFoundError」时使用。覆盖 macOS、Linux、WSL2 和原生 Windows。
---

# kg-install · 按需安装

核心原则：**Node 是默认运行时，Python 是媒体和特殊平台的可选后端。**
只做查库、灵感、学习、回顾、lint、地图、AIHOT、GitHub、YouTube 字幕、微信读书时，
不需要创建 Python 环境。

## 1. 先体检

```bash
../bin/kg-node kg-install/scripts/doctor.mjs --json
```

体检只读不安装，报告：

- Node/npm 版本（Node 要求 `>=22.13`）
- git、uv、ffmpeg、GPU
- Python `.venv` 中各可选能力是否就绪
- 知识库注册、默认库和项目/用户级 skill 软链

先解决 `blockers`；`notes` 是按需项，不要全部安装。

## 2. 问用户要处理什么

必须先问内容类型，再决定依赖：

1. 只写笔记、查库、回顾、地图或普通 Node 能力
2. B 站
3. 公众号 / 小宇宙
4. YouTube 或播客无字幕时的本地转写
5. PDF / Word / PPT / Excel

视频/播客再确认是否已有字幕或 shownotes。有文字就走 L0，不装 Whisper。

## 3. 能力矩阵

| 能力 | 默认入口 | 额外依赖 |
|---|---|---|
| 查库/回顾/lint/学习/灵感/地图/AIHOT | Node | 无 |
| GitHub | Node | 官方 `gh` CLI |
| 浏览器/知乎/小红书 | Node + Kimi WebBridge | Chrome 扩展连接 |
| YouTube 字幕 | Node | `yt-dlp` |
| 微信读书 | Node | API Key；macOS 可放 Keychain |
| B 站 | Python 保留后端 | `requirements/bilibili.txt` |
| 公众号/小宇宙 | Python 保留后端 | `requirements/base.txt` / `wechat.txt` |
| 文档解析 | Python 保留后端 | `requirements/doc.txt`，约 1GB |
| 本地 ASR | Python 保留后端 | `asr-mac.txt` 或 `asr-linux.txt` + ffmpeg；模型约 1.5GB |

## 4. Node 核心

在 skill 根目录执行：

```bash
npm install
npm run check
```

## 5. 仅在需要时创建 Python 后端

在 `skills/kg-wiki-skills` 目录：

```bash
uv python install 3.12
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements/<对应文件>
uv pip install -e ./kg-media-to-text
```

Windows 激活：

```powershell
.venv\Scripts\Activate.ps1
```

ASR 选型：

- Apple Silicon：`asr-mac.txt`（mlx-whisper / Metal）
- Linux、WSL2、Windows、Intel Mac：`asr-linux.txt`（faster-whisper）
- NVIDIA 加速需 CUDA 12 + cuDNN 9；无 GPU 可降级 CPU
- 内存小于 8GB 时优先 small/medium 模型

ffmpeg 是系统依赖，安装前先告知用户并确认：

```bash
brew install ffmpeg             # macOS
sudo apt install -y ffmpeg      # Linux / WSL2
winget install ffmpeg           # Windows
```

## 6. 浏览器

知乎、小红书和其他登录态页面统一看 `kg-browser/SKILL.md`，通过 Kimi WebBridge
操作真实 Chrome。不要安装 Playwright，也不要索要或导出 cookie。

## 7. 知识库路由

```bash
../bin/kg-node kg-vault/scripts/vault-cli.mjs list --json
../bin/kg-node kg-vault/scripts/vault-cli.mjs add /path/to/vault --name tech --desc "技术与工程实践"
```

多个库由 AI 读取 `path + desc` 后自动分类，并给业务脚本显式传 `--vault`。
没有标准库时先走 kg-init；不要为了消除多库报错而偷偷设第一个库为默认。

## 8. Skill 发现

把本 skill 目录软链到用户级 skills 目录，即可被 pi 发现：

```bash
mkdir -p ~/.agents/skills
ln -s "$PWD" ~/.agents/skills/kg-wiki-skills
```

创建前先检查目标是否存在，不覆盖已有目录。原生 Windows 用开发者模式或管理员
PowerShell 创建 SymbolicLink。

## 9. 验证

```bash
../bin/kg-node kg-install/scripts/doctor.mjs
../bin/kg-node kg-install/scripts/lint-docs.mjs
npm run check
```

装了哪种 Python 后端，就额外跑对应最小样本；不要只凭安装命令退出码说“完成”。

## 常见故障

| 症状 | 处理 |
|---|---|
| Node 版本过低 | 升级到 22.13+ |
| `ModuleNotFoundError` | 该流程确实需要 Python 时，用仓库 `.venv` 和 `../bin/kg-py`；Node 流程不要装 Python 修 |
| `ffmpeg not found` | 只在音视频转写时安装 ffmpeg |
| `libcudnn_ops.so` 缺失 | 补 cuDNN 9，或先用 CPU |
| 找不到知识库 | `kg-vault list --json`；路径失效才询问用户 |
| 多库未指定默认 | AI 按 desc 选择并传 `--vault`，不是让用户重复分类 |
| Kimi snapshot 无连接 | 让用户确认 Chrome 扩展连接，然后复用同一 session |

## 边界

- `doctor.mjs` 只诊断，不安装。
- 系统包、CUDA、cuDNN、浏览器扩展等外部变更要先说明影响。
- 不碰用户全局 Python；可选包只装在本仓库 `.venv`。
- 不默认安装 Docling 或 Whisper；体积和首次模型下载必须提前说明。
