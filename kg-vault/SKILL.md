---
name: kg-vault
description: 知识库路径与用途管理——维护库的别名、路径和 desc，供 AI 在多个全局知识库之间自动路由。当用户说「我的知识库在 X」「这个库放后端内容」「切换到工作库」「有哪些知识库」，或任何 kg-* skill 报「找不到知识库」时使用。提供 which / list --json / add --desc / describe / use / remove / doctor。**不负责创建知识库**——建新库或改造旧笔记走 kg-init。
---

# kg-vault · 知识库在哪

**只管库的注册信息：在哪、叫什么、收什么。** 其他 kg-* skill 要读写知识库，
先读取这里的 `path + desc`，由 AI 根据本次内容选择目标库。

配置在 `~/.kg-agent-config/config.json` 的 `vault` 分域；同一文件还可包含 Agent 的
`collect` / `report` 等配置，`kg-vault` 写入时不会覆盖它们。

## 与 kg-init 的分工（别搞混）

```
旧笔记仓库 / 空目录
   ↓  kg-init      ← 建结构、建 AGENTS.md（它有模板），会先出计划让用户确认
标准的知识库结构
   ↓  kg-vault     ← 注册路径、切换默认（本 skill）
其他 skill 能找到它了
```

**本 skill 不建库、不改知识内容**，只维护"别名 → 路径 + 用途描述"的映射。
遇到还不是知识库的目录，会引导去 kg-init。

## 何时用

- **任何 kg-* skill 报「找不到知识库」时** ← 最主要的触发场景
- 「我的知识库在 /path/to/xxx」→ `add`
- 「这个库专门放后端内容」→ `describe`
- 「帮我新建一个知识库」→ 转交 `kg-init`
- 「切到工作那个库」→ `use`
- 「有哪些库」→ `list`
- 配置好像不对 → `doctor`

## 用法

```bash
source ../.venv/bin/activate

python scripts/vault_cli.py which            # 当前会用哪个库（拿不准时先跑这个）
python scripts/vault_cli.py list             # 列出已注册的库和用途
python scripts/vault_cli.py list --json      # 给 AI 自动路由用
python scripts/vault_cli.py doctor           # 检查配置与各库健康

python scripts/vault_cli.py add  <路径> [--name 别名] [--desc 用途]  # 注册知识库
python scripts/vault_cli.py describe <别名> "用途描述"             # 补/改用途
python scripts/vault_cli.py use  <别名>                 # 切换默认库
python scripts/vault_cli.py remove <别名>               # 移除注册（不删目录）
```

`init` 子命令仅为旧调用保留，会引导去 `kg-init`，不要在新流程中使用。

> **手动执行时**先 `cd` 到本 skill 目录。Windows PowerShell 用
> `..\.venv\Scripts\Activate.ps1`，CMD 用 `..\.venv\Scripts\activate.bat`。
>
> 嫌麻烦可用 `../bin/kg-py`，它自己找环境，无需激活也无需 cd：
> `../bin/kg-py <skill>/scripts/<脚本>.py [参数]`

## 退出码

| 码 | 含义 | AI 该做什么 |
|----|------|------------|
| `0` | 明确知道用哪个库（stdout 是路径） | 直接继续，别打扰用户 |
| `1` | 出错（路径不存在、别名冲突等） | 看错误信息处理 |
| `2` | `which` 无法给出唯一默认（未配置 / 多库无默认 / 路径失效） | 多库先 `list --json` 自动路由；真没配置或全失效才问路径 |

## 核心行为：多库按 desc 自动路由

当任务涉及知识库内容时，先运行：

```bash
../bin/kg-py kg-vault/scripts/vault_cli.py list --json
```

- 只有一个有效库 → 直接用。
- 有多个有效库 → 比较本次主题与每个 `desc`，选择语义最匹配的库，并给后续命令
  **显式传 `--vault <path>`**。不要因为存在默认库就静默写入默认库。
- `desc` 缺失 → 先根据别名和库内结构判断；默认库只作为最后兜底。
- **不要仅因为有多个库就询问用户。** 分类判断属于 AI 的工作。

只有这些情况才问：
- 一个都没注册 → 问「你的知识库在哪个目录？」
  - **已经是标准结构** → `add <路径>`
  - **是旧笔记 / 空目录** → 先走 **kg-init**（改造/建结构），完成后再 `add`
- 注册的路径都失效了（目录被移动/删除）→ 问新路径

`use` 只表示通用兜底偏好，不替代按 `desc` 做内容分类。

## 配置格式

**规范格式（单库、多库都用这一种）**：
```json
{
  "version": 1,
  "vault": {
    "default": "personal",
    "paths": {
      "personal": "/path/to/personal-vault",
      "work": "/path/to/work-vault"
    },
    "descriptions": {
      "personal": "个人阅读、生活经验和非工作灵感",
      "work": "软件工程、后端架构和项目技术决策"
    }
  }
}
```

旧的单库 `{"vault": "/path"}` 和顶层 `vaults/default` 格式仍兼容读取；
下一次执行 `add/use/remove` 时会迁移到规范格式，同时保留其他配置分域。

**旧单库示例**：
```json
{"vault": "/path/to/vault"}
```

## 与其他 skill 的关系

```
其他 kg-* skill 需要读写库
  → AI 先用 list --json 读取 path + desc，按内容自动选库
  → 给业务脚本显式传 --vault
  → 解析失败 → 调用本 skill 修复注册信息
  → 重试原操作
```

直接定位知识库的 CLI 都支持 `--vault <路径>` 做单次覆盖；由 AI 手动沉淀内容的
skill 多库时运行 `list --json` 后显式传路径，**不必**切换默认库。

## 边界

- **只管库的路径和用途描述**，不建库、不改知识内容
- `remove` 只移除注册，**不删目录**（不做危险的事）
- 遇到非知识库目录 → 引导去 kg-init，不自己动手创建
- 配置只存路径，不存任何凭证
