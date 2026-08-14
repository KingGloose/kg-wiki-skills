# 开发约定

本仓库的 `kg-*/` 是可独立发现的 Agent Skills，开发时保持 `SKILL.md`、脚本和依赖说明一致，只修改与当前需求直接相关的内容。
仓库会通过软连接注册到全局 skill 目录，skill 可能从系统任意工作目录被调用；路径必须相对 skill/仓库自身解析，不得依赖当前目录、软连接名称或硬编码的知识库路径。
知识库定位统一遵循 `--vault` → `KG_VAULT` → `~/.kg-agent-config/config.json` 的 `vault` 分域 → 向上查找；多库时先读取 kg-vault 的 `path + desc`，由模型按本次内容自动选择并显式传 `--vault`，不要静默使用默认库，也不要仅因多库询问用户。desc 不足时按别名/库结构判断、默认库最终兜底；只有未配置或路径全失效时才询问路径。
知识库定位的规范实现是 `lib/vault.mjs`。Node 脚本直接复用它；仍保留的 Python 文档/语音后端复用兼容实现 `media_to_text.vault`，两者必须读写同一份配置格式。素材转换统一复用 `kg-media-to-text`；上层 skill 只负责来源适配与沉淀流程。
改动 Node 公共能力后执行 `npm test`；改动 Skill 文档后执行 `./bin/kg-node kg-install/scripts/lint-docs.mjs`。不要提交凭证、缓存、转写产物或用户知识库内容。
