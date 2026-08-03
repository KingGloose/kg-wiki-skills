---
name: kg-install
description: 装环境（对话式，按需裁剪，覆盖 macOS / Linux / WSL2 / 原生 Windows）。先体检当前机器，再问用户要处理什么内容，只装他真正需要的那几样——而不是无脑装全套（文档解析约 1GB、Whisper 模型约 1.5GB）。装失败时能诊断具体原因并给出对策。当用户说「帮我装一下」「配置环境」「这些 skill 怎么用起来」「装到新电脑上」「xxx 报错说缺依赖」「ModuleNotFoundError」时使用。也用于事后排查「为什么这个 skill 跑不起来」。
---

# kg-install · 装环境

**这是本仓库唯一的安装入口。** 没有一键脚本 —— 因为安装脚本要穷举
「4 个平台 × 有无 GPU × 用户要装哪几样能力」的组合，分支爆炸且失败只能 `exit`。

你（AI）能读环境、读报错、判断原因、给对策。这是脚本做不到的，也是这里不用脚本的原因。

## 为什么不用一键脚本

- **脚本不知道用户要干什么**，只能按平台猜，于是装全套。
  一个"只想存几篇公众号文章"的人，被装 Docling（约 1GB）+ Whisper 模型（约 1.5GB）。
- **脚本失败只能 exit 或跳过**，用户拿到残缺环境却不知缺什么、怎么补。
- **平台组合太多**：macOS(ARM/Intel) × Linux × WSL2 × 原生 Windows，
  各自的包管理器、venv 激活方式、GPU 方案、ASR 后端都不同。

## 铁律

1. **先体检，再问需求，最后才装。** 不要跳过任何一步。
2. **不默认装全套。** 每一项重依赖装之前，说清它多大、用来干什么、不装会缺什么。
3. **装之前报备。** 要跑 `uv pip install` 或系统包管理器（brew/apt）前，
   先说要装什么、大概多大，让用户知情。
4. **失败不硬扛。** 装不上就诊断原因、给替代方案，不要反复重试同一条命令。

## 四个平台的差异（照这个给命令）

| | macOS | Linux | WSL2 | 原生 Windows |
|---|---|---|---|---|
| 系统包管理器 | `brew` | `apt` | `apt` | `winget` / `scoop` |
| venv 激活 | `source .venv/bin/activate` | 同左 | 同左 | PowerShell: `.venv\Scripts\Activate.ps1`<br>CMD: `.venv\Scripts\activate.bat` |
| ASR 后端 | ARM: mlx-whisper(Metal)<br>Intel: faster-whisper(CPU) | faster-whisper | faster-whisper | faster-whisper |
| GPU 加速 | Apple Metal（ARM 自带） | NVIDIA + CUDA12/cuDNN9 | 同左（走 WSL GPU 直通） | 同左（驱动装在 Windows 侧） |
| ffmpeg | `brew install ffmpeg` | `sudo apt install -y ffmpeg` | 同左 | `winget install ffmpeg` |
| 已知坑 | Intel Mac 无 GPU 加速，慢 | cuDNN 版本不符最常见 | GPU 直通需较新驱动 | Docling 偶有编译问题；<br>CUDA 配置比 WSL2 麻烦 |

**原生 Windows 的建议**：能用 WSL2 就用 WSL2 —— 依赖生态更顺，
GPU 直通也能用。但如果用户明确要原生 Windows，上表够你走通（除 mlx 之外都支持）。

## 第 1 步：体检

```bash
cd <clone 下来的 kg-wiki-skills>/kg-install
python3 scripts/doctor.py            # 人类可读
python3 scripts/doctor.py --json     # 结构化（你优先用这个）
```

> 装环境阶段还没注册全局软链，所以这里用 clone 路径。
> 其他 skill 的文档用**相对 SKILL.md 的路径**（`../.venv/bin/activate`），
> 不依赖软链名 —— 你（AI）按已知规则把相对路径解析成绝对路径即可。

注意用 `python3` 而不是 venv 里的 python —— **体检时 venv 可能还不存在**。
脚本纯标准库，零依赖。

它报告：平台/内存/GPU、工具链（uv/ffmpeg/git）、venv 与**按能力分组**的已装情况、
知识库定位、全局注册、**阻塞项**（必须先解决）、**提示**（可选优化）。

退出码：`0` = 无阻塞，`1` = 有阻塞项。

**先解决 blockers**（通常是 uv 没装），再往下走。

## 第 2 步：问用户要处理什么内容

这一步决定装什么。**别跳过，也别替用户猜。**

> 你平时想往知识库里存什么内容？（可多选）
>
> 1. 网页文章、公众号、知乎
> 2. B 站 / YouTube 视频
> 3. 播客（小宇宙）
> 4. 本地文档（PDF / Word / PPT / Excel）
> 5. 就想写笔记、查库、复习，不摄入外部内容

对选了 2/3 的追问一句关键的：

> 视频/播客**有字幕或 shownotes 吗**？
> · 有 → 直接白拿文字，零算力成本，不用装转写
> · 没有 / 不确定 → 需要本地转写（要下约 1.5GB 模型）

