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
| `kg-ingest` | **内容摄入统一入口**：B站 / YouTube / 知乎 / 小红书 / 公众号 / 小宇宙 / GitHub / 微信读书。SKILL.md 只做路由，细节在 `references/<平台>/index.md` 按需披露 |
| `kg-doc` | 本地文档：PDF / Word / PPT / Excel / txt / md，支持文件夹批量与网页 URL |

### 前置：装环境、知识库在哪

| skill | 能力 |
|-------|------|
| `kg-install` | **装环境（对话式）**。先体检机器 → 问你要处理什么内容 → 只装真正需要的（省几个 GB），装失败还能诊断。覆盖 macOS/Linux/WSL2/Windows |
| `kg-init` | **建库 / 改造现有笔记**。已有一堆散乱笔记？先体检 → 出改造计划并解释理由 → 用户确认后执行「整体归档 + 向前新建」。持有 `templates/`。不改内容、不删文件、可回滚 |
| `kg-vault` | **路径管理**。`add` 注册 / `use` 切换默认 / `which` 查当前用哪个 / `doctor` 体检配置。只管"库在哪"，不建库 |

### 底层能力（被上层调用）

| skill | 能力 |
|-------|------|
| `kg-media-to-text` | **任意素材 → 文字**。按类型分流：PDF→Docling（含 OCR）、Office→MarkItDown、音视频→Whisper |
| `kg-browser` | 通过 **Kimi WebBridge + 用户真实 Chrome** 读取需登录态/有反爬的页面；另含本地历史与书签模糊查找 |

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
| `kg-travel` | **地图与出行**：百度地图 API——地理编码 / 地点检索 / 周边美食 / 公交驾车路线规划 |

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
  kg-ingest/    kg-doc/
```

**转换能力沉到底层复用，沉淀规则永远归上层。** Node 入口负责通用编排；
只有文档/ASR 通过 `media_to_text` Python 后端处理，上层不关心内部用了 Docling 还是 Whisper。

---

## 安装

### 前置

- **Node.js 22.13+**（默认运行时）
- **Python 3.12+ / [uv](https://docs.astral.sh/uv/)**（仅 B 站、公众号、小宇宙、文档和 ASR 后端需要）
- **ffmpeg**（仅音视频转写需要）：`brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install ffmpeg`
- **Kimi WebBridge**（仅真实浏览器读取需要）：[WebBridge 帮助](https://www.kimi.com/zh-cn/features/webbridge)

其余依赖由 `kg-install` 按需安装，不用手动装。

### 让 AI 装

```bash
git clone https://github.com/KingGloose/kg-wiki-skills.git
cd kg-wiki-skills
```

然后对你的 AI agent 说「**帮我装一下**」，它会唤起 `kg-install`：

1. **体检**这台机器（平台 / 内存 / GPU / 已有工具 / 已装了什么）
2. **问你要处理什么内容**（文章 / 视频 / 播客 / 文档 / 只写笔记）
3. **只装你需要的那几样**

**没有一键脚本，这是故意的。** 安装脚本要穷举「4 个平台 × 有无 GPU ×
用户要哪几样能力」的组合，分支爆炸，而且失败只能 `exit`。
AI 能读环境、读报错、判断原因、给对策——这是脚本做不到的。

省的空间也不少：全套装下来 Docling 约 1GB + Whisper 模型约 1.5GB，
但只想存公众号文章的话 **15MB 就够**。视频/播客多数有现成字幕，
可以完全跳过转写依赖。

想自己先看看环境状况（Node 标准库，无需 Python）：

```bash
./bin/kg-node kg-install/scripts/doctor.mjs           # 人类可读
./bin/kg-node kg-install/scripts/doctor.mjs --json    # 结构化
```

### 平台支持

| | macOS | Linux | WSL2 | 原生 Windows |
|---|---|---|---|---|
| 状态 | ✅ | ✅ | ✅ | ✅ |
| venv 激活 | `source .venv/bin/activate` | 同左 | 同左 | `.venv\Scripts\Activate.ps1` |
| ASR 后端 | ARM: mlx-whisper（Metal GPU）<br>Intel: faster-whisper（CPU） | faster-whisper | faster-whisper | faster-whisper |
| 系统包管理器 | `brew` | `apt` | `apt` | `winget` / `scoop` |

原生 Windows 能跑，但**推荐 WSL2**——依赖生态更顺，GPU 直通也能用，
CUDA/cuDNN 配置比原生省事。

### 指定你的知识库

**已经有一堆笔记？** 先用 `kg-init` 归一化（会先给你看计划再动手）：

```bash
./bin/kg-node kg-init/scripts/analyze-notes.mjs ~/my-notes      # 1. 体检
./bin/kg-node kg-init/scripts/migrate.mjs plan ~/my-notes       # 2. 看计划（只读）
./bin/kg-node kg-init/scripts/migrate.mjs apply ~/my-notes --confirm   # 3. 确认后执行
```

**从零开始**：先用 `kg-init` 建结构；**已有标准结构**：直接用 `kg-vault` 注册。

```bash
./bin/kg-node kg-init/scripts/migrate.mjs apply ~/my-vault --confirm
./bin/kg-node kg-vault/scripts/vault-cli.mjs add ~/my-vault
./bin/kg-node kg-vault/scripts/vault-cli.mjs which
```

底层的**四级解析**（所有 skill 通用，前面命中就不往下找）：

```bash
# 1. 命令行显式指定（临时覆盖，优先级最高）
./bin/kg-node kg-ask/scripts/search-vault.mjs "关键词" --vault /path/to/vault

