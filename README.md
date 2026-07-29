# kg-wiki-skills

一套 AI Agent skill 集合，把散落在各处的内容——B站视频、播客、公众号文章、知乎、YouTube、
本地文档——**变成一个可检索、可唤醒、能长期复利的个人知识库**。

遵循 Andrej Karpathy 的 **LLM Wiki** 模式：**唤醒**（知道某个知识点存在，能判断 AI 的回答）
+ **沉淀**（只存 AI 给不出的东西：个人判断、项目上下文、踩过的坑）。

> `kg` 取自作者 ID（KingGloose），`wiki` 指知识库，`skills` 即 Agent skill。

---

## 为什么做这个

AI 时代，个人笔记的价值变了。

以前记笔记是为了"以后能查到"。现在通用知识问 AI 就有，**再抄一遍文档没有意义**。
真正值钱的只剩三类：

- **你踩过的坑** —— 花几小时定位、网上没标准答案的那种
- **有上下文的决策** —— 这个项目为什么选 A 不选 B，当时的约束是什么
- **你的判断** —— 读完一篇文章后，你认同哪部分、怀疑哪部分

而这三类东西的共同点是：**必须由你自己产生，AI 给不出来**。

所以这套 skills 的设计原则是：
1. **摄入要省力** —— 视频/播客/文章自动转文字，你不用手抄
2. **沉淀要审慎** —— AI 能答的只在索引里留个关键词（唤醒），不写详细页
3. **来源要分明** —— 严格区分「你记过的」和「AI 补充的」，绝不混淆
4. **知识要被用** —— 提供检索、回顾、体检，防止库变成死档案

---

## 能力概览

### 摄入（多源 → 文字 → 沉淀）

| skill | 能力 |
|-------|------|
| `kg-bilibili` | B 站：稍后再看 / 收藏夹 / 全站搜索 / CC/AI 字幕 / 无字幕时本地 ASR 兜底 |
| `kg-youtube` | YouTube：官方与自动字幕（覆盖率高，多数视频零算力）+ ASR 兜底 |
| `kg-xiaoyuzhou` | 小宇宙播客：元信息 + shownotes（常含时间戳大纲）+ 可选本地转写 |
| `kg-wechat` | 微信公众号文章（含图片防盗链处理） |
| `kg-zhihu` | 知乎专栏 / 回答 / 问题页（走真实浏览器，绕过 JS 挑战） |
| `kg-doc` | 本地文档：PDF / Word / PPT / Excel / txt / md，支持文件夹批量与网页 URL |

### 前置：知识库在哪

| skill | 能力 |
|-------|------|
| `kg-vault` | **知识库注册与切换**。`init` 从模板建新库 / `add` 注册已有库 / `use` 切换默认 / `which` 查当前用哪个。多库无默认时会要求询问用户而非瞎猜 |

### 底层能力（被上层调用）

| skill | 能力 |
|-------|------|
| `kg-media-to-text` | **任意素材 → 文字**。按类型分流：PDF→Docling（含 OCR）、Office→MarkItDown、音视频→Whisper |
| `kg-browser` | 通过 **用户真实 Chrome** 读取需登录态/有反爬的页面；另含本地历史与书签模糊查找 |

### 捕获与学习

| skill | 能力 |
|-------|------|
| `kg-capture` | **跨项目知识捕获**：在别的项目里排查问题、做技术决策时，识别值得沉淀的内容并回填 |
| `kg-learn` | **学习模式**：陌生领域渐进切入（地图式 / 苏格拉底 / 问题驱动 / 费曼），可选学习计划 |

### 使用与维护

| skill | 能力 |
|-------|------|
| `kg-ask` | **库内检索问答**。索引全库文本，毫秒级查询，严格区分"库里记过的"vs"AI 补充的" |
| `kg-review` | **知识回顾**：先回想再看答案，并确认页里的个人判断是否还认同 |
| `kg-lint` | **库健康体检**：孤儿页、死链、raw 未沉淀、index 缺唤醒条目 |

---

## 分层摄入原则

多模态资料统一走 **多模态 → 文字 → 沉淀**。文字是唯一能被搜索、被双链、被反复检索的形态。

```
L0  白拿现成文字   平台已有的字幕 / 文章正文 / shownotes / PDF 文字层
    （零成本，最优先——等于白嫖平台已经做完的 ASR）
L1  本地转换       无字幕音视频 → 本地 ASR；扫描件 → OCR
    （一次投入，永久复用，边际成本≈0）
L2  多模态补充     仅对"文字丢了关键信息"的局部（关键帧、公式页）
```

