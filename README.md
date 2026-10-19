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

### 线上作业报错排查（2026-10-19）

正式仪表盘的七日报错持续增长，抽查的最新失败任务来自同一笔零元人工分配的专属套餐订单：出口不可用使开通事务回滚，订单仍为开通中，每分钟检查再次投递并触发任务重试。后台分配现已补上与用户购单相同的出口容量预留；失败明细也修复了只读取前 50 条导致后续页面为空的问题。相关 55 项测试 / 276 个断言通过。

用户选择保留订单等待专属出口恢复。代码将这类已识别的等待按 5 分钟间隔重试，保留开通中状态与告警日志，恢复后自动开通；其他异常仍进入失败队列。历史失败不清空，订单不取消、不换套餐。当前为本地修复，生产生效须部署后另行验证。根因、取舍及生产边界见[决策笔记](./.agents/notes/implemented/bug-fix/2026-10-19-dedicated-admin-order-failures.md)与[排查记录](./progress-log.md#2026-10-19线上作业失败与专属订单排查)。

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