# 2. 环境变量
export KG_VAULT=/path/to/your-vault

# 3. 配置文件 ~/.kg-agent-config/config.json
{"version": 1, "vault": {"default": "personal", "paths": {"personal": "/path/to/your-vault"}}}

# 4. 在知识库目录内执行（自动向上查找含 AGENTS.md + wiki/ 的目录）
```

**多个知识库**（如工作/个人分开）用这个格式：

```json
{
  "version": 1,
  "vault": {
    "default": "personal",
    "paths": {
      "personal": "/path/to/personal-vault",
      "work": "/path/to/work-vault"
    }
  }
}
```

业务调用用 `--vault /path/to/work-vault` 显式指定。
`add` 只注册路径，不替用户选择默认库；多库时 AI 读取各库 `desc` 自动分类，
不会静默选择第一个，也不会把分类工作重新丢给用户。

> **完全没配置或路径都失效时**，脚本不会瞎猜路径，而是提示 AI **直接问用户**，
> 拿到路径后用 `kg-vault` 注册：
> ```bash
> ./bin/kg-node kg-vault/scripts/vault-cli.mjs add /path/to/vault --desc "这个库的用途"
> ```

### 不需要放进知识库

工具**不必**软链或复制到知识库目录里。Piko 项目把它注册到自身 `.agents/skills/` 即可，
AI 在任何工作目录都能发现并调用；库的位置靠上面的解析机制确定。
**知识库保持纯粹——只放知识。**

**知识库的最小结构**（需要 `AGENTS.md` 和 `wiki/` 才能被识别）：

```
your-vault/
├── AGENTS.md    维护契约（kg-init 从模板生成）
├── index.md     知识点唤醒索引
├── log.md       流水账
├── wiki/        沉淀的知识，按领域分子目录
├── raw/         原始资料留档
├── assets/      图片
└── learning/    学习计划（kg-learn 自动创建）
```

没有现成的库？用 `kg-init` 建（空目录也行）：

```bash
./bin/kg-node kg-init/scripts/migrate.mjs apply ~/my-vault --confirm
./bin/kg-node kg-vault/scripts/vault-cli.mjs add ~/my-vault    # 再注册
```

模板在 `kg-init/templates/`（`AGENTS.md` / `index.md` / `log.md`），
建库后**按自己习惯改 `AGENTS.md`** —— 尤其「写作约定」和「领域划分」。

---

## 平台差异（重要）

**ASR 后端必须按平台选，这是硬约束：**

| 平台 | 后端 | 原因 |
|------|------|------|
| macOS (Apple Silicon) | `mlx-whisper` | 走 Apple MLX + Metal GPU |
| Linux / WSL2 | `faster-whisper` | 走 CUDA（无 GPU 自动降级 CPU） |

**faster-whisper 不支持 Apple MPS**，在 Mac 上只能 CPU 干跑。所以两个平台用不同后端，
`kg-media-to-text` 内部会**自动检测平台选择**，上层代码无需关心。

`kg-browser` 通过 Kimi WebBridge 连接用户真实 Chrome；WSL2 与 Windows 分开运行时，
按 `kg-browser/references/troubleshooting.md` 检查守护进程和扩展连接。

---

## 依赖矩阵（按需安装）

| skill | 需要 |
|-------|------|
| `kg-media-to-text`（文档） | `base` + `doc` |
| `kg-media-to-text`（转写） | `base` + `asr-mac` 或 `asr-linux` + ffmpeg |
| `kg-doc` | `base` + `doc` |
| `kg-browser` | Node.js + Kimi WebBridge；无 Python 依赖 |
| `kg-travel` | 无额外依赖（纯标准库）；AK 在 `~/.kg-agent-config/credentials.json` |
| `kg-install` / `kg-vault` / `kg-init` / `kg-ask` / `kg-lint` / `kg-review` / `kg-learn` / `kg-capture` | 无额外依赖（纯标准库） |

---

## 用法示例

```bash
cd skills/kg-wiki-skills