这个追问很值得 —— B 站大部分热门视频有 CC 或 AI 字幕，YouTube 自动字幕覆盖 157 种语言。
**很多人其实不需要装 ASR。**

## 第 3 步：按需求装

### 能力矩阵（照这个裁剪）

| 用户要什么 | 装什么 | 体积 | 备注 |
|-----------|--------|------|------|
| **任何情况（必装）** | `requirements/base.txt` + `-e ./kg-media-to-text` | ~15MB | HTTP/HTML 解析 + 底层库 |
| 网页 / 知乎 | 已含在 base | 0 | 知乎另需真实 Chrome（见下） |
| 公众号 | `requirements/wechat.txt` | ~2MB | markdownify |
| B 站 | `requirements/bilibili.txt` | ~10MB | 需 `curl_cffi`（base 已含） |
| YouTube / 播客（有字幕） | `yt-dlp`（在 asr-*.txt 里，可单独装） | ~5MB | 只下字幕不转写 |
| **音视频转写** | `requirements/asr-mac.txt` 或 `asr-linux.txt` | 包 ~200MB<br>**模型 ~1.5GB** | 见下方选型 |
| **本地文档** | `requirements/doc.txt` | **~1GB**<br>+ 首次跑下模型 | Docling + MarkItDown |
| 只写/查/复习 | 只装必装项 | ~15MB | kg-ask/review/lint/learn 纯标准库 |

命令模板（在仓库根，`.venv` 已激活）：

```bash
uv pip install -r requirements/<对应文件>
uv pip install -e ./kg-media-to-text     # 底层库，editable
```

### 环境创建（venv 不存在时）

```bash
cd <clone 下来的仓库根>          # 首次安装时用户就在这里，没有软链可依赖
uv python install 3.12          # 确保 3.12 可用
uv venv --python 3.12
```

激活（按平台选，体检报告的 `activate_cmd` 字段直接给了）：

```bash
source .venv/bin/activate              # macOS / Linux / WSL2
.venv\Scripts\Activate.ps1             # Windows PowerShell
.venv\Scripts\activate.bat             # Windows CMD
```

### 本地转写的选型（按体检结果定）

| 机器 | 后端 | 速度参考 | 说明 |
|------|------|---------|------|
| Apple Silicon | `asr-mac.txt`（mlx-whisper） | 1 小时音频约 2-4 分钟 | 走 Metal GPU |
| Linux/WSL2 + NVIDIA | `asr-linux.txt`（faster-whisper） | 1 小时约 2-5 分钟 | **需 CUDA 12 + cuDNN 9** |
| 原生 Windows + NVIDIA | `asr-linux.txt`（faster-whisper） | 1 小时约 2-5 分钟 | 驱动装 Windows 侧；<br>配 CUDA 比 WSL2 麻烦 |
| Intel Mac / 无 GPU | `asr-linux.txt`（CPU 模式） | 1 小时约 20-40 分钟 | 慢但能用 |
| 内存 < 8GB | 同上，但**换小模型** | —— | large-v3 吃紧，建议 small/medium |

选型要**如实告知代价**：模型约 1.5GB 存 `~/.cache`，首次转写会先下载。
如果用户的内容大多有字幕，直接建议**先不装**，需要时再回来。

### ffmpeg（音视频必需，不是 Python 包）

```bash
brew install ffmpeg          # macOS
sudo apt install -y ffmpeg   # Linux / WSL2
```

装它要用系统包管理器，**动手前先问用户**。

### 知乎的特殊依赖

`kg-zhihu` 不装 Python 包，它要**真实的 Chrome + chrome-devtools CLI**（走 `kg-browser`）。
如果用户要存知乎，提醒这一点，具体见 `kg-browser/SKILL.md`。

## 第 4 步：定位知识库（最容易漏，漏了等于没装）

装完包不等于能用 —— skills 还不知道往哪写。看体检的"知识库定位"：

- **已有标准结构的库** → `kg-vault`：`python kg-vault/scripts/vault_cli.py add <路径>`
- **有一堆旧笔记要改造** → `kg-init`（会先出计划让用户确认，别跳过那步）
- **完全从零** → `kg-init` 在空目录上 apply

## 第 5 步：注册到全局（可选但强烈建议）

不注册的话，AI 只能在本仓库目录内发现这些 skill。

macOS / Linux / WSL2：

```bash
mkdir -p ~/.agents/skills
ln -s "$(pwd)" ~/.agents/skills/kg-wiki-skills
```

**软链名建议用 `kg-wiki-skills`**（与仓库同名，最少困惑）。
各 skill 文档已改用相对路径，所以名字不一致也能工作 —— 但保持一致省心。

> 踩过的坑：软链曾叫 `kg`，而文档写死 `cd kg-wiki-skills`，
> AI 照抄失败后误诊成"环境没装"，准备重装一遍。
> 教训是**文档不该写死依赖外部命名的路径** —— 现已全部改为相对路径。

