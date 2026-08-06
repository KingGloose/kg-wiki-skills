---
name: kg-vivo-health
description: 读取用户 vivo 手表/健康 App 的健康数据（步数、睡眠、心率、血氧、压力、运动），按天落盘到知识库 daily/ 目录。当用户问「我今天走了多少步」「昨晚睡得怎么样」「我的健康数据」或需要定时采集 vivo 健康数据时使用。纯命令行登录（短信验证码），不需要模拟器。不负责其他品牌手环（小米/华为等）——那些走各自生态。
---

# kg-vivo-health · vivo 健康数据采集

把 vivo 手表/健康 App 的数据（步数、睡眠、心率、血氧、压力、运动）拉取并按天落盘到知识库 `daily/YYYY-MM-DD/vivo-health.json`。

## 何时用

- 「我今天走了多少步」「昨晚睡了多久/睡得怎么样」
- 「我的健康数据怎么样」→ 拉最近几天的汇总
- 定时任务：每天自动采集（launchd 或 agent 定时）

## 数据源与原理

数据来自 vivo 健康云端 API（`health.vivo.com`），用 vivo 账号 token 直连，**不需要模拟器**。
登录走短信验证码（`smsLogin/p1` 发码 → `p2` 验证 → 拿 token），token 持久化在 `scripts/.state/vivo-health/token.json`。

sign 算法已逆向自 `libvivo_account_wave.so`（MD5 + 参数排序拼接），纯 Python 实现，无需 native。

## 脚本位置

```
scripts/lib/kg_vivo_health.py       # 核心库：登录 + 拉数据 + 落盘
scripts/lib/collect_vivo_health.py  # 采集入口（CLI）
scripts/lib/wave_prefix.bin         # sign 前缀（361 字节）
scripts/collect-vivo-health.sh      # shell 入口（launchd 用）
```

## 用法

```bash
# 1. 登录（首次 / token 过期时）
python3 scripts/lib/collect_vivo_health.py --send-code <手机号>
#   → 返回 randomNum，验证码发到手机
python3 scripts/lib/collect_vivo_health.py --verify <手机号> <验证码> <randomNum>
#   → token 保存到 scripts/.state/vivo-health/token.json

# 2. 采集某天数据（默认今天）
python3 scripts/lib/collect_vivo_health.py [日期 YYYY-MM-DD]
# 或
./scripts/collect-vivo-health.sh [日期]
```

## 落盘格式

- `<vault>/daily/YYYY-MM-DD/vivo-health.json` —— 完整原始数据
- `<vault>/daily/YYYY-MM-DD/vivo-health-summary.json` —— 摘要（步数/睡眠/心率/血氧/压力）

摘要字段：
```json
{
  "steps": 952.0,
  "distance_m": 734.54,
  "calories": 69.69,
  "heart_rate": 86.0,
  "spo2": 96.0,
  "stress": 44.0,
  "sleep_hours": 6.8,
  "sleep_score": 80
}
```

## 给 agent 的回答约定

- **区分数据来源**：数字来自 vivo 云端，标 `owner`（用户自己的健康数据）；解释性内容（如"8000 步是活跃标准"）是通用知识，不要混为数据。
- **不猜指标含义**：字段含义按 App 定义（步数=当日累计、sleep_score=睡眠评分 0-100 等）。拿不准就问。
- **provenance**：定时采集的落盘是 `owner` 级（用户自己的数据），可进长期记忆/日报。

## 定时采集（可选）

参考 `scripts/com.kg.vivo-health.plist.example` 配 launchd，每天定时跑 `collect-vivo-health.sh`。
token 过期时脚本报错，需手动重新登录（上面步骤 1）。

## 边界

- 只支持 vivo 账号（手表数据在 vivo 云端）
- token 有效期不定（实测跨天），过期需重登
- 私有 API，vivo 可能调整字段——字段缺失时如实说明，不编造
