# 决策笔记使用说明

先从 FEATURE_MAP.md 定位并核对代码，再检索 `.agents/notes/` 中除 archived 外的相关笔记。
非平凡改动遵循仓库内 `.agents/skills/write-notes-like-deepseek/SKILL.md`，已有归属优先更新；用户及项目授权高于 Skill 默认确认步骤。

笔记路径为 `.agents/notes/{proposed,implemented,rejected,archived}/{类别}/yyyy-mm-dd-topic.md`。
类别为 feature、bug-fix、simplification、architecture、process、testing。仅创建用到的目录。
新决策先 proposed，实施并验证后改为 implemented，正文改为当前事实，与代码一起提交；机械改动免写。

在项目根目录执行 `python3 .agents/workflow.py verify`。Windows 可使用 `python` 替代 `python3`。
需要 Python 3.9+ 和 Bun；无需安装 npm 依赖。`doctor` 检查运行环境与托管文件完整性。
CI 如需禁止合并，还需仓库分支保护规则；结构检查不判断业务方案正确，也不能证明所有重要决策都已记录。

新电脑克隆仓库即可获得规则、模板及校验器。项目业务笔记、AGENTS.md 和本说明应随仓库提交，不需要全局 Skill。
升级从新版项目能力核对与决策记录工具包运行 `workflow.py install <项目目录>` 预览，再加 `--apply`。安装器拒绝覆盖本地修改；能力地图和本说明始终保留。
敏感信息不应写入笔记；部署、提交、发布遵循本项目授权。

## Xboard 的记录入口

- [README.md](../README.md)：当前能力、反馈结论、验证摘要和导航。
- [progress-log.md](../progress-log.md)：按日期记录用户反馈、排查证据、方案取舍、后续行动、验证和发布状态；完成后从 GitHub 回读核对。
- [FEATURE_MAP.md](./FEATURE_MAP.md)：实际入口、权限、服务、数据来源和验证路径；不能凭地图推断线上状态。
- [接入决策](../.agents/notes/implemented/process/2026-10-17-project-decision-kit.md)：本次方案、备选、收益与维护成本。

三种文档通过链接连接；进展记录保留时间证据，决策笔记维护当前约束，不复制整篇正文。
项目规则写在 AGENTS.md 的托管标记块之外，避免以后工具包升级覆盖。来源包 UPSTREAM.md 中提到的 `make verify-notes` 是来源项目入口，Xboard 使用 `python3 .agents/workflow.py verify`，没有新增 Makefile。

## 安装来源与升级

2026-10-17 接入 [project-decision-kit v1.0.1](https://github.com/nanashiwang/new-api/releases/tag/project-decision-kit-v1.0.1)，源码为 `nanashiwang/new-api/scripts/agent-workflow/`。
安装前验证 Release 附带的 SHA256SUMS.txt；ZIP SHA256 为 `0c7d0a40c18040667d486eb01e21ea9e16907ac2177540a4c72bb067de2a17c8`。
项目内安装清单记录工具版本及托管文件哈希；保留工具原始来源声明。

升级需使用完整 Release 分发包执行 install，先预览并审阅冲突，再加 `--apply --ci`；项目中的 `.agents/workflow.py` 用作 doctor/verify 入口，不是包含 templates/payload 的独立分发包。已有业务提案、能力地图和本说明不由升级器覆盖。

## 验证与交付边界

`Agent Workflow Notes` 在 push、pull_request 和手动触发时执行，权限仅为 `contents: read`。归档比较基线采用 PR base 或 push before；本地默认 HEAD。若需要把失败变成合并阻断，需另行配置分支保护，本次没有变更仓库保护设置。

本次只修改工具与文档，不运行支付或节点生产操作。现有 Docker CI 会在主线推送时构建并发布镜像，生产部署工作流仍需单独手动触发。仓库无 GitHub Release 工作流；若以后需要应用版本发布，需明确版本来源、标签规范、发布说明及附件清单，再接入相应流程。