原生 Windows（PowerShell，**需管理员权限或开启开发者模式**）：

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills"
New-Item -ItemType SymbolicLink -Path "$HOME\.agents\skills\kg-wiki-skills" -Target (Get-Location)
```

> 建不了软链的话，直接复制目录也行（缺点：改代码要重新复制）。

Claude Code 用 `~/.claude/skills/`。**建软链前先看目标是否已存在**，别覆盖别人的东西。

## 文档自检（维护者用）

改过任何 SKILL.md 后跑一下，防止写出 AI 解析不了的路径：

```bash
python3 scripts/lint_docs.py          # 退出码 0=干净，1=有错
```

查五类问题：写死仓库名（`cd kg-wiki-skills`）、未定义变量（`$KG`）、
写死用户目录（`/Users/xxx/`）、依赖软链名（`~/.agents/skills/kg/`）、
假设 skill 位于知识库内的相对输出路径（如 `../../raw/`）。

**为什么要有这个**：曾经文档写死 `cd kg-wiki-skills`，
但软链叫 `kg`、AI 的工作目录又是用户项目，于是 cd 失败，
AI 误诊成"环境没装"准备重装。规范做法是用相对 SKILL.md 的路径，
AI 按已知规则解析成绝对路径 —— 不依赖任何外部命名。

## 第 6 步：验证

```bash
python scripts/doctor.py                     # 再体检一次，该绿的绿了吗
cd /tmp && pi --print "列出名字以 kg- 开头的 skill"   # 全局能发现吗
```

装了什么就验什么，别泛泛说"装好了"。

## 常见故障与对策

| 症状 | 原因 | 对策 |
|------|------|------|
| `uv: command not found` | 没装或没重开终端 | `curl -LsSf https://astral.sh/uv/install.sh \| sh`，然后**重开终端** |
| `ModuleNotFoundError: media_to_text` | 底层库没装或没激活 venv | 先 `source .venv/bin/activate`，再 `uv pip install -e ./kg-media-to-text` |
| `Could not load library libcudnn_ops.so` | CUDA 有但 cuDNN 缺/版本不符 | 装 cuDNN 9；或先降级 CPU 跑通再说 |
| mlx-whisper 在 Intel Mac 装不上 | mlx 只支持 Apple Silicon | 改用 `asr-linux.txt`（CPU 模式） |
| `ffmpeg not found`（转写时） | ffmpeg 没装 | 见上方 ffmpeg 一节 |
| Docling 首次跑很久 | 在下版面/OCR 模型（数百 MB） | 正常，等它下完；之后走缓存 |
| `找不到知识库` | 没配置库位置 | 走第 4 步 |
| skill 在别的目录唤不起来 | 没注册全局 | 走第 5 步 |
| 装依赖时网络超时 | 源慢 | 换国内镜像：`uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple ...` |
| Windows 上 `无法加载文件 Activate.ps1` | PowerShell 执行策略 | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`，或改用 CMD 的 `.bat` |
| Windows 上建软链失败 | 权限不足 | 用管理员 PowerShell，或开启「开发者模式」，或直接复制目录 |
| Windows 上 Docling 装不上 | 依赖需编译 | 装 VS Build Tools，或改用 WSL2，或先跳过文档能力 |
| 中文路径/文件名报错 | 编码问题 | 确认终端用 UTF-8（`chcp 65001`）；脚本内部读写已统一 utf-8 |

## 边界

- **`doctor.py` 只诊断，不安装。** 安装决策依赖用户需求，那是对话里才能问清的。
- 装系统级东西（ffmpeg、CUDA、cuDNN）**必须先问用户** —— 那超出了本仓库的范围。
- 不碰用户已有的 Python 环境，一切装在本仓库的 `.venv` 里。
- 不自动建软链覆盖已存在的路径。
- 云端 ASR 暂未支持（当前只有本地 Whisper）。
- **纯 Windows 的 mlx-whisper 不可用**（mlx 只支持 Apple Silicon），会自动落到 faster-whisper。
- 本仓库**没有一键安装脚本**，安装靠你按本文档判断。

## 已验证

- `doctor.py` 在真实环境（macOS Apple Silicon / 16GB / 10 核）体检：
  平台、内存、GPU（apple-metal）、工具链版本、7 项能力全 ready、
  库根定位、全局软链，均正确。
- 模拟全新克隆环境（无 venv、PATH 剥离到只有 /usr/bin:/bin、无 KG_VAULT）：
  正确报出阻塞项（uv 未安装 + 装法 + 提醒重开终端）、
  正确区分"阻塞项"与"提示"（ffmpeg 缺失只是提示，因为非必需）、
  正确识别 venv 未创建、未注册全局。
- `--json` 输出结构完整（platform/gpu/tools/venv.capabilities/vault/registration/
  blockers/notes），可直接被 AI 解析用于决策。
- 模拟 Windows 平台（mock platform.system）：正确识别为 supported、
  包管理器给 winget、激活命令给 `.venv\Scripts\Activate.ps1`、
  ffmpeg 装法给 winget、并追加两条 Windows 专属提示（ASR 后端 / Docling 编译）。
