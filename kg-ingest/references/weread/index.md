# 微信读书

## 和 vendor/WeChatReading 的分工

`vendor/WeChatReading` 是**腾讯官方**的 skill（纯 Markdown，教 agent 怎么打
gateway）。它的工作流是**被动应答** —— 你问哪本书它查哪本。

本 skill 补两件官方那套没有的事：

1. **主动扫全架做聚合** —— 哪些在吃灰、哪些读了一半、哪些投入多没读完
2. **接沉淀契约** —— 划线导出成 Markdown 落 `raw/`，再进 `wiki/`

接口参数和返回字段以 `../../../vendor/WeChatReading/skills/*.md` 为准，
那边写得比本文档细（含各字段单位、易错点）。

## 一个实测得出的关键结论

**`readUpdateTime` 不是「最后阅读时间」，是「书架条目更新时间」。**

实测：四本 `readUpdateTime` 显示 73 天前的书，`progress` 全是 0%、
`readingTime` 只有 0～43 秒、`isStartReading=0` —— 那天是**批量加入书架**，
不是读了它们。

所以判断「有没有真读过」必须看 `progress` / `readingTime` / `isStartReading`。
只看 `readUpdateTime` 会把「囤了没翻」误判成「读过但搁下了」，
给用户虚假的进度感。本 skill 的分类逻辑就是按这条来的。

同理，微信读书允许**手动标记「已读」**，那种 `readingTime` 很短。
这类单独归到「标记了已读但没什么阅读时长」，不混进「读完了」。

## 前置：API Key

Key 从 https://weread.qq.com/r/weread-skills 扫码获取（格式 `wrk-xxxxxxxx`）。

存进 Keychain（推荐，不落明文）：

```bash
security add-generic-password -a weread -s kg-weread-apikey -w '<wrk-xxx>' -U
```

脚本按 `WEREAD_API_KEY` 环境变量 → Keychain 的顺序找。

## 用法

```bash
# 书架体检（第一次会逐本查进度，之后 6 小时内走缓存）
../../../bin/kg-node kg-ingest/references/weread/weread.mjs shelf
../../../bin/kg-node kg-ingest/references/weread/weread.mjs shelf --refresh    # 强制重拉

# 某本书的划线（书名关键词或 bookId 都行）
../../../bin/kg-node kg-ingest/references/weread/weread.mjs notes "非暴力沟通"

# 哪些书有笔记
../../../bin/kg-node kg-ingest/references/weread/weread.mjs notebooks

# 阅读统计
../../../bin/kg-node kg-ingest/references/weread/weread.mjs stats --mode monthly
#   weekly / monthly / annually / overall

# 都支持 --out 落盘
... --out "<vault>/raw/weread-<slug>.md"
```

## 频控：这个必须注意

微信读书对连续请求限得很紧。实测逐本查 19 本进度时，**大面积返回
`errcode -2014`「请求频率超限」**（HTTP 499）。

所以脚本做了三件事：

- 请求间隔 `MIN_INTERVAL = 1.2` 秒
- 撞限流自动退避重试（3+6+9 秒）
- 进度结果缓存 6 小时到 `~/.cache/kg-weread/progress.json`

**不要绕过脚本连发 curl**，会被限流。要反复看书架就用缓存（二次运行 0.4 秒，
零请求）。

## 没划线时的行为

`notes` 发现你在这本书没有划线，会自动退到**社区热门划线**（TOP 20，
带划过人数）。对没读过的书反而更有用 —— 能快速看到这本书里别人认为重要的是什么。

产出的 md 里会明确标注「这不是你的划线」。**沉淀时必须保留这个区分** ——
社区热门划线是公共信息，不是你的阅读所得，混在一起会污染知识库的
「我的判断」这层价值。

## 沉淀流程

1. **先查重** —— `kg-ask` 看库里有没有记过这本书
2. **抓取** —— 落 `raw/weread-<书名>.md`
3. **确认再写** —— 报「这本书的划线集中在 X，打算放 wiki 哪」，等用户点头
4. **提炼而非照搬** —— 划线是当时的注意力，结论要用户自己下。
   直接把 50 条划线搬进 `wiki/` 是原文摘录，不是沉淀
5. **区分来源** —— 个人划线 / 社区热门 / AI 补充，三者不能混

## 分类口径

| 分类 | 判定 |
|---|---|
| 读完了 | `finishReading=1` 且 `readingTime >= 5 分钟` |
| 标记已读但没时长 | `finishReading=1` 但 `readingTime < 5 分钟` |
| 读了一半搁下的 | 未读完 + `readingTime >= 5 分钟` + `progress` 在 5~85% |
| 投入不少没读完 | 未读完 + `readingTime >= 1 小时`，且不在「半途」 |
| 囤了没真正翻过 | 未读完 + `readingTime < 5 分钟` |

阈值在脚本顶部常量里（`TOUCHED_SECONDS` / `HALFWAY_MIN` / `HALFWAY_MAX`）。

## 限制

- **只读**，不改微信读书的任何数据
- **有声书/专辑**（`albums`）只统计数量，不取内容
- **文章收藏**（`mp`，公众号存的文章）暂未处理 —— 那部分和 `kg-wechat` 重叠
- `stats` 的 `totalReadTime` **单位是秒**，别误当分钟（官方文档专门强调过）

## 失败排查

| 现象 | 原因 |
|---|---|
| `没找到 API Key` | 按上面存进 Keychain |
| `API Key 无效或已失效` | 重新去 weread-skills 页面扫码 |
| `errcode -2014` | 频率超限。脚本会自动重试；手工 curl 请加间隔 |
| 书名匹配到多本 | 用完整书名或 bookId |
| 划线是空的 | 你在这本书确实没划线（会自动退到社区热门划线） |
