# 任意网页链接兜底流程

当链接不在 `kg-ingest` 的已适配平台表里时，按本页的顺序处理。**不要因为“没写过这个平台的 reference”就停下来或直接说抓不了** —— 两条兜底能力已经覆盖绝大多数页面。

## 决策顺序

| 顺序 | 情况 | 走哪条 | 命令入口 |
|---|---|---|---|
| 1 | 普通网页 / 技术博客 / 服务端渲染 | `kg-doc` 静态抓取 | `kg-doc/scripts/ingest_doc.py <url>` |
| 2 | 403 / JS 渲染 / 需要登录 / 抓出来为空 | `kg-browser` 真实 Chrome | `kg-browser/scripts/kimi-bridge.mjs` |
| 3 | 直接给音频/视频文件链接 | `kg-media-to-text` | `kg-media-to-text/scripts/to-text.py <path>` |

## 第 1 步：先试 kg-doc 静态抓取

先预览，判断能不能抓、值不值得抓：

```bash
../../../bin/kg-py kg-doc/scripts/ingest_doc.py "<url>" --stdout
```

判定：

- **正文完整** → 正式跑（不带 `--stdout`），产物会按 kg-doc 的规则落进所选库的 `raw/`。
- **空 / 403 / 只有导航 / 明确需要登录** → 进第 2 步。
- 页面是视频/音频直链 → 下载后走 `kg-media-to-text`，不要硬抓网页。

正式抓取前先选库（`kg-vault list --json`），落 `raw/` 时显式传 `--vault`。

## 第 2 步：kg-browser 兜底

`kg-browser` 用 Kimi WebBridge 操作用户 Windows 上真实 Chrome，天然带登录态。
本页只给通用流程，命令细节读 `../../../kg-browser/SKILL.md`。

```bash
# 一个任务固定一个 session，页面变化后重新 snapshot
../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs navigate "<url>" \
  --new-tab --group-title "知识摄入" --session web-capture

../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs snapshot --session web-capture
```

抓正文时：

1. 先 `snapshot` 确认页面加载完、是否要登录。要登录就让用户在 Chrome 里完成，不要索要 cookie。
2. 正文在 DOM 里时用 `evaluate` 取 `title` + 正文容器 `innerText`；需要交互（点“展开/显示全部”）先用 `click`，再重新 `snapshot`。
3. 正文是图片（例如小红书、部分社区帖）→ `screenshot` 后走 `kg-vision` 识图，不能只存标题和链接。
4. 拿到正文后，按第 3 步的格式整理并写 `raw/`。

## 第 3 步：整理 + 落 raw

kg-browser 路径没有现成落盘脚本，由 agent 写文件到所选库：

```text
<vault>/raw/web-<YYYY-MM-DD>-<安全标题>.md
```

文件头保留溯源：

```markdown
---
source: <最终 URL>
fetched: <YYYY-MM-DD>
method: kg-browser
---

# <页面标题>

<正文 Markdown>
```

- 文件名里的标题要去掉 `/\:*?"<>|` 和控制字符，太长截到 60 字以内。
- 只保留正文和必要的来源信息；导航、推荐流、评论区**默认不搬**，除非用户明确要。
- 原始页面内容暂存 `raw/` 原样留档；只有用户确认后才写 `wiki/`、更新 `index.md` 和 `log.md`。

## 给用户的确认格式

无论走 kg-doc 还是 kg-browser，抓完先报这三样，等点头再写库：

```text
标题：<页面标题>
大意：<2-3 句话，说清这是什么、为什么值得收>
打算放：<哪个库> / raw 暂存 或 wiki/<领域>/<页名>
```

用户可能只想要“存一下”，也可能只想听听内容不沉淀；不要默认写 `wiki/`。

## 容易踩的坑

| 现象 | 处理 |
|---|---|
| kg-doc 抓出来是空/只有导航 | JS 渲染页，切 kg-browser |
| `no extension connected` | 让用户在 Chrome 里连接 Kimi WebBridge 扩展 |
| 页面需要登录 | 用户在真实 Chrome 登录后重试，不导出 cookie |
| 正文被折叠/懒加载 | kg-browser 先 `click` / `evaluate` 滚动，再重新 `snapshot` |
| 正文全在截图里 | `screenshot` → `kg-vision` 转文字，再决定沉淀 |