**为什么不用原生多模态当主线**：每次理解都重新付费、结果不落文字等于没沉淀。
本地转文字是一次投入、永久复利——对"沉淀后反复查"的知识库，这是数量级的差距。

---

## 架构：底层能力 + 上层业务

```
底层（被代码调用，平台无关，不懂业务）
  kg-media-to-text/    素材 → 文字，按类型分流
  kg-browser/          真实浏览器读取（登录态、JS 挑战）

上层（各自独立触发，按知识库契约沉淀）
  kg-bilibili/  kg-youtube/  kg-xiaoyuzhou/  kg-wechat/  kg-zhihu/  kg-doc/
```

**转换能力沉到底层复用，沉淀规则永远归上层。** 上层通过
`from media_to_text import to_text` 调用底层，不关心内部用了 Docling 还是 Whisper。

---

## 安装

### 前置

- **Python 3.12+**（脚本用了新语法）
- **[uv](https://docs.astral.sh/uv/)**：`curl -LsSf https://astral.sh/uv/install.sh | sh`
- **ffmpeg**（音视频转写需要）：macOS `brew install ffmpeg` / Ubuntu `sudo apt install ffmpeg`
- Node.js（仅 `kg-browser` 需要）：`npm i -g chrome-devtools-mcp@latest`

### 一键安装

```bash
git clone https://github.com/KingGloose/kg-wiki-skills.git
cd kg-wiki-skills
bash install.sh
```

脚本会：探测平台（macOS / Linux / WSL2）→ 建 Python 3.12 venv →
**按平台自动选 ASR 后端**（macOS 用 mlx-whisper 走 Metal，Linux 用 faster-whisper 走 CUDA）→
装底层库 → 软链注册到 `~/.agents/skills/kg` → 自检。幂等，可重复运行。

```bash
bash install.sh --minimal   # 跳过 Docling(~1GB) 和 Whisper 模型(~1.5GB)
bash install.sh --no-link   # 不注册到全局
```

### 指定你的知识库

**最简单的方式**：用 `kg-vault` 管理（它会写好配置）

```bash
cd kg-vault && source ../.venv/bin/activate

python scripts/vault_cli.py init ~/my-vault      # 没有库？从模板建一个
python scripts/vault_cli.py add /path/to/vault   # 已有库？注册进来
python scripts/vault_cli.py which                # 确认当前用哪个
```

底层的**四级解析**（所有 skill 通用，前面命中就不往下找）：

```bash
# 1. 命令行显式指定（临时覆盖，优先级最高）
python scripts/xxx.py --vault /path/to/vault

# 2. 环境变量
export KG_VAULT=/path/to/your-vault

# 3. 配置文件 ~/.config/kg-wiki/config.json
{"vault": "/path/to/your-vault"}

# 4. 在知识库目录内执行（自动向上查找含 AGENTS.md + wiki/ 的目录）
```

**多个知识库**（如工作/个人分开）用这个格式：

```json
{
  "default": "personal",
  "vaults": {
    "personal": "/path/to/personal-vault",
    "work": "/path/to/work-vault"
  }
}
```

切换用 `--vault /path/to/work-vault`，或改 `default`。

> **找不到知识库时**，脚本不会瞎猜路径，而是提示 AI **直接问用户**，
> 拿到路径后可一行写进配置：
> ```bash
> python -c "from media_to_text import save_config; save_config('/path/to/vault')"
> ```

### 不需要放进知识库

工具**不必**软链或复制到知识库目录里。安装脚本已把本仓库注册到 `~/.agents/skills/`，
AI 在任何工作目录都能发现并调用；库的位置靠上面的解析机制确定。
**知识库保持纯粹——只放知识。**

**知识库的最小结构**（需要 `AGENTS.md` 和 `wiki/` 才能被识别）：

```
your-vault/
├── AGENTS.md    维护契约（见 templates/AGENTS.md 模板）
├── index.md     知识点唤醒索引
├── log.md       流水账
├── wiki/        沉淀的知识，按领域分子目录
├── raw/         原始资料留档
├── assets/      图片
└── learning/    学习计划（kg-learn 自动创建）
```

没有现成的库？复制 `templates/` 里的模板开始：

```bash
mkdir -p ~/my-vault/{wiki,raw,assets}
cp templates/AGENTS.md templates/index.md templates/log.md ~/my-vault/
export KG_VAULT=~/my-vault
```

---

## 平台差异（重要）

**ASR 后端必须按平台选，这是硬约束：**

| 平台 | 后端 | 原因 |
|------|------|------|
| macOS (Apple Silicon) | `mlx-whisper` | 走 Apple MLX + Metal GPU |
| Linux / WSL2 | `faster-whisper` | 走 CUDA（无 GPU 自动降级 CPU） |

**faster-whisper 不支持 Apple MPS**，在 Mac 上只能 CPU 干跑。所以两个平台用不同后端，
`kg-media-to-text` 内部会**自动检测平台选择**，上层代码无需关心。

`kg-browser` 在 WSL2 下访问 Windows 侧 Chrome 需要额外配置（见其
`references/troubleshooting.md`），配不通有手动降级方案。

---

## 依赖矩阵（按需安装）

| skill | 需要 |
|-------|------|
| `kg-media-to-text`（文档） | `base` + `doc` |
| `kg-media-to-text`（转写） | `base` + `asr-mac` 或 `asr-linux` + ffmpeg |
| `kg-bilibili` | `base` + `bilibili`（`--asr` 还需 asr-* + ffmpeg） |
| `kg-youtube` | `base` + `asr-*`（为其中的 yt-dlp） |
| `kg-xiaoyuzhou` | `base`（仅 shownotes）；`--transcribe` 还需 asr-* |
| `kg-wechat` | `base` + `wechat` |
| `kg-zhihu` | `base` + `wechat`；浏览器能力依赖 `kg-browser` |
| `kg-doc` | `base` + `doc` |
| `kg-browser` | 无 Python 依赖；需 `chrome-devtools-mcp` CLI |
| `kg-vault` / `kg-ask` / `kg-lint` / `kg-review` / `kg-learn` / `kg-capture` | 无额外依赖（纯标准库） |

---

## 用法示例

```bash
cd kg-wiki-skills && source .venv/bin/activate

# 首次：告诉它你的库在哪
cd kg-vault && python scripts/vault_cli.py add /path/to/your-vault

# 摄入
cd kg-doc      && python scripts/ingest_doc.py ~/Downloads/paper.pdf
cd kg-doc      && python scripts/ingest_doc.py ~/papers --batch
cd kg-youtube  && python scripts/ingest_video.py "https://youtube.com/watch?v=xxx"
cd kg-bilibili && python scripts/search_videos.py "Rust 异步" --order click --min-min 8

# 使用
cd kg-ask    && python scripts/search_vault.py "泛域名 证书"
cd kg-review && python scripts/pick_review.py --count 3
cd kg-lint   && python scripts/lint_vault.py
```

多数 skill 的实际使用是**对话式的**——直接对 AI 说「解析这个视频 <链接>」
「这个 PDF 存进知识库」「回顾一下」即可，AI 会读对应 SKILL.md 并执行。

---

## 设计取舍（做了什么、没做什么）

**刻意没做的：**

- **自动/定时批量摄入** —— 违背"一切按需"。价值在你和 AI 讨论的过程，不在攒素材
- **说话人分离（diarization）** —— 需引入 gated model 与额外配置，多人对谈时逐字稿
  不标注发言人，但 SKILL.md 明确要求 AI **不确定就说不确定，不编造发言归属**
- **原生多模态当主线** —— 每次付费无复利，见「分层摄入原则」
- **小红书摄入** —— 签名逆向 + 频繁失效 + 账号风险，且笔记短图多，性价比低

**刻意做了的：**

- **真实浏览器而非无头浏览器** —— 天然有登录态、天然过 JS 挑战、零反爬对抗
- **平台自适应 ASR** —— 而非强求一个后端跑遍所有平台
- **只读用户已能看到的内容** —— 不注入 cookie、不绕权限、不批量爬取

---

## 兼容性

- 在 **Claude Code / pi** 等支持 Agent Skills（`SKILL.md` + frontmatter）的环境下开箱可用
- skill 发现：把本仓库软链或复制到 `~/.agents/skills/`，含 `SKILL.md` 的目录会被递归发现
- 脚本本身是普通 Python CLI，也可脱离 Agent 直接调用

## 许可

MIT

## 致谢

- **Andrej Karpathy** 的 LLM Wiki 概念——本项目的方法论源头
- [Docling](https://github.com/docling-project/docling)（IBM）、
  [MarkItDown](https://github.com/microsoft/markitdown)（Microsoft）、
  [mlx-whisper](https://github.com/ml-explore/mlx-examples)、
  [faster-whisper](https://github.com/SYSTRAN/faster-whisper)、
  [yt-dlp](https://github.com/yt-dlp/yt-dlp)、
  [bilibili-api](https://github.com/Nemo2011/bilibili-api)
  —— 脏活都是这些库干的，本项目只做调度与沉淀
