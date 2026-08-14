---
name: kg-ingest
description: 内容摄入统一入口：把外部平台的内容抓进知识库。覆盖 B站、YouTube、知乎、小红书、微信公众号、小宇宙播客、GitHub、微信读书。当用户丢一个链接过来（多数情况下不附加说明，默认意图就是「存进知识库」）、说「解析这个视频/文章/播客」「这篇存一下」「我 star 了哪些仓库」「哪些书该读了」时使用。本 SKILL.md 只做路由，认出平台后去读 references/<平台>/index.md 拿具体做法。不负责本地文档与普通网页（走 kg-doc）、库内检索（kg-ask）、跨项目结论捕获（kg-capture）。
---

# 内容摄入

## 怎么用这个 skill

**先按链接特征认出平台，再去读对应的 `references/<平台>/index.md`。**
那里面才有接口、参数、坑和沉淀纪律。别凭印象直接敲命令。

| 链接 / 意图 | 读这个 |
|---|---|
| `bilibili.com` / `b23.tv` / `BV…`、「稍后再看」「收藏夹」 | `references/bilibili/index.md` |
| `youtube.com` / `youtu.be` | `references/youtube/index.md` |
| `zhihu.com` / `zhuanlan.zhihu.com` | `references/zhihu/index.md` |
| `xiaohongshu.com` / `xhslink.cn`、整段「打开【小红书】」分享文本 | `references/xiaohongshu/index.md` |
| `mp.weixin.qq.com/s/…` | `references/wechat/index.md` |
| `xiaoyuzhoufm.com/episode/…` | `references/xiaoyuzhou/index.md` |
| `github.com/…`、「我 star 了什么」「这个 issue 存下来」 | `references/github/index.md` |
| 「书架」「划线」「哪些书没读」「读了多久」 | `references/weread/index.md` |

**不在这张表里的**：

- 本地文档（PDF/Word/Excel/PPT）、普通技术博客 → `kg-doc`
- 要登录态或有 JS 挑战的任意网页 → `kg-browser`（知乎就是委派它）
- 小红书**搜索结果**和**收藏夹** → 不是 SSR，得走 `kg-browser`，
  本 skill 只处理单篇（详见 xiaohongshu/index.md 的边界说明）

## 为什么合成一个 skill

八个平台原来是八个独立 skill，八份 description 共 5000+ 字符**全部常驻
system prompt**，不管当次用不用。合并后只有这一份，平台细节按需披露。

副作用是加新平台的成本降到「加一个 `references/<平台>/` 目录 + 表里加一行」，
不增加常驻开销。

## 目录约定

```
references/<平台>/
├── index.md        做法、接口、坑、沉淀纪律
└── *.py            该平台的脚本，跟文档放一起
```

脚本一律用仓库的环境入口跑（路径相对本 SKILL.md）：

```bash
../bin/kg-py kg-ingest/references/<平台>/<脚本>.py [参数]
```

`kg-py` 自己找 venv，不用激活也不用 cd。

## 所有平台共通的流程纪律

不管哪个平台，摄入都走这四步。**这几条比任何平台的技术细节都重要**：

0. **先路由知识库。** 运行 `../bin/kg-py kg-vault/scripts/vault_cli.py list --json`，
   按 `desc` 判断本次内容最适合的库，后续检索和摄入都显式传 `--vault <path>`。
   多库不询问用户，也不静默使用默认库。
1. **先查重。** 用 `kg-ask` 看库里是否已有。重复沉淀会让知识库退化成
   搜索引擎缓存。
2. **抓取扔 subagent。** 字幕、正文、OCR 吐字量大，在主会话里做会把上下文
   烧穿。用 fresh context 的子进程，只把摘要带回来。
3. **沉淀前确认。** 抓完先报「标题 / 大意 / 打算放 wiki 哪」，等用户点头再写。
   他可能只想暂存 `raw/` 不要沉淀。
4. **区分来源。** 这是知识库的核心价值所在：

   | 性质 | 例子 | 能进 `wiki/` 吗 |
   |---|---|---|
   | 带用户判断 | 他划的线、他收藏的、他提的 issue、他主动丢的链接 | ✅ |
   | 不带判断 | 搜索结果、社区热门划线、star 清单、AI 补充的知识 | ❌ 只做情报 |

   把后者无差别灌进 `wiki/`，三个月后用户分不清哪些是自己想过的。

## 共通的失败模式

| 现象 | 先查什么 |
|---|---|
| `ModuleNotFoundError` | 是不是没走 `kg-py`（依赖在仓库 venv 里，系统 python 是 3.9 且什么都没有） |
| 凭据相关报错 | `~/.kg-agent-config/credentials.json` 里对应平台那段 |
| 找不到知识库 | 先用 `kg-vault list --json` 看 `path + desc`；未注册再检查配置 |
| GitHub 相关超时 | 直连不通，脚本已内置代理，手工敲 `gh` 要自己带 `HTTPS_PROXY` |
