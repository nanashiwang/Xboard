# Agent Note: 接入能力核对与决策记录工具包

Status: implemented

## Problem

项目已有业务代码、运维说明和一篇本地网络方案提案，但缺少可迁移的能力索引、笔记校验入口和自动检查。用户要求将反馈、排查结论、方案取舍、后续行动及验证结果记录到 README.md 与 progress-log.md，并在完成后回读核对。

## Decision

项目使用从 nanashiwang/new-api 的 project-decision-kit-v1.0.1 Release 安装的工具包，下载包通过 SHA256 校验。Xboard 的 master 主线与原有提交、发布约定保持有效。复用现有笔记树，增加独立只读 CI，不改 Docker 发布与生产部署流程。

[README.md](../../../../README.md) 保存当前结论和导航；[progress-log.md](../../../../progress-log.md) 保存每次工作的证据与待办；[能力地图](../../../../docs/FEATURE_MAP.md)从代码入口、权限、服务和数据源建立索引；非平凡取舍留在同一笔记树中并互相链接。项目特有的记录和回读约定放在 AGENTS.md 托管块之外，以保留升级兼容性。

## Existing decision audit

检索 `.agents/notes/` 的 proposed、implemented、rejected 状态及 docs 后，发现唯一既有笔记涉及香港入口与 WireGuard，是与本次流程接入无关的本地未提交提案。保留原文和未提交状态，不复制其部署结论，不将其纳入本次提交。现有安装文档作为能力地图的参考入口，不迁移到新记录体系。

## Alternatives considered

- 只在 README.md 和 progress-log.md 中手工记事：入口集中且无需额外运行时，但不能满足工具包提供的结构、链接和归档自动校验，因此保留这两个入口，同时接入校验工具。
- 使用本机已安装的 project-workflow 1.0.0：可离线安装，但用户提供的是已发布的 1.0.1，后者名称与说明更准确；采用可核验的 Release 包，不修改全局 Skill。
- 将笔记检查并入 Docker 构建：少一个工作流，但文档校验将与镜像权限、构建耗时耦合；采用工具包原装独立 CI，权限仅为 contents: read。

## Verification

安装预览无冲突，doctor 与 verify 通过，重复安装预览不产生写入计划。能力地图按当前路由和代码核对，原有本地未提交提案不属于本次提交。有效/无效笔记、链接、归档、安装保护及远程回读的最终结果与证据统一记录在 [progress-log.md](../../../../progress-log.md)。

## Consequences

新电脑克隆仓库即可获得规则、模板、能力索引和相同版本的校验器；证据与设计约束可相互追溯。代价是 Python 与 Bun 的文档校验依赖，以及能力地图、README 摘要和进展记录的维护工作。升级保留项目文档，若工具托管文件有自定义修改，需先比较再合并，不能覆盖。

结构校验不判断业务正确性，CI 未配置为分支保护时不强制阻止直接推送。当前仓库只有镜像构建发布流程，没有 GitHub Release 及安装包发布流程；本次不将工具包版本当成 Xboard 应用版本，也不执行生产部署。新增发布需求时再明确版本来源、标签和附件；业务改动仍需执行对应 PHP、运维或浏览器验收。
