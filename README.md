# Xboard

<div align="center">

[![Telegram](https://img.shields.io/badge/Telegram-Channel-blue)](https://t.me/XboardOfficial)
![PHP](https://img.shields.io/badge/PHP-8.2+-green.svg)
![MySQL](https://img.shields.io/badge/MySQL-5.7+-blue.svg)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## 📖 Introduction

Xboard is a modern panel system built on Laravel 12, focusing on providing a clean and efficient user experience.

## ✨ Features

- 🚀 Built with Laravel 12 + Octane for significant performance gains
- 🎨 Redesigned admin interface (React + Shadcn UI)
- 📱 Modern user frontend (Vue3 + TypeScript)
- 🐳 Ready-to-use Docker deployment solution
- 🎯 Optimized system architecture for better maintainability

## 项目能力核对与进展记录

本仓库已接入 **project-decision-kit v1.0.1**。修改前先核对已有入口、权限、接口和数据来源，再记录真实方案取舍与验证结果。

- [能力地图](./docs/FEATURE_MAP.md)：按当前代码定位可复用能力、权限边界和相关检查。
- [进展记录](./progress-log.md)：保存项目反馈、排查结论、方案取舍、后续行动及验证结果。
- [决策笔记说明](./docs/AGENT_NOTES.md)与[本次接入决策](./.agents/notes/implemented/process/2026-10-17-project-decision-kit.md)：说明记录方式、工具来源和维护边界。
- 工具源码：[nanashiwang/new-api · scripts/agent-workflow/](https://github.com/nanashiwang/new-api/tree/project-decision-kit-v1.0.1/scripts/agent-workflow)；[v1.0.1 Release](https://github.com/nanashiwang/new-api/releases/tag/project-decision-kit-v1.0.1)。该版本号属于工具包。

### 四档套餐双线路规划（2026-10-21，尚未实施）

按用户后续要求，将全部 41 条第三方线路分为累计 **8 / 16 / 28 / 41** 条，分别加入轻量、标准、进阶、旗舰；叠加现有自建后目标共 **25 / 34 / 47 / 61** 条，独享保持原分配。两组区分为自建与拓展，现有售价和总额度不变；上游身份只在服务端使用，两组均由 Xboard 鉴权并按实际节点倍率计量。

已只读核对生产套餐价格和限制，并完成逐条分配清单；这是方案，尚未创建生产拓展节点。共享额度/到期、证书校验、IPv6、服务器转发和多用户计量需逐项验收；节点数量不等于独立出口或容量。见[完整规划](./.agents/notes/proposed/architecture/2026-10-21-tiered-upstream-route-family.md)和[本轮记录](./progress-log.md#2026-10-21四档套餐双线路分配规划)。

### 第三方订阅转发评估（2026-10-21）

本轮只评估外部订阅作为地区补充或备用的可行性，没有接入生产套餐。配置解析和少量 HTTPS 成功不能代表服务器中转性能或多用户承载能力；实际接入需保留 Xboard 用户鉴权与计量，并核对共享额度、倍率、到期、证书校验及上游共享限制。订阅地址、令牌、节点凭据和账户额度不写入仓库；[评估边界与验证记录](./progress-log.md#2026-10-21第三方订阅转发可行性评估)。

### 节点管理显隐与清理核对（2026-10-21）

生产 53 条节点记录由 20 条普通订阅入口、13 条固定出口订阅别名、20 条隐藏后端组成。本次逐条核对未发现无引用闲置节点，因此未删除。列表「显隐」开关控制是否进入订阅；「服务器在线」是服务器心跳状态，两者独立。隐藏后端仍须启用，供公开入口转发。用户指出的 `10.77.0.2:31006` 是「美国自建｜旗舰｜CF备用」依赖的后端，不能按显隐关闭误删；证据见[进展记录](./progress-log.md#2026-10-21节点显隐与闲置记录核对)。

### 荷兰与罗马尼亚节点已接入（2026-10-21）

`friendhosting-荷兰` 和 `friendhosting-罗马` 已加入轻量、标准、进阶、旗舰四个套餐，刷新订阅可见「荷兰｜friendhosting｜第一阶段入口」与「罗马尼亚｜friendhosting｜第一阶段入口」。第二台实际出口识别为罗马尼亚（RO），机器名保留用户原命名；四档节点数现为 **17 / 18 / 19 / 20**，独享仍仅原固定出口及香港备用。

两台均完成三名普通账号的 HTTPS 出口与 UDP DNS、独享/无效身份拒绝和旧线路抽查；两种客户端订阅共 20 项权限检查通过。本机补充检查：荷兰 4/6 次 HTTPS 成功；罗马尼亚 5/6 次 HTTPS 成功。已扩展至 20 条质量探针和 16 条入口隧道；持续采样的成功、超时与速度不等同于长期性能保证。配置和回退见[欧洲节点运维](./docs/zh-CN/installation/europe-nodes.md)，本轮证据见[进展记录](./progress-log.md#2026-10-21荷兰与罗马尼亚节点接入)。

### 日本节点已接入普通套餐（2026-10-21）

`friendhosting-日本` 已作为日本出口加入轻量版、标准版、进阶版、旗舰版，订阅节点名为「日本｜friendhosting｜第一阶段入口」，日本接入当时四档可见节点数为 **15 / 16 / 17 / 18**。独享套餐保持原固定出口及香港备用，日本节点既不出现在其订阅中，也不接受其身份转发。

复用原入口与 WireGuard，实际出口为 `185.39.31.75`；三名有效普通账号的 HTTPS / 日本出口检查及 UDP DNS、独享与无效身份拒绝、原有线路抽查均通过。节点已加入既有质量探针与入口隧道映射；本机追加测试 5/6 成功，NAS 首轮存在间歇超时，当前不能承诺长期稳定或固定速度。配置、回退与记录见[日本节点运维](./docs/zh-CN/installation/japan-node.md)、[接入决策](./.agents/notes/implemented/architecture/2026-10-21-friendhosting-japan-node.md)及[本次进展](./progress-log.md#2026-10-21friendhosting-日本节点接入)。

### 10 月 19 日 Actions 失败通知复核（2026-10-21）

当天三条失败已逐条回读 GitHub 日志：`Order Queue Checks` 是 CI 回归测试，因干净环境缺少备份目录而失败，修复后 84 项测试 / 460 断言通过；两条 `Production Deploy` 实际分别执行接入预览和开通验收，失败原因为容器缺少 `/dev/stdin`、订单尚在等待正常重试。实际部署在 16:11 成功，最终验收在 16:28 成功，不能只凭工作流名称判断部署失败。

10 月 21 日只读检查时生产容器为 Up 42 hours，公开配置接口 HTTP 200；未完成新的订单/队列统计读取，不据此宣称当前全部业务无异常。失败运行、修复提交、后续成功及验证边界见[通知复核记录](./progress-log.md#2026-10-21复核-1019-actions-失败通知)。

### 站内 Turnstile 已关闭（2026-10-21）

用户明确确认先关闭站内 Cloudflare Turnstile。生产 `captcha_enable` 已由 1 改为 0，`taige.us` 与 `board.taige.us` 的公开配置均返回关闭；后端无 token 验证通过，注册页未显示 Turnstile 组件。邮箱验证码仍保留，Cloudflare 其他防护保持现状。该操作不证明原反馈用户已经恢复，仍需其刷新页面复试。执行方式、回退值及验证边界见[关闭记录](./progress-log.md#2026-10-21按确认关闭站内-turnstile)。

### Cloudflare 验证循环排查（2026-10-21）

用户反馈浏览器持续停在人机验证并刷新。10 月 20 日深夜至 21 日凌晨的只读检查中，`taige.us` 首页、公开配置接口和浏览器注册页可访问，应用容器显示连续运行约 32 小时；脚本使用默认 User-Agent 时收到 Cloudflare `403 / 1010`，改用 `Mozilla/5.0` 后返回 200。该对照证明存在按客户端特征拦截的情况，不能直接认定为反馈用户的触发原因。

正式应用当日另有 89 条 SQLite `database is locked` 错误，抽样涉及节点探针写入；尚未与验证循环建立关联。缺少反馈用户的完整网址、Ray ID 和 Cloudflare 安全事件，具体规则及恢复状态未确认。本轮仅诊断和记录，未改安全策略或部署；证据、验证码日志边界和后续步骤见[排查记录](./progress-log.md#2026-10-21cloudflare-人机验证循环排查)。

### 自建固定出口池接入（2026-10-19）

用户确认保留固定出口分配，将现有自建线路接入出口池。实现复用 13 个去重后的美国出口，每出口五个固定套餐账号；香港作为公共备用，普通套餐继续使用原节点。200 GB、10 Mbps、价格、套餐总销售上限 15 和上架状态保持不变。

`20261019-f4f3849` 已完成双架构镜像发布、生产部署和出口池接入，相关 84 项测试 / 460 断言及 CI 通过。[生产验收](https://github.com/nanashiwang/Xboard/actions/runs/39222948840)确认：保留订单于 16:26 自动开通为 200 GB 半年套餐；订阅包含一个固定美国出口与香港备用；固定账号实际代理成功且其余 12 个池内出口拒绝访问；普通账号 13/13 线路正常。验收时 8 个出口健康、5 个尚未满足连续探测条件，只有健康出口参与分配。

健康依据为指定探针的两次独立 HTTPS / 出口 IP 观测；健康绑定保持，故障时按原规则迁移。服务器与 IP 仍供普通套餐共用，固定分配不代表物理独占或住宅 IP 认证。接入前权限快照已保存，旧镜像回退需先撤销本次新增的专属后端授权。见[接入决策](./.agents/notes/implemented/feature/2026-10-19-owned-fixed-exit-pool.md)和[进展记录](./progress-log.md#2026-10-19自建线路接入固定出口池)。

### 线上作业报错排查（2026-10-19）

正式仪表盘的七日报错持续增长，抽查的最新失败任务来自同一笔零元人工分配的专属套餐订单：出口不可用使开通事务回滚，订单仍为开通中，每分钟检查再次投递并触发任务重试。后台分配现已补上与用户购单相同的出口容量预留；失败明细也修复了只读取前 50 条导致后续页面为空的问题。相关 55 项测试 / 276 个断言通过。

用户选择保留订单等待专属出口恢复。代码将这类已识别的等待按 5 分钟间隔重试，保留开通中状态与告警日志，恢复后自动开通；其他异常仍进入失败队列。历史失败不清空，订单不取消、不换套餐。最终版本 `20261019-9d6cf40` 已完成[双架构镜像发布](https://github.com/nanashiwang/Xboard/actions/runs/39207429478)和[生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39207867717)，页面与运行镜像版本一致；首次修复上线后观察超过 10 分钟，失败计数保持 944，订单仍为开通中，队列正常。出口恢复后的真实开通尚未发生，不能将停止重复报错等同于权益交付。

部署验收同时修复构建源码随 master 前进的问题：CI 按完整提交号取源码并核验 HEAD，生产部署也核对目标镜像提交。根因、取舍及生产边界见[决策笔记](./.agents/notes/implemented/bug-fix/2026-10-19-dedicated-admin-order-failures.md)与[排查记录](./progress-log.md#2026-10-19线上作业失败与专属订单排查)。

### 流量邮件提醒（2026-10-19）

“套餐流量已用完”通知已部署：用量达到或超过 100% 后每 5 分钟检查，站点邮件提醒及用户流量提醒均开启时，每个流量周期成功发送一次。失败保留重试资格，重置流量后的新周期可以再次提醒；后台邮件模板可独立编辑。原 80% 预警和到期邮件仍每天北京时间 11:30 执行，快速用完流量仍可能错过 80% 预警。

功能提交 `c00e753`，线上版本 `20261019-c00e753`；[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39194627796)及[生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39195201349)成功，数据库迁移、运行镜像 revision、正式后台模板与队列已核对。本地 108 项测试 / 652 断言、邮件专项 CI 13 项 / 69 断言通过；项目没有 GitHub Release 工作流，本次未创建 Release。

[生产只读核验](https://github.com/nanashiwang/Xboard/actions/runs/39195993433)确认总开关开启、调度新鲜；当前耗尽用户为 0，因此真实发送、重试和成功记录均为 0。原排查账号在本次验收时已为 513.5 MB / 25 GB（约 2%），不能把没有触发邮件当作发送失败；本轮提醒逻辑不修改额度，未为测试而耗尽账号或覆盖提醒偏好，也未声称收件箱投递成功。实现和验证边界见[决策笔记](./.agents/notes/implemented/bug-fix/2026-10-19-traffic-exhausted-reminder.md)与[本次记录](./progress-log.md#2026-10-19流量耗尽邮件提醒)。

### 本机节点可测延迟但无法联网（2026-10-19）

本轮排查确认本机订阅账户的流量已耗尽：正式后台显示已用 **25.1 GB / 25 GB（100.4%）**，订阅即时状态为上传 12.81 GB、下载 12.29 GB、剩余 0；套餐有效至 2027-09-17。入口可建立连接不代表账号获准转发，服务端只下发 `u + d < transfer_enable` 的有效用户。固定本机同账号测美国 01、02、CN2 和香港线路，48 次海外 HTTPS 全部失败；当前第三方节点对照 12/12 成功，同账号在入口服务器内绕过本地公网段仍立即断开。详见[本轮诊断证据](./progress-log.md#2026-10-19本机订阅流量耗尽诊断)。

本轮仅完成诊断，未重置流量、调整套餐、修改客户端或生产网络。恢复需按账户政策补充或重置额度，再用相同账号复验真实网站；本次未完成恢复验收，也不据此否定此前已记录的链路波动。独立监控账号的可用性不能代表这个已耗尽账户，边界见[探针决策](./.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)。

### 第一段入口分层监控（2026-10-19）

节点质量页增加「探测位置到第一段」「入口机器资源」「入口到出口隧道」三组证据，与原完整代理线路对照。NAS 探针版本升级为 1.1.0；共享入口每轮只测一次，机器显示 CPU、内存、物理网卡实际收发，各节点显示对应 peer 的 RTT、3 包丢包和握手时间。入口历史在页面内展示；数据过期显式标记，未绑定入口不借用其他机器结果，不自动断言慢速根因。配置方式和指标边界见[入口监控文档](./docs/zh-CN/installation/node-probes.md#第一段入口机器资源与出口隧道)与[决策笔记](./.agents/notes/implemented/feature/2026-10-19-ingress-observability.md)。

已接入正式后台：NAS 1.1.0 持续检测 17 条线路，第一段独立采集器覆盖 13 条出口隧道，4 条 CF 备用明确显示未绑定入口。当前运行 revision `2b8c615`（后台版本 `20261019-2b8c615`）已完成双架构镜像发布和生产部署，并修复节点质量空白加载、增加失败重试；入口超时、成功样本及机器资源均已写入历史。本地 PHP 18 项 / 106 断言与真实内核 Python 12 项通过；构建与现场证据见[本次进展](./progress-log.md#2026-10-19第一段入口分层监控)。

### 节点质量探针（2026-10-18）

正式 Xboard 后台已上线节点质量看板，NAS 探针首次以 1.0.2 常驻并通过三轮生产上报验收（当前已升级 1.1.0），持续检测 17 条公开线路；已发现并展示部分上下行超时。独立监控账号为非管理员、100 Mbps、30 GiB 总额度、有效期至 2027-10-18。上一轮页面交付运行 revision `f09a440`，后台显示版本 `20261018-f09a440`；首次 NAS 接入证据见[采样记录](./progress-log.md#2026-10-18正式后台上线与-nas-接入)，当前页面交付见[页面验收](./progress-log.md#2026-10-18节点质量改为后台完整页面)。


Xboard 独立探针统一由侧栏「节点质量」进入，在后台主内容区展示完整页面；仪表盘不再重复显示监控卡片。可查看各位置的真实代理 HTTPS 成功率、延迟、上下行小样本速率与完成率，以及故障/恢复记录。探针失联、账号不可用和配置错误不会继续显示正常；不发送外部通知。首个探针按用户指定常驻家庭 NAS；数据按探测位置统计。节点历史在页面内查看并可返回列表，探针管理继续保留。展示方式及兼容边界见[页面简化决策](./.agents/notes/implemented/simplification/2026-10-18-node-quality-page.md)；本地 13 项探针接口测试、深浅主题和 390px 窄屏验收通过；双架构镜像、CI 与生产部署完成。正式后台已验证首页去重、17 条节点、页面内历史及长列表滚动。

默认每轮后等待 60 秒，每节点每 30 分钟各上传/下载 256 KiB；17 节点仅传输载荷约 408 MiB/天，另有协议开销。应使用独立监控账号，数据不能代表所有运营商或线路带宽上限。安装、权限、指标口径和运维见[探针文档](./docs/zh-CN/installation/node-probes.md)、[决策笔记](./.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)及[进展记录](./progress-log.md#2026-10-18xboard-节点质量探针实施)。

### 节点监控覆盖核对（2026-10-18）

已有服务器心跳、资源与收发速率监控，后台可查看 1–24 小时趋势；它们不能证明用户经过入口后的访问稳定性。公开节点状态沿用隐藏后端心跳，2026-10-18 核对时新入口 143.203.200.5 未列入服务器管理；已核对的新入口服务、计时器和 root cron 中未发现 VPN 全链路持续探测。独立 Flawless 流量页面监控的是另一台业务跳板。现有掉线通知命令未注册在仓库主调度表，线上独立调度与通知送达尚未核验。具体覆盖、代码边界与建议探测方法见[监控核对记录](./progress-log.md#2026-10-18节点稳定性监控覆盖核对)；该核对轮次没有部署或启用新监控；后续分层接入见上方 2026-10-19 记录。

### 当前节点稳定性复测（2026-10-17 晚间）

23:09–23:14 连续约 5 分钟主测，仍使用「美国自建｜02｜第一阶段入口」，新入口 143.203.200.5、出口 192.220.36.213。海外小请求 **46/60 成功、14 次 CONNECT / TLS 超时**；1 MiB 上传 5/5 完成，下载 4/5 完成，当前连接不能判为稳定。同账号从入口服务器经相同出口的 36 次对照全部成功，入口到出口隧道 300 包零丢包；本地网关虽无丢包，但最高延迟约 345 ms。问题重点在本地网络、客户端及到入口的公网链路，尚未定位到其中某一处。完整采样口径、前置失败样本和后续对照建议见[稳定性记录](./progress-log.md#2026-10-17晚间美国-02-节点稳定性复测)。

### 当前节点速度复测（2026-10-17 晚间）

重连后客户端选中「美国自建｜02｜第一阶段入口」，实际仅连接新入口 143.203.200.5，出口为 192.220.36.213。当前账号后台限速为 **10 Mbps（约 1.25 MB/s）**；同账号服务器侧 16 MiB 上传实测 9.92 Mbps。真实 Shadowrocket 单连接上传为 1.33–5.49 Mbps、下载为 4.80–5.56 Mbps（含连接开销），四连接下载合计 7.43 Mbps。到新入口的公网 TCP 连接仍有约 190 ms 延迟及明显重传，入口到出口隧道短测无丢包。本次未调整限速或网络配置，完整口径、无效样本和后续步骤见[速度复测记录](./progress-log.md#2026-10-17晚间新入口上传下载复测与账号限速核对)；前次旧入口故障记录继续保留，不能代表重连后的状态。

### 当前反馈与结论（2026-10-17）

用户要求让项目反馈和验证证据随 GitHub 仓库保存，并在完成后回读核对。排查确认：已有业务代码和运维文档可复用，原先缺少统一能力索引及笔记校验；`composer.json` 使用 Laravel 12，本文两处 Laravel 11 的旧说明已修正。

采用“README 当前摘要 + progress-log 逐次证据 + 原有笔记树记录决策”的方式，补全能力地图，并使用独立的 `Agent Workflow Notes` CI。选择独立校验是为了让笔记检查不依赖 PHP 服务、数据库或 Docker 镜像构建；具体备选及代价见接入决策。

工具包下载、完整性、笔记结构、6 项校验行为和 105 个文档链接检查均通过；[笔记 CI](https://github.com/nanashiwang/Xboard/actions/runs/38975255703) 与[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/38975255672)均成功，GHCR 的 amd64/arm64 镜像 revision 与实施提交 `015240b` 一致。首次推送后已从 GitHub 完整回读 README 与 progress-log，内容与提交一致。详细证据和后续事项见[进展记录](./progress-log.md)。后续每次改动需同步相关记录，并执行：

```bash
python3 .agents/workflow.py doctor
python3 .agents/workflow.py verify
```

运行需要 Python 3.9+ 和 Bun（CI 固定 1.3.14）；新电脑克隆仓库即可获得校验器，无需全局 Skill。现有 Docker 工作流会在推送主分支时构建镜像，生产部署需单独手动触发。仓库目前没有 GitHub Release 与安装包发布流程；本次仅接入工具和文档，未执行生产部署。

### VPN 第一阶段已迁移（2026-10-17）

第一阶段当前由 `143.203.200.5` 承担，`hk.taige.us:443` 已切到新 IP，取代此前由香港机器承担入口的配置。新入口通过独立 WireGuard 隧道连接原 12 个美国出口和 1 个香港出口，原出口 IP、公开节点 ID、用户身份和订阅地址保持不变；4 条 CF 备用保留。用户更新原订阅后可选择「第一阶段入口」线路。

新机已关闭 SSH 密码/键盘交互认证，使用原密钥登录，启用 Fail2ban 和默认拒绝入站防火墙。切换前按新 IP、切换后按原域名各完成 13 条严格 TLS HTTPS 出口和 UDP DNS 验证；第二个付费用户抽查和错误身份拒绝通过，套餐节点数仍为 **14 / 15 / 16 / 17**。原香港入口和旧隧道保留作回退；不将本次验收等同于大陆测速、长期稳定性或全部客户端兼容验证。

配置、证书维护与回退见[第一阶段运维](./docs/zh-CN/installation/vpn-stage1.md)、[决策笔记](./.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)和[验证记录](./progress-log.md)。本次只调整生产配置并同步运维文档，不更新应用版本或创建 GitHub Release。

### 安卓 Clash Meta 下载等待排查（2026-10-18）

手机日志确认两类异常：`services.googleapis.cn` 被 `.cn → DIRECT` 规则提前匹配，约 31 秒内出现 38 次 DNS 失败；另有 1 次入口 TCP 建连超时和 2 次 UDP 代理客户端建立超时。仓库默认 Clash 模板的规则顺序与日志一致，服务器侧独立 DNS 查询能解析该 Google 域名。该采样实际是规则模式和美国 01，没有覆盖用户另述的全局 / CN2 对照，也未捕获视频或应用包下载请求，因此尚不能把全部故障归为单一原因。证据、修复方向与验收边界见[安卓下载排查记录](./progress-log.md#2026-10-18安卓-clash-meta-下载等待日志排查)。后续修复已更新线上 Clash Meta 模板：Google 域名优先分流、双境外 DoH 经所选代理组、节点域名独立解析。实际重新下载的订阅通过双版本内核检查，美国 02 / CN2 的有限下载和 YouTube 连通性复测成功；用户已在安卓手机更新订阅并重连后确认：Play 下载与 YouTube 视频均恢复。实现与取舍见[修复笔记](./.agents/notes/implemented/bug-fix/2026-10-18-clashmeta-google-dns.md)，新安装默认使用 [Clash Meta 模板](./resources/rules/default.clashmeta.yaml)。 构建与手机验收状态见[修复交付记录](./progress-log.md#2026-10-18clash-meta-google-分流与代理-dns-修复)。

## 🚀 Quick Start

```bash
git clone -b compose --depth 1 https://github.com/cedar2025/Xboard && \
cd Xboard && \
docker compose run -it --rm \
    -e ENABLE_SQLITE=true \
    -e ENABLE_REDIS=true \
    -e ADMIN_ACCOUNT=admin@demo.com \
    web php artisan xboard:install && \
docker compose up -d
```

> After installation, visit: http://SERVER_IP:7001  
> ⚠️ Make sure to save the admin credentials shown during installation

## 📖 Documentation

### 🔄 Upgrade Notice
> 🚨 **Important:** This version involves significant changes. Please strictly follow the upgrade documentation and backup your database before upgrading. Note that upgrading and migration are different processes, do not confuse them.

### Development Guides
- [Plugin Development Guide](./docs/en/development/plugin-development-guide.md) - Complete guide for developing XBoard plugins

### Deployment Guides
- [服务器快捷管理菜单（中文）](./docs/zh-CN/installation/server-manager.md) - 输入 `xboard` 更新、重启、查看状态或卸载服务
- [Deploy with 1Panel](./docs/en/installation/1panel.md)
- [Deploy with Docker Compose](./docs/en/installation/docker-compose.md)
- [Deploy with aaPanel](./docs/en/installation/aapanel.md)
- [Deploy with aaPanel + Docker](./docs/en/installation/aapanel-docker.md) (Recommended)

### Migration Guides
- [Migrate from v2board dev](./docs/en/migration/v2board-dev.md)
- [Migrate from v2board 1.7.4](./docs/en/migration/v2board-1.7.4.md)
- [Migrate from v2board 1.7.3](./docs/en/migration/v2board-1.7.3.md)

## 🛠️ Tech Stack

- Backend: Laravel 12 + Octane
- Admin Panel: React + Shadcn UI + TailwindCSS
- User Frontend: Vue3 + TypeScript + NaiveUI
- Deployment: Docker + Docker Compose
- Caching: Redis + Octane Cache

## 📷 Preview
![Admin Preview](./docs/images/admin.png)

![User Preview](./docs/images/user.png)

## ⚠️ Disclaimer

This project is for learning and communication purposes only. Users are responsible for any consequences of using this project.

## ❤️ Support The Project

If this project has helped you, donations are appreciated. They help support ongoing maintenance and would make me very happy.

TRC20: `TLypStEWsVrj6Wz9mCxbXffqgt5yz3Y4XB`

## 🌟 Maintenance Notice

This project is currently under light maintenance. We will:
- Fix critical bugs and security issues
- Review and merge important pull requests
- Provide necessary updates for compatibility

However, new feature development may be limited.

## 🔔 Important Notes

1. Restart required after modifying admin path:
```bash
docker compose restart
```

2. For aaPanel installations, restart the Octane daemon process

## 🤝 Contributing

Issues and Pull Requests are welcome to help improve the project.

## 📈 Star History

[![Stargazers over time](https://starchart.cc/cedar2025/Xboard.svg)](https://starchart.cc/cedar2025/Xboard)
