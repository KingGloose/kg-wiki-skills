# X / Twitter 摄入

## 现状判断

X 没有稳定、免费、免登录的公开抓取通道（官方 API 收费，twscrape 等方案需要额外账号和风控成本），所以**默认走 `kg-browser` 读用户已登录的 Chrome**。不要在无登录的情况下硬试 `kg-doc` —— X 页面是重 JS 渲染，静态抓取基本只会拿到空壳或登录墙。

## 流程

1. 先按 `kg-ingest/SKILL.md` 共通纪律：`kg-vault list --json` 选库、`kg-ask` 查重。
2. 固定一个 session，例如 `x-capture`：

   ```bash
   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs navigate "<tweet URL>" \
     --new-tab --group-title "知识摄入" --session x-capture

   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs snapshot --session x-capture
   ```

3. `t.co` 短链直接导航即可，浏览器会跳到最终 `x.com/.../status/...`；记录最终 URL 作为 `source`。
4. 单条推文：优先用 `evaluate` 从 DOM 取正文，不要搬导航/推荐流：

   ```js
   (() => {
     const text = [...document.querySelectorAll('[data-testid="tweetText"]')]
       .map((el) => el.innerText.trim())
       .join('\n\n');
     const author = document.querySelector('[data-testid="User-Name"]')?.innerText ?? '';
     const time = document.querySelector('time')?.getAttribute('datetime') ?? '';
     return { url: location.href, title: document.title, author, time, text };
   })()
   ```

5. 推文线程：页面通常会自动展开主帖 + 回复；没展开完就滚动/点「显示更多」后重新 `snapshot`。只收**楼主自己的连续内容**，评论默认不要，除非用户明确说“把讨论也存了”。
6. 推文里的图片/长截图：`screenshot` 后走 `kg-vision`，不要只记一句“配了张图”。

## 可能遇到的墙

| 现象 | 处理 |
|---|---|
| 未登录只能看到单条，点不进回复 | 让用户在 Chrome 里登录 X，再重试；不导出 cookie |
| 页面一直转圈 / `snapshot` 为空 | 等几秒重 `snapshot`；或先 `navigate` 到最终 URL |
| 搜索/主页时间线 | 这类默认不摄入，除非用户指定某几条 |
| NSFW/风控页 | 不绕过，告诉用户页面被平台挡住 |

## 落盘

按 `references/web/index.md` 第 3 步：写 `raw/web-<日期>-<作者-内容前几词>.md`，头部
`source` 填最终 `x.com/.../status/...` URL，`method: kg-browser`。确认后再沉淀。
