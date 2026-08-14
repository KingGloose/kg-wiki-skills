# GitHub 摄入

## 为什么用 `gh` 而不是自己调 REST

官方 CLI，认证走 OAuth（不用手工建 token 也不用在仓库里存密钥），
分页、限流、错误处理它都管了。本 skill 只做三件 `gh` 不该管的事：

1. 需要时集中注入代理
2. 把 issue 正文 + 讨论拼装成可读 Markdown
3. 落 `raw/` 的命名和 frontmatter 跟其他 `kg-*` 对齐

## 前置：一次性

```bash
brew install gh
gh auth login    # 选 web browser 登录；网络需要代理时自行设置 HTTPS_PROXY
```

脚本尊重现有 `HTTPS_PROXY`；设置 `KG_GH_PROXY` 时会在未配置代理的环境中注入它。
不写死某台机器的代理端口。

验证：

```bash
gh api user --jq .login
```

## 用法

```bash
# 我 star 了什么（按语言分组，按 star 数排序）
../../../bin/kg-node kg-ingest/references/github/gh-fetch.mjs stars
../../../bin/kg-node kg-ingest/references/github/gh-fetch.mjs stars --language Python

# 单个 issue/PR 全文 + 全部讨论
../../../bin/kg-node kg-ingest/references/github/gh-fetch.mjs issue "sjzar/chatlog#197"

# 我提的 issue / PR（含正文）
../../../bin/kg-node kg-ingest/references/github/gh-fetch.mjs mine --limit 30

# 仓库概况 + README
../../../bin/kg-node kg-ingest/references/github/gh-fetch.mjs repo "Tencent/WeChatReading"

# 都支持 --out 落盘
... --out "<vault>/raw/gh-<slug>.md"
```

## 四个子命令的定位不同

| 命令 | 拿到什么 | 沉淀价值 |
|---|---|---|
| `mine` | 你提的 issue/PR **含正文** | **最高** —— 你自己写下的问题和判断 |
| `issue` | 别人的 issue 全文 + 讨论 | 高 —— 排查问题时的一手结论 |
| `repo` | 概况 + README | 中 —— 选型时对比用 |
| `stars` | 清单（无 README） | 低 —— 是索引不是内容 |

**`stars` 别直接沉淀。** 69 个仓库的清单进 `wiki/` 是噪音，它的用途是
「让你回想起 star 过什么」，看完就可以扔。真要沉淀就挑出几个具体的
再用 `repo` 拉详情。

**`issue` 最值得沉淀的场景**：排查问题时找到了关键答案。比如判断某个工具在
新版本上能不能用，issue 里的实测报告就是一手资料 —— 那些讨论会随项目
归档而变难找，存下来有价值。

## 沉淀流程

1. **先查重** —— `kg-ask` 看库里有没有记过这个仓库/问题
2. **抓取** —— 落 `raw/gh-<owner>-<repo>-<slug>.md`
3. **确认再写** —— 报「这个 issue 的结论是 X，打算放 wiki 哪」，等用户点头
4. **沉淀时提炼结论而不是照搬** —— issue 讨论动辄几十条，
   真正有价值的是「最后确认了什么」，不是完整对话

## 限制

- **只读。** 不创建 issue、不提 PR、不改任何东西。
- **`stars` 不带 README**（69 个仓库逐个拉 README 要 69 次请求）。
  要某个仓库的详情用 `repo`。
- **`mine` 用的是 search API**，限流比普通 API 严（30 次/分钟）。
- **私有仓库**取决于你 `gh auth` 的 scope，默认登录能读你有权限的。
- 限流：认证后 5000 次/小时，正常使用碰不到。

## 失败排查

| 现象 | 原因 |
|---|---|
| `gh 未认证` | 跑 `HTTPS_PROXY=… gh auth login` |
| `gh 超时` | 代理不通，检查 `KG_GH_PROXY` |
| `找不到 gh` | `brew install gh` |
| issue 格式报错 | 用 `owner/repo#123`，别漏 `#` |
