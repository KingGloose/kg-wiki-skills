# 小红书摄入

小红书单篇、搜索和收藏都统一走 `kg-browser` 的 Kimi WebBridge。旧的纯 HTTP
`__INITIAL_STATE__` 抓取依赖页面内部结构，遇到 `xsec_token`、登录态或客户端渲染时
会静默拿到空内容，已经移除。

## 流程

1. 先运行 `../../../bin/kg-node kg-vault/scripts/vault-cli.mjs list --json`，按 `desc`
   选择知识库；再用 kg-ask 查重。
2. 为本次任务固定一个 session，例如 `xhs-capture`：

   ```bash
   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs navigate "<分享链接>" \
     --new-tab --group-title "知识摄入" --session xhs-capture
   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs snapshot --session xhs-capture
   ```

3. 页面需要展开正文、图片或评论时，继续用同一个 session 调 `click`、`scroll`、
   `screenshot`；不要换 session 丢掉标签页上下文。遇到登录提示，让用户在真实 Chrome
   完成登录后继续，不索要 cookie。
4. 小红书的关键信息经常在图片里。必须查看图片/截图并理解版式，不能只保存标题、
   `desc` 和话题标签。
5. 先向用户报告「标题 / 正文和图片大意 / 打算放哪个库和 wiki 位置」，确认后再写。
   只想暂存时，把模型整理出的 Markdown 写到所选库的 `raw/`；写文件仍遵守库契约。

## 单篇、搜索与收藏

- 单篇分享链接：直接 `navigate`，读取正文并逐图查看。
- 搜索结果：导航到搜索页，滚动加载后按候选逐个打开新标签；不要用 HTTP 猜异步接口。
- 收藏夹：依赖用户现有登录态，只在真实 Chrome 内操作。

## 纪律

- 原链接和作者、发布时间、互动数据可作为来源信息，但 `xsec_token` 可能过期。
- 图片内容要注明「信息来自图片」，不要伪装成正文原文。
- 不批量下载全部收藏；先筛选价值，再逐篇摄入，避免知识库变成平台缓存。
- 完成后只关闭本任务创建的标签页；不要关闭用户原有标签页或浏览器。
