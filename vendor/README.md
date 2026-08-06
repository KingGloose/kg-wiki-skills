# vendor/ — 第三方 skill 原样存放

这里放**上游维护的** skill，本仓库不改动其内容。要扩展就在外层写自己的
`kg-*` skill 去调它，别直接改 vendor 里的文件 —— 否则上游更新时会冲突。

## WeChatReading

| | |
|---|---|
| 来源 | https://github.com/Tencent/WeChatReading |
| 归属 | 腾讯官方 |
| 版本 | commit `315698a8` (2026-07-01) |
| 形态 | **纯 Markdown，零可执行代码** |
| 认证 | `WEREAD_API_KEY` 环境变量，格式 `wrk-xxxxxxxx` |
| 取 Key | https://weread.qq.com/r/weread-skills → 「登录微信读书」扫码 |

### 它做什么

教 agent 打微信读书的 Agent API Gateway：

```
POST https://i.weread.qq.com/api/agent/gateway
Authorization: Bearer $WEREAD_API_KEY
Body: {"api_name": "/shelf/sync", "skill_version": "..."}
```

九个能力文档：书架 / 书籍详情 / 笔记划线 / 阅读统计 / 点评 / 搜索 / 推荐 / 个人信息。

### 为什么没用官方给的安装命令

页面上给的是 `npx skills add Tencent/WeChatReading -g`。没用它，因为：

- `-g` 全局安装，会影响所有项目
- `npx` 直接下载执行，跳过了源码审查
- 它是纯 Markdown，`git clone` 过来就行，没必要引入 `skills` 这个工具链

### 已知的功能缺口（外层要补的）

字段都能拿到（`readUpdateTime` / `finishReading` / `progress` / `readingTime`），
但**官方 skill 没有这些用例**：

- 「哪些书躺了三个月没翻」——需要按 `readUpdateTime` 排序筛选
- 「哪些买了没打开过」——`isStartReading == 0`
- 「读了一半扔下的」——`progress` 在 5–80% 且 `readUpdateTime` 很久以前
- 「投入很多但没读完」——`readingTime` 大 + `finishReading == 0`

它的工作流是被动应答（你问哪本它查哪本），没有「主动扫全架找异常」的逻辑。

另外它**不接知识库沉淀契约** —— 只把数据吐出来，不写 `raw/`、不查重、
不落 `wiki/`。这是预期的，它不知道本仓库的存在。

以上都由外层的 `kg-weread` 负责（待建）。

### 更新方式

```bash
# 对比上游是否有变化
git -c http.proxy=http://127.0.0.1:7897 clone --depth 1 \
    https://github.com/Tencent/WeChatReading.git /tmp/wr-upstream
diff -r vendor/WeChatReading/skills /tmp/wr-upstream/skills
```

有变化时整目录替换，并更新上面记的 commit 号。
