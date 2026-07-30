---
name: kg-install
description: 装环境（对话式，按需裁剪）。先体检当前机器，再问用户要处理什么内容，只装他真正需要的那几样——而不是无脑装全套（文档解析约 1GB、Whisper 模型约 1.5GB）。装失败时能诊断具体原因并给出对策。当用户说「帮我装一下」「配置环境」「这些 skill 怎么用起来」「装到新电脑上」「xxx 报错说缺依赖」「ModuleNotFoundError」时使用。也用于事后排查「为什么这个 skill 跑不起来」。
---

# kg-install · 装环境

`install.sh` 是"闭眼装全套"，适合已经走通的标准路径。
**本 skill 是"问清楚再装"** —— 按机器实际情况和用户实际需求裁剪。

## 为什么要有这个（对话式安装的价值）

脚本的死穴：**它不知道用户要干什么**，只能按平台猜，于是装全套。
结果一个"只想存几篇公众号文章"的人，被装了 Docling（约 1GB）+ Whisper 模型（约 1.5GB）。

而且脚本失败只能 `exit 1` 或跳过，用户拿到一个残缺环境却不知道缺什么。
你（AI）能读报错、判断原因、给对策，这是脚本做不到的。

## 铁律

1. **先体检，再问需求，最后才装。** 不要跳过任何一步。
2. **不默认装全套。** 每一项重依赖装之前，说清它多大、用来干什么、不装会缺什么。
3. **装之前报备。** 要跑 `uv pip install` 或系统包管理器（brew/apt）前，
   先说要装什么、大概多大，让用户知情。
4. **失败不硬扛。** 装不上就诊断原因、给替代方案，不要反复重试同一条命令。

## 第 1 步：体检

```bash
cd kg-wiki-skills/kg-install
python3 scripts/doctor.py            # 人类可读
python3 scripts/doctor.py --json     # 结构化（你优先用这个）
```

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
cd kg-wiki-skills
uv python install 3.12          # 确保 3.12 可用
uv venv --python 3.12
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

### 本地转写的选型（按体检结果定）

| 机器 | 后端 | 速度参考 | 说明 |
|------|------|---------|------|
| Apple Silicon | `asr-mac.txt`（mlx-whisper） | 1 小时音频约 2-4 分钟 | 走 Metal GPU |
| Linux/WSL2 + NVIDIA | `asr-linux.txt`（faster-whisper） | 1 小时约 2-5 分钟 | **需 CUDA 12 + cuDNN 9** |
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

```bash
mkdir -p ~/.agents/skills
ln -s "$(pwd)" ~/.agents/skills/kg
```

Claude Code 用 `~/.claude/skills/`。**建软链前先看目标是否已存在**，别覆盖别人的东西。

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

## 与 install.sh 的分工

```
install.sh          闭眼装全套，走通的标准路径，一条命令，幂等
                    → 适合：自己迁移新机器、CI、已知环境干净

kg-install（本 skill）  问清楚再装，按需裁剪，能诊断
                    → 适合：新用户首次装、环境不标准、脚本挂了、
                            只想装一部分、事后排查跑不起来
```

两者不冲突。脚本装完也可以用本 skill 的 `doctor.py` 体检。

## 边界

- **`doctor.py` 只诊断，不安装。** 安装决策依赖用户需求，那是对话里才能问清的。
- 装系统级东西（ffmpeg、CUDA、cuDNN）**必须先问用户** —— 那超出了本仓库的范围。
- 不碰用户已有的 Python 环境，一切装在本仓库的 `.venv` 里。
- 不自动建软链覆盖已存在的路径。
- 云端 ASR 暂未支持（当前只有本地 Whisper）。

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
