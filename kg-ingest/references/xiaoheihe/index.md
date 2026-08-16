# 小黑盒摄入

小黑盒（www.xiaoheihe.cn）没有公开文档化的抓取 API，App 接口带 `hkey` 签名。**默认走 `kg-browser` 读用户已登录的 Chrome**；纯静态抓取只适合碰运气，不要作为主路线。

## 流程

1. 先按 `kg-ingest/SKILL.md` 共通纪律：选库、查重。
2. 固定 session，例如 `xhh-capture`：

   ```bash
   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs navigate "<分享链接>" \
     --new-tab --group-title "知识摄入" --session xhh-capture

   ../../../bin/kg-node kg-browser/scripts/kimi-bridge.mjs snapshot --session xhh-capture
   ```

3. 分享链接可能跳到 `www.xiaoheihe.cn` 的帖子页，也可能直接返回 JSON（App 分享链接）。两种都先看页面实际内容，不要猜格式。

## 网页帖子页

页面是 Vue SSR，`window.__INITIAL_STATE__` 里通常挂着页面数据。先用 `evaluate` 试取：

```js
(() => {
  const s = window.__INITIAL_STATE__;
  const post = s?.postDetail || {};
  const article = post?.article || post?.link || {};
  return {
    url: location.href,
    title: s?.postTitle || document.title,
    text: article?.content || article?.text || document.body.innerText.slice(0, 20000),
    images: Array.isArray(article?.images) ? article.images : [],
  };
})()
```

拿不到或字段为空时，退回 `snapshot` 人工读页面结构，再用 `click` / `scroll` 展开正文。

## App 分享接口（观察记录，未逆向）

在小黑盒前端包里能看到 `api.xiaoheihe.cn/bbs/app/api/share/data/`，但实测缺少 `hkey` 参数会直接报错；`/bbs/web/link/detail` 需要合法 `link_id`。**没有验证过的签名方案前不要手拼这些接口**，浏览器路线已经能拿到正文。

如果将来要 CLI 化，再单独逆向 `hkey` 算法并把可用参数沉淀回本页。

## 内容特点

- 游戏资讯帖常带多张截图/长图：`screenshot` 后走 `kg-vision`，关键信息在图片里。
- 社区帖子正文可能短，价值常在评论区。默认只收楼主正文；用户明确要评论时再收，并在文件里标注“评论来源”。
- 视频帖优先找视频链接/音轨，走 `kg-media-to-text`；网页正文只是摘要。

## 落盘

按 `references/web/index.md` 第 3 步：写 `raw/web-<日期>-<标题>.md`，头部
`source` 填最终 URL，`method: kg-browser`。确认后再沉淀。
