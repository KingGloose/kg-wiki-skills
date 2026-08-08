# 开发约定

本仓库的 `kg-*/` 是可独立发现的 Agent Skills，开发时保持 `SKILL.md`、脚本和依赖说明一致，只修改与当前需求直接相关的内容。
仓库会通过软连接注册到全局 skill 目录，skill 可能从系统任意工作目录被调用；路径必须相对 skill/仓库自身解析，不得依赖当前目录、软连接名称或硬编码的知识库路径。
知识库定位统一遵循 `--vault` → `KG_VAULT` → `~/.kg-agent-config/config.json` 的 `vault` 分域 → 向上查找；没有唯一结果时必须询问用户，不能猜测或静默选择。
知识库定位统一复用 `media_to_text.vault`，素材转换统一复用 `kg-media-to-text`；上层 skill 只负责来源适配与沉淀流程，避免复制出行为不同的实现。
改动后至少运行相关 CLI 检查，并执行 `python3 kg-install/scripts/lint_docs.py`；不要提交凭证、缓存、转写产物或用户知识库内容。
