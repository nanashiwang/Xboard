# Xboard 项目进展记录

本文件保存项目反馈、排查结论、方案取舍、后续行动及验证结果。当前摘要见 [README.md](./README.md)，代码索引见[能力地图](./docs/FEATURE_MAP.md)，详细取舍链接到[决策笔记说明](./docs/AGENT_NOTES.md)中的统一笔记树。记录日期使用 Asia/Shanghai。

每次完成后先回读本地文档，再在推送后按提交版本从 GitHub 回读 README.md 与 progress-log.md。未运行的检查、未完成的构建、未发布的版本和未部署的代码须明确区分；不记录密钥或用户凭据。

## 2026-10-17：接入 project-decision-kit v1.0.1

### 项目反馈

用户提供 `nanashiwang/new-api` 的项目能力核对与决策记录工具包，要求修改前复用已有能力，保存方案取舍和验证结果，并要求将反馈、排查、后续行动及验证写入 README.md 和本文件，完成后回读。

### 排查结论

- 业务代码核对基线为 `61919aa`，工作分支是 `master`，远程为 `nanashiwang/Xboard`。已有 Laravel 业务接口、客户端认证/下载、专属出口、支付插件及运维说明，新增需求应先沿[能力地图](./docs/FEATURE_MAP.md)检索。
- 原先无 `docs/FEATURE_MAP.md`、统一笔记校验或本进展文件；已有一篇本地未提交网络方案提案，属于其他任务，原文保留且不纳入本次提交。
- `composer.json` 声明 Laravel ^12.0，README 两处 Laravel 11 旧说明已改为 12。管理前端子模块未在当前检出中展开，本次未进行界面或线上业务验收。
- GitHub API 核实工具包最新版本为 `project-decision-kit-v1.0.1`；Release 提供 ZIP 和 SHA256SUMS.txt，实际下载校验一致。来源及摘要见[安装说明](./docs/AGENT_NOTES.md)。
- Xboard 现有 `Docker Build and Publish` 会在 master 推送时构建 amd64/arm64 镜像；`Production Deploy` 仅手动触发。查询 Xboard Releases 列表为空，仓库没有 GitHub Release/安装包发布工作流。

### 方案取舍与已完成改动

采用工具包原装安装器和独立笔记 CI，保留原有 master 提交、镜像构建、部署规则和未提交提案。README 维护当前摘要，本文件保存逐次证据，能力地图提供检索入口，原有笔记树保存设计约束。

相比仅手工写 README，自动校验可发现结构与链接问题；相比将校验放进 Docker CI，独立流程无需镜像发布权限或业务运行时。代价是新增 Python/Bun 校验环境与文档维护工作。完整备选和边界见[本次接入决策](./.agents/notes/implemented/process/2026-10-17-project-decision-kit.md)。

### 验证结果

- Release ZIP 的 SHA256 与发布校验文件一致。
- 安装前预览无冲突；安装后 `python3 .agents/workflow.py doctor` 和 `python3 .agents/workflow.py verify` 通过：本地共 2 篇笔记，目录、格式、相对链接和归档校验通过。其中本次接入笔记已转为 implemented；另一篇原有提案保持原文与未提交状态。
- 临时目录中的 6 项校验行为检查通过：合法笔记和合法归档被接受；缺少备选方案、失效相对链接、归档内容篡改、托管文件修改均被拒绝。临时样例不写入项目。
- 再次运行安装器 `install --apply --ci` 没有写入，相关文件哈希全部不变；原有提案 SHA256 也与接入前一致。
- 本次文档中的 105 个本地链接目标存在；`git diff --check` 通过。README 与本文件已在本地回读，核对工具版本、能力边界、待办和验证记录一致。
- 暂存快照单独校验通过：只包含本次 1 篇接入笔记，105 个文档链接有效；原有未提交提案未混入。该临时快照不含 Git 元数据，归档历史对比由实际仓库与下述 CI 使用 Git 基线验证。
- 本次没有业务代码变更，不运行 PHP 业务测试或生产请求；管理界面、真实支付和节点连通性没有在本次验收。
- 实施提交 [`015240b`](https://github.com/nanashiwang/Xboard/commit/015240b7849cc19e21d24c6abbcf5d064da79ef8) 已推送至 `origin/master`。
- [Agent Workflow Notes #38975255703](https://github.com/nanashiwang/Xboard/actions/runs/38975255703) 成功：验证 1 篇已提交笔记，使用前一提交 `61919aa` 作为归档比较基线。运行日志提示来源包的 checkout/setup-python Action 使用已弃用的 Node.js 20 声明，runner 强制以 Node.js 24 执行并成功；本次保留来源包版本，后续升级时复核兼容性。
- GitHub Contents API 按实施提交完整回读 `README.md` 和 `progress-log.md`，逐字节与本地文件比对一致；远程 master 当时指向同一提交。结果补记后继续执行最终回读。
- [Docker Build and Publish #38975255672](https://github.com/nanashiwang/Xboard/actions/runs/38975255672) 已成功。GHCR 实际读取确认 `ghcr.io/nanashiwang/xboard:015240b` 包含 linux/amd64 与 linux/arm64，两者 OCI revision 均为 `015240b7849cc19e21d24c6abbcf5d064da79ef8`；清单摘要 `sha256:1e7ae3bc16db8001917f2e32bf06f9a6c254697f350bf25bdca58eb6a0144e57` 与 CI 一致。第一次读取遇到 TLS 握手超时，重试成功。
- 流水线版本步骤输出 `20261016-015240b`，日期来自 runner 的 UTC 时间；本记录日期为北京时间 2026-10-17。该输出不替代镜像内应用版本或生产运行版本验收，镜像交付以已核对的 revision 与摘要识别。

### 后续行动与交付状态

- 本地检查、实施提交、推送、笔记 CI、镜像发布及首次 GitHub 回读已完成。结果补记仅修改 README 与本文件，使用中文文档提交并带 `[skip ci]`，避免重复构建同一业务代码；最终推送后再次按远程 master 回读比对，终态在本次交付回复中报告。
- 后续业务改动按能力地图定位，更新对应记录并执行相关测试；结构检查不能代替支付结算、节点连通、权限或浏览器验收。
- 如需强制合并门禁，应另行配置分支保护；如需 GitHub Release，应先补齐版本来源、标签规范、中文说明和附件发布流程。
- 工具包版本：**v1.0.1**；Xboard 源码版本：本次不手动调整，镜像沿用既有流水线自动生成版本；GitHub Release：本次不创建；生产部署：本次未执行。
