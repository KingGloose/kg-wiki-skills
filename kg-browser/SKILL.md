---
name: kg-browser
description: 底层浏览器能力：通过 Kimi WebBridge 操作用户真实的 Chrome，使用现有登录态读取需要登录、有反爬或 JS 挑战的页面，也可翻页、滚动、展开折叠、截图、查网络请求和批量读标签页；另提供从本地 Chrome 历史/书签模糊查找 URL。当上层摄入 skill 需要真实浏览器，或用户说「读一下我浏览器里打开的页面」「这个站要登录才能看」「纯抓取被 403 了」「之前看过一篇讲 X 的文章帮我找出来」时使用。
---

# kg-browser

通过 Kimi WebBridge 的本地守护进程操作用户可见的真实 Chrome。不导出 cookie、不伪造凭证、不绕过用户本来无权访问的内容。

## 会话约定

每个用户任务选一个简短的 session 名，例如 `wiki-zhihu-capture`。同一任务的所有命令始终传同一个 `--session`，不要按站点切换 session。

首次打开页面时使用 `--new-tab --group-title "<任务标题>"`。由任务打开的页面会收进同一个标签组。只有用户明确要求关闭时才调 `close_session`。

## 快速命令

以下命令假设当前在 `skills/kg-wiki-skills/`：

```bash
bin/kg-node kg-browser/scripts/kimi-bridge.mjs list_tabs --session wiki-capture

bin/kg-node kg-browser/scripts/kimi-bridge.mjs navigate "<url>" \
  --new-tab --group-title "知识摄入" --session wiki-capture

bin/kg-node kg-browser/scripts/kimi-bridge.mjs find_tab "<完整 URL>" \
  --active --session wiki-capture

bin/kg-node kg-browser/scripts/kimi-bridge.mjs snapshot --session wiki-capture
bin/kg-node kg-browser/scripts/kimi-bridge.mjs click "@e123" --session wiki-capture
bin/kg-node kg-browser/scripts/kimi-bridge.mjs fill "@e456" "<内容>" --session wiki-capture

bin/kg-node kg-browser/scripts/kimi-bridge.mjs evaluate \
  "(() => ({url: location.href, title: document.title, text: document.body.innerText}))()" \
  --session wiki-capture
```

客户端连不到守护进程时会自动执行 `kimi-webbridge start`。如果返回 `no extension connected`，请用户在 Chrome 里连接 Kimi WebBridge 扩展，不要改为导出 cookie 的方案。

## 读取正文

1. 先用 `snapshot` 确认页面是否加载完、是否需要登录。
2. 优先从 snapshot 读文本和找交互元素；只在需要 DOM 属性或大块 HTML 时用 `evaluate`。
3. 页面折叠时用 snapshot 里的 `@e` 按钮点开；页面变化后重新 snapshot，不要重用旧 `@e`。
4. 懒加载或无限滚动用 `evaluate` 滚动后再 snapshot。
5. 正文选择器和站点坑查 `references/site-selectors.md`。

Kimi WebBridge 的 `evaluate` 支持 `async/await`。多次执行时用 IIFE 包住代码，避免在页面的同一 JS realm 里重复声明 `const` / `let`。

## 历史与书签

用户记得看过某篇内容但没有 URL 时：

```bash
bin/kg-node kg-browser/scripts/find-history.mjs --keywords <多个关键词> --articles-only
bin/kg-node kg-browser/scripts/find-history.mjs --keywords 知乎 知识库 wiki --days 30 --articles-only
```

主动扩展同义词，找文章时默认加 `--articles-only`。拿到多个相似候选时让用户确认，不要自己猜。细节见 `references/history-search.md`。

## 边界

- 默认只读。提交表单、发布、点赞或发送消息必须有用户明确授权。
- 遇到银行、验证码或检查 `event.isTrusted` 的操作，让用户手动完成。
- 跨域 iframe 不能直接操作时，获取 iframe URL 后单独导航。
- 详细错误处理见 `references/troubleshooting.md`。