# 首次：告诉它你的库在哪
./bin/kg-node kg-vault/scripts/vault-cli.mjs add /path/to/your-vault --desc "这个库的用途"

# 摄入
./bin/kg-py kg-doc/scripts/ingest_doc.py ~/Downloads/paper.pdf
./bin/kg-py kg-doc/scripts/ingest_doc.py ~/papers --batch
./bin/kg-node kg-ingest/references/youtube/ingest-video.mjs "https://youtube.com/watch?v=xxx"
./bin/kg-py kg-ingest/references/bilibili/search_videos.py "Rust 异步" --order click --min-min 8

# 使用
./bin/kg-node kg-ask/scripts/search-vault.mjs "泛域名 证书"
./bin/kg-node kg-review/scripts/pick-review.mjs --count 3
./bin/kg-node kg-lint/scripts/lint-vault.mjs
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
- **小红书搜索/收藏夹批量抓取** —— 非 SSR，需要真实浏览器登录态，按需走 `kg-browser`

**刻意做了的：**

- **真实浏览器而非无头浏览器** —— 天然有登录态、天然过 JS 挑战、零反爬对抗
- **平台自适应 ASR** —— 而非强求一个后端跑遍所有平台
- **只读用户已能看到的内容** —— 不注入 cookie、不绕权限、不批量爬取

---

## 兼容性

- 在 **Claude Code / pi** 等支持 Agent Skills（`SKILL.md` + frontmatter）的环境下开箱可用
- skill 发现：Piko 默认把本仓库软链到项目 `.agents/skills/`，含 `SKILL.md` 的目录会被递归发现；需要跨项目共享时也可另建用户级软链

  ```bash
  mkdir -p .agents/skills
  ln -s ../../skills/kg-wiki-skills .agents/skills/kg-wiki-skills
  ```

  软链名称可以自定；各 skill 的命令都相对自身位置解析，不依赖软链名或调用时的工作目录。
- 脚本以 Node CLI 为主；文档解析、语音转写和少数平台适配保留 Python 后端，均可脱离 Agent 直接调用

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
