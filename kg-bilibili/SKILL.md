---
name: kg-bilibili
description: B站操作（全能力）。查询 UP 主动态/投稿/合集、搜索、视频详情/分P/播放地址、字幕、弹幕、评论、收藏夹、稍后再看、直播、下载、语音转文字，以及扫码登录和点赞/投币/三连/发评论（写操作）。当用户要「查 UP」「搜视频」「看视频讲了什么」「看收藏/稍后再看」「下载」「看直播」「登录 B站」时使用。底层是 @renmu/bili-api（Node 封装）。
---

# kg-bilibili · B站操作

把 B站的能力接进来，让 AI 通过命令行直接操作 B站。底层 `@renmu/bili-api`（Node，活跃维护）。

## 何时用

- 查 UP / 搜视频 / 看视频详情 / 字幕 / 弹幕 / 评论 → 对应查询子命令
- 看收藏夹 / 稍后再看 / 合集 → 收藏类子命令
- 直播 / 下载 / 语音转文字 → 对应子命令
- 登录 → `qrcode` + `login`

## 用法

所有命令先 `cd` 到 skill 根目录，用 `bin/kg-node` 调脚本（stdout 是 JSON/文本，进度打 stderr）：

### 登录
```bash
../../../bin/kg-node kg-bilibili/scripts/bili.mjs qrcode                  # 出登录二维码（返回 auth_code）
../../../bin/kg-node kg-bilibili/scripts/bili.mjs login <auth_code>      # 扫完轮询，写 cookie
```

### 查询（公开数据，无需登录）
```bash
bili.mjs up <uid>                 # 查 UP：信息+动态+投稿
bili.mjs search <关键词>          # 综合搜索
bili.mjs searchtype <词> <类型>   # 分类搜索（video/bili_user/media_bangumi/live_room）
bili.mjs video <BV号>             # 视频详情
bili.mjs pages <BV号>             # 分P列表
bili.mjs desc <BV号>              # 视频简介
bili.mjs playerinfo <BV号>        # 播放信息（含字幕列表）
bili.mjs playurl <BV号>           # 播放地址
bili.mjs areas                    # 分区列表
```

### 内容（字幕/弹幕/评论）
```bash
bili.mjs subtitle <BV号>          # 字幕 srt
bili.mjs danmaku <BV号>           # 弹幕 XML
bili.mjs comment <BV号>           # 评论列表（按点赞）
bili.mjs replycount <BV号>        # 评论数
```

### 收藏 / 稍后再看 / 合集（需登录）
```bash
bili.mjs me                       # 我的信息
bili.mjs favlist                  # 我的收藏夹列表
bili.mjs toview                   # 稍后再看列表
bili.mjs collections <uid>        # 某 UP 的合集/系列列表
bili.mjs seriesvideos <uid> <sid> # 合集-视频列表
bili.mjs seasons <uid> <sid>      # 合集-投稿列表（season）
```

### 直播
```bash
bili.mjs live <房间号>            # 房间+主播信息
bili.mjs liveguard <房间号>       # 舰长列表
bili.mjs liveslice <房间号>       # 直播回放列表
```

### 下载 / 转写
```bash
bili.mjs download <BV号> [路径] [清晰度]  # 整视频下载。清晰度按场景选：
                                     #   · 只要语音做 ASR → 用最低（240p/360p 自动选），文件小
                                     #   · 要识别视频画面/图片内容 → 用 64（720p），清晰度大小合适
                                     #   清晰度档位：16=360p 32=480p 64=720p 80=1080p
bili.mjs asr <音频文件>           # 语音转文字 srt（B站云端）
```

> 视频转写流程：`bili download <BV>`（默认 240p，文件很小）→ ffmpeg 提音频（`-vn`）→ `bili asr <音频>`。
> 判据：只做语音转写用最低清晰度；需要看画面/识图/OCR 时传 `64`（720p）。

### 写操作 ⚠️（改变账号状态，**必须先 ask_master 确认**）
```bash
bili.mjs like <BV号>              # 点赞
bili.mjs coin <BV号> [1|2]        # 投币
bili.mjs three <BV号>             # 一键三连
bili.mjs share <BV号>             # 分享
bili.mjs replyadd <BV号> <内容>   # 发评论
```

## 登录（cookie）

**两步式**（agent 后台跑不了"阻塞等扫码"）：

1. `bili qrcode` 秒出二维码，返回 `{ url, auth_code, png }`，auth_code 已存 state
2. 把二维码图/链接发给主人扫
3. 主人扫完，`bili login <auth_code>` 轮询几秒完成，cookie 写 `~/.piko-config/credentials/bilibili.json`

cookie 有效期约一个月，报鉴权错误时提醒主人重新走上面两步。

## 怎么拿 uid / BV 号 / 房间号

- 搜索/`up` 结果里有 mid（uid）和 bvid
- B站链接：`space.bilibili.com/<uid>` 是 uid；`video/BV...` 是 bvid；`live.bilibili.com/<房间号>`
- **推荐视频给主人时，每条必须附完整链接** `https://www.bilibili.com/video/BV…`

## 边界

- **不碰创作中心**（上传/编辑投稿）
- 写操作（like/coin/three/share/replyadd）会改变账号状态，**先 ask_master 再调**
- 遵守 B站使用规范，只做个人查询，别批量抓取
