---
name: kg-vault
description: 知识库路径与用途管理——维护库的别名、路径和 desc，供 AI 在多个全局知识库之间自动路由。当用户说「我的知识库在 X」「这个库放后端内容」「切换到工作库」「有哪些知识库」，或任何 kg-* skill 报「找不到知识库」时使用。提供 which / list --json / add --desc / describe / use / remove / doctor；不负责创建知识库。
---

# kg-vault

只管理「别名 → 路径 + 用途描述」。建库或改造旧笔记走 `kg-init`。

配置位于 `~/.kg-agent-config/config.json` 的 `vault` 分域；写入时必须保留同一文件的 `collect` / `report` 等其他分域。

## 命令

在项目根目录运行：

```bash
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs which
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs list --json
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs doctor

skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs add <路径> --name <别名> --desc <用途>
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs describe <别名> "<用途>"
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs use <别名>
skills/kg-wiki-skills/bin/kg-node kg-vault/scripts/vault-cli.mjs remove <别名>
```

如果当前已在 `skills/kg-wiki-skills/` 内，把前缀缩短为 `bin/kg-node`。不需要激活 Python 虚拟环境。

## 多库路由

在读写知识库前先运行 `list --json`：

1. 只有一个有效库：直接使用。
2. 有多个有效库：比较任务主题与每个 `desc`，选语义最匹配的库。
3. 给后续命令显式传 `--vault <path>`，不要因为配了默认库就静默写入它。
4. `desc` 不足时先看别名和库结构，默认库只是最后兜底。
5. 不要仅因为存在多个库就询问用户。

只有一个库都没注册，或所有路径都已失效时，才询问用户路径。

## 配置格式

```json
{
  "version": 1,
  "vault": {
    "default": "personal",
    "paths": {
      "personal": "/path/to/personal-vault",
      "backend": "/path/to/backend-vault"
    },
    "descriptions": {
      "personal": "个人阅读、生活经验和非工作灵感",
      "backend": "后端架构、数据库和服务端工程"
    }
  }
}
```

`remove` 只移除注册，不删除知识库目录。
