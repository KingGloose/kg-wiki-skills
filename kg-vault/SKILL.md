---
name: kg-vault
description: 知识库注册与切换——解决「往哪写」这一个问题。所有其他 kg-* skill 都靠它的配置定位知识库。当用户说「我的知识库在 X」「新建一个知识库」「切换到工作库」「有哪些知识库」，或**任何 kg-* skill 报「找不到知识库」时**使用。提供 which（当前用哪个）/ list / init（从模板建新库）/ add / use（切换默认）/ remove / doctor。多个库且无默认时会明确要求询问用户，而不是瞎猜。
---

# kg-vault · 知识库在哪

**这是前置 skill。** 其他 kg-* skill 要读写知识库，都得先知道库在哪——那个"哪"由这里管。

配置在 `~/.config/kg-wiki/config.json`。

## 何时用

- **任何 kg-* skill 报「找不到知识库」时** ← 最主要的触发场景
- 「我的知识库在 /path/to/xxx」→ `add`
- 「帮我新建一个知识库」→ `init`
- 「切到工作那个库」→ `use`
- 「有哪些库」→ `list`
- 配置好像不对 → `doctor`

## 用法

```bash
cd kg-wiki-skills/kg-vault && source ../.venv/bin/activate

python scripts/vault_cli.py which            # 当前会用哪个库（拿不准时先跑这个）
python scripts/vault_cli.py list             # 列出已注册的库
python scripts/vault_cli.py doctor           # 检查配置与各库健康

python scripts/vault_cli.py init <路径> [--name 别名]   # 从模板建新库并注册
python scripts/vault_cli.py add  <路径> [--name 别名]   # 注册已有的库目录
python scripts/vault_cli.py use  <别名>                 # 切换默认库
python scripts/vault_cli.py remove <别名>               # 移除注册（不删目录）
```

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
  - 已有库 → `add <路径>`
  - 没有库 → `init <路径>`（从 `templates/` 创建骨架）
- 多个有效库但没指定默认 → 问「这次要写到哪个库？」
  - 单次：其他脚本加 `--vault <路径>`
  - 长期：`use <别名>`
- 注册的路径都失效了（目录被移动/删除）→ 问新路径

**不要猜路径。** 猜错会把内容写到不该去的地方。

## init 会做什么

```
<路径>/
├── AGENTS.md    ← 从 kg-vault/templates/ 复制（维护契约，所有 skill 都依赖它）
├── index.md     ← 唤醒索引骨架
├── log.md       ← 流水账格式说明
├── wiki/        ← 沉淀的知识
├── raw/         ← 原始资料留档
└── assets/      ← 图片
```

**安全约束**：
- 目标已是知识库 → 只注册，**不覆盖任何文件**
- 目标存在且非空但不像知识库 → **拒绝操作**（避免污染别人的目录），提示用空目录或手动补齐后 `add`

创建后要提醒用户：**按自己习惯改 `AGENTS.md`**，尤其「写作约定」和「领域划分」——
那份是模板，不改也能用，但改过才贴合自己。

## 模板

模板是本 skill 的自带资源，在 `kg-vault/templates/`：`AGENTS.md` / `index.md` / `log.md`。
`kg-init`（改造现有笔记）也复用这份模板 —— 建库这件事归本 skill 管，模板自然放这里。

**改模板 = 改所有新库的起点。** 若想调整默认契约，改 `templates/AGENTS.md`。

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

- 只管"库在哪"，不碰库里的内容
- `remove` 只移除注册，**不删目录**（不做危险的事）
- `init` 不覆盖已有文件
- 配置只存路径，不存任何凭证
