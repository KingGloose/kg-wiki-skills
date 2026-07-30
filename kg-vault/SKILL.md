---
name: kg-vault
description: 知识库路径管理——只解决「库在哪」这一个问题。所有其他 kg-* skill 都靠它的配置定位知识库。当用户说「我的知识库在 X」「切换到工作库」「有哪些知识库」，或**任何 kg-* skill 报「找不到知识库」时**使用。提供 which（当前用哪个）/ list / add（注册）/ use（切换默认）/ remove / doctor。多个库且无默认时会明确要求询问用户而非瞎猜。**不负责创建知识库**——建新库或改造旧笔记走 kg-init。
---

# kg-vault · 知识库在哪

**只管一件事：库在哪。** 其他 kg-* skill 要读写知识库，都得先知道路径——那个"哪"由这里管。

配置在 `~/.config/kg-wiki/config.json`。

## 与 kg-init 的分工（别搞混）

```
旧笔记仓库 / 空目录
   ↓  kg-init      ← 建结构、建 AGENTS.md（它有模板），会先出计划让用户确认
标准的知识库结构
   ↓  kg-vault     ← 注册路径、切换默认（本 skill）
其他 skill 能找到它了
```

**本 skill 不建库、不改文件、不碰内容**，只维护"路径 → 别名"的映射。
遇到还不是知识库的目录，会引导去 kg-init。

## 何时用

- **任何 kg-* skill 报「找不到知识库」时** ← 最主要的触发场景
- 「我的知识库在 /path/to/xxx」→ `add`
- 「帮我新建一个知识库」→ `init`
- 「切到工作那个库」→ `use`
- 「有哪些库」→ `list`
- 配置好像不对 → `doctor`

## 用法

```bash
cd "$KG/kg-vault" && source "$KG/.venv/bin/activate"

python scripts/vault_cli.py which            # 当前会用哪个库（拿不准时先跑这个）
python scripts/vault_cli.py list             # 列出已注册的库
python scripts/vault_cli.py doctor           # 检查配置与各库健康

python scripts/vault_cli.py add  <路径> [--name 别名]   # 注册知识库
python scripts/vault_cli.py init <路径>                 # 已弃用：会引导你去 kg-init
python scripts/vault_cli.py use  <别名>                 # 切换默认库
python scripts/vault_cli.py remove <别名>               # 移除注册（不删目录）
```

> `$KG` = 本仓库根目录。全局注册过的话就是 `~/.agents/skills/kg-wiki-skills`
> （Claude Code：`~/.claude/skills/kg-wiki-skills`）；否则用 clone 下来的路径。
> Windows PowerShell 把 `source $KG/.venv/bin/activate` 换成 `$KG\.venv\Scripts\Activate.ps1`。

## 退出码（AI 可据此判断该不该问用户）

| 码 | 含义 | AI 该做什么 |
|----|------|------------|
| `0` | 明确知道用哪个库（stdout 是路径） | 直接继续，别打扰用户 |
| `1` | 出错（路径不存在、别名冲突等） | 看错误信息处理 |
| `2` | **需要询问用户**（未配置 / 多库无默认 / 全部路径失效） | **问用户，不要猜** |

## 核心行为：什么时候问、什么时候不问

**不问**（有明确答案就直接用）：
- 有默认库且有效 → 用它
- 只注册了一个有效库 → 用它（无歧义）

**必须问**：
- 一个都没注册 → 问「你的知识库在哪个目录？」
  - **已经是标准结构** → `add <路径>`
  - **是旧笔记 / 空目录** → 先走 **kg-init**（改造/建结构），完成后再 `add`
- 多个有效库但没指定默认 → 问「这次要写到哪个库？」
  - 单次：其他脚本加 `--vault <路径>`
  - 长期：`use <别名>`
- 注册的路径都失效了（目录被移动/删除）→ 问新路径

**不要猜路径。** 猜错会把内容写到不该去的地方。

## 配置格式

**多库（推荐，`kg-vault` 会自动升级成这个）**：
```json
{
  "default": "personal",
  "vaults": {
    "personal": "/path/to/personal-vault",
    "work": "/path/to/work-vault"
  }
}
```

**单库（旧格式，仍兼容读取）**：
```json
{"vault": "/path/to/vault"}
```

## 与其他 skill 的关系

```
其他 kg-* skill 需要读写库
  → 自己按四级解析：--vault 参数 → KG_VAULT → 本配置 → 向上查找
  → 解析失败 → 报错并提示调用本 skill
  → AI 用 kg-vault 问清楚 / 注册 / 切换
  → 重试原操作
```

所有 skill 都支持 `--vault <路径>` 做单次覆盖，**不必**先改配置。

## 边界

- **只管"库在哪"**，不建库、不改文件、不碰内容
- `remove` 只移除注册，**不删目录**（不做危险的事）
- 遇到非知识库目录 → 引导去 kg-init，不自己动手创建
- 配置只存路径，不存任何凭证
