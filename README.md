# Xboard

<!-- singbox-template-20261030:start -->
### sing-box 默认订阅兼容修复（2026-10-30）

香港入口历史记录中的完整订阅失败已在本地复现：旧 DNS 格式首先被 sing-box 1.13.19 拒绝，只修 DNS 后旧入站字段仍报错。默认模板现采用现代 DNS 与路由动作，并补齐旧内核降级；节点、TLS、私网/国内直连及代理组语义保留。五个真实内核（1.9.7/1.10.7/1.11.0/1.12.0/1.13.19）配置检查和相关 37 项 PHP 测试通过。

**已有安装从数据库读取模板，不会随代码升级自动替换；生产配置未修改，线上完整订阅尚未复验。** 扩展测试发现原下载目录代码 0.1.5 与 manifest 0.1.9 不一致，5 项失败留在原范围。原因、回归与交付状态见[修复决定](./.agents/notes/implemented/bug-fix/2026-10-30-singbox-template-compat.md)和[进展](./progress-log.md#2026-10-30sing-box-默认订阅兼容修复)。

实现 `1005bf7` 已推送 master；[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/41000180490)成功，镜像标签 `1005bf7`（流水线编号 `20261030-1005bf7`），未部署。[远端检查](https://github.com/nanashiwang/Xboard/actions/runs/41000180502)的订阅专项 9 项 / 236 断言通过，全套 Desktop 因上述下载目录问题失败；笔记与探针 CI 通过。无服务端 GitHub Release。
<!-- singbox-template-20261030:end -->

<!-- residential-capacity-20261030:start -->
### 管理看板家宽订阅与容量（2026-10-30）

后台仪表盘新增“家宽订阅与容量”：独享套餐展示有效订阅、已分配人数、订单预留、当前可新增和逐IP占用；共享家宽另列授权订阅人数，合并同后端别名，同一账号跨节点不累加。有效订阅包含未封禁未到期及永久用户，流量耗尽仍占订阅；续费不重复计人。可新增沿用真实分配的健康、备用、每出口五名额、套餐上限和停售规则，异常或过期健康不会冒充可售容量。

仅管理员可读，每60秒或手动刷新，失败清除旧数字，未改套餐、分配或节点状态。本地94项PHP、5项前端、桌面/窄屏/深色及退出登录交互和远端CI通过；[双架构镜像](https://github.com/nanashiwang/Xboard/actions/runs/40999949564)已发布，提交6e077e3。生产尚未更新：主分支还有要求不部署的并行订阅修复与既有下载目录错误，待用户确定整镜像上线范围。详见[进展](./progress-log.md#2026-10-30家宽订阅与出口容量看板)及[统计口径决定](./.agents/notes/implemented/feature/2026-10-30-residential-capacity-dashboard.md)。
<!-- residential-capacity-20261030:end -->

<!-- upstream-disappearance-20261028:start -->
### 外接线路故障现状（2026-10-28）

16:25–16:34 复核：41 条外接线路中 31 条已被保护器撤下，四档普通套餐剩余可见外接数为 **0/0/2/10**；剩余 10 条的双目标 HTTPS 实测也全部失败，不能视为可用。上游来源、地址和证书公钥变化与既有固定配置不一致；入口服务、IPv6 出网和保护定时器正常，额度/到期有效。15:18 美国出口替换前已是相同撤下状态，本次美国替换没有改变外接节点启用状态或套餐权限。

本轮仅诊断及候选观察，没有更新身份、重新上架或修改生产配置。后续须核对最新来源/证书并完成实际公开路径验收；当前运行时证书保护仅覆盖 28 条 AnyTLS，不能把其他协议仍显示当作健康。详见[证据与恢复边界](./progress-log.md#2026-10-28外接节点消失与全量不可用复核)及[既有决定](./.agents/notes/implemented/architecture/2026-10-21-tiered-upstream-route-family.md)。
<!-- upstream-disappearance-20261028:end -->

<!-- us-retirement-20261028:start -->
### 美国出口已更换（2026-10-28）

四档普通套餐的美国01/02现为 **216.36.108.128 / 192.220.24.147**；独享套餐仅保留 **216.36.108.173**（美国10）及香港备用。原两个普通美国与其他旧独享出口已撤权停用，记录保留；一个既有独享绑定已迁移，容量从15收敛为5，价格与用户权益不变。客户端需更新原订阅。此条为当前配置，后文10月21/22日的十三出口数量为历史记录。

[最终生产验收](https://github.com/nanashiwang/Xboard/actions/runs/40655295874)通过：五档实际订阅、37项代理/拒绝、9项QA撤权；30个原账号、5套餐、55订单对照一致（仅授权容量调整）。七条保留线路的监控已同步，最终固定出口健康；NAS仍有间歇请求超时，本次不声称消除长期波动。服务商自动续费开关未操作。本轮无应用/客户端新版本或Release。见[决定](./.agents/notes/implemented/architecture/2026-10-28-owned-us-retirement.md)、[固定出口运维](./docs/zh-CN/installation/dedicated-exits.md)和[进展](./progress-log.md#2026-10-28美国出口退租与替换)。
<!-- us-retirement-20261028:end -->

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

### 办公网域名自动直连（2026-10-27）

用户反馈办公网站退出客户端后可访问，其他客户端 PAC/系统代理正常，并指出不应要求用户修改电脑配置。0.1.11修复域名解析到内网地址时被 no-resolve 规则漏过的问题：规则与全局自动直连内网，全局公网仍走已选节点；直连默认系统 DNS，保留订阅显式解析设置。公司域名与访问参数不写入代码或文档。仅企业 DNS 可解析的域名仍可能需要显式直连规则；不把隔离复现当成用户故障电脑的完整根因确认。见[决定](./.agents/notes/implemented/bug-fix/2026-10-27-capybara-private-network-routing.md)和[进展](./progress-log.md#2026-10-27办公网域名自动直连)。本地前端75/脚本16/Rust59及构建通过；[四目标构建](https://github.com/nanashiwang/Xboard/actions/runs/40479066479)与[0.1.11正式Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.11)已完成，18附件摘要、四目标签名与固定提交源码包已核验。官网/应用内更新源未同步，Windows公司网络仍待升级复测。

### 切换分流模式保留节点（2026-10-27）

用户要求切换规则时保持已选节点。0.1.10在规则与全局间带入内核当前实际节点，经过直连仍保留选择；只同步首页当前规则组，其他组不变。模式与节点一起加载，保存失败恢复切换前完整选择。自动组保留自身策略，组不包含目标时明确报错；已有连接仍可能沿用原出口。见[修复决定](./.agents/notes/implemented/bug-fix/2026-10-27-capybara-mode-selection.md)和[进展](./progress-log.md#2026-10-27切换分流模式保留节点)。本地前端75项、脚本16项、Rust57项及构建通过；[四目标构建](https://github.com/nanashiwang/Xboard/actions/runs/40471554545)与[0.1.10 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.10)已完成，18附件摘要、四目标签名及固定提交源码包核验通过。官网与应用内更新源尚未同步，用户实机使用待验证。

### Windows 本机调用502修复（2026-10-27）

用户随后反馈元衡本地15721返回裸502 Unknown error。本轮系统/已安装版本确认尚未收到，按此前Windows场景审查并复现另一缺陷：0.1.8修复单地址后，原生HTTP应用能识别系统代理，但没有显式回环例外时，Codex到元衡的本机请求也会进入Mihomo，全局模式可返回空502。上一轮只测了外网代理匹配，漏了本机URL路径；不能把裸502直接归为OpenAI上游。

0.1.9保留原代理例外并补齐localhost/IPv4/IPv6本机地址，断开恢复原值，兼容旧恢复记录并保留用户后来修改的例外。真实matcher和隔离Mihomo对照证明本机请求需绕过代理、chatgpt.com仍需代理；用户故障电脑尚未复验。检查、发布与更新源状态见[进展](./progress-log.md#2026-10-27windows-本机调用502修复)，沿用[Windows兼容决定](./.agents/notes/implemented/bug-fix/2026-10-27-capybara-windows-proxy-compat.md)。

[0.1.9正式Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.9)已完成四目标构建、18附件与4目标签名核验，Windows原生61项通过。应用内更新源已同步0.1.9，两域索引、12文件摘要、4签名及10次Range均通过；升级后连接卡皮巴拉，再保存工作并完整退出重开Codex，避免沿用已缓存的旧代理设置。用户电脑的真实调用仍待复验。

### Windows 原生应用代理兼容修复（2026-10-27）

用户确认同一节点在 v2rayN 正常，而卡皮巴拉规则/全局模式下 YuanHeng 的 Codex /responses 连接超时，浏览器正常。已用 YuanHeng 锁定的真实网络库复现：旧 Windows 分协议 ProxyServer 无法被当作单个代理地址解析，可能绕过代理直连。0.1.8 改用统一回环地址，并兼容恢复旧格式；没有据通用错误提示调整 DNS 或节点。升级后断开再连接应用新设置，故障电脑的真实请求仍待复验。

本地前端74项、脚本16项、Rust53项及类型/构建通过；Windows CI54项通过，四目标构建完成。[0.1.8正式Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.8)的18附件、四目标签名和GitHub上传摘要均已核验，包含0.1.7的节点点击连接改进。应用内更新源已同步0.1.8，两域索引一致，12文件SHA、4目标签名和10次Range通过；官网PHP下载页未部署。完整状态见[进展](./progress-log.md#2026-10-27windows-原生应用代理兼容修复)与[修复决定](./.agents/notes/implemented/bug-fix/2026-10-27-capybara-windows-proxy-compat.md)。

### 卡皮巴拉点击节点即连接（2026-10-27）

本次 Windows 全局模式 IP 未变，用户确认点击“一键连接”后正常，原因是尚未连接。按新交互要求，0.1.7 点击首页右侧节点就连接；已经连接时直接切换，断开后点击当前节点也能恢复，主按钮仍可手动连接/断开并跟随真实状态。选择和开启代理由原生统一处理，失败不误连旧节点；自动加载、测速及仅切模式不自动连接。

本地前端74项、网页/发布脚本16项、Rust51项通过（1项既有手动钥匙串测试忽略），类型检查、构建及界面模拟通过；Windows真实使用仍待新版安装后验证。[0.1.7正式Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.7)四目标构建和18附件/签名/源码已核验，官网应用更新源已同步0.1.7并通过23项公开下载核验；完整状态见[进展](./progress-log.md#2026-10-27卡皮巴拉点击节点即连接)，取舍见[决定](./.agents/notes/implemented/feature/2026-10-27-capybara-select-connect.md)。本次反馈与此前美国01连接差异不混为同一已解决问题。

### Actions 部署与维护失败复核（2026-10-27）

近期失败记录来自手动维护或预检阶段：早期私有清单、探针读权限、TLS默认值与输入流问题已有对应修复；后续预检遇到上游超时、不可达或来源变化仍按约定失败退出。10:21保护器状态检查、10:23维护环境检查均成功，定时器active、服务Result success，10:24公开路径实测36条可用、5条撤下拒绝，工作流成功不等于所有线路恢复。运行标题现包含具体operation和分支，上游维护/运行时部署工作流文件改动也触发专项回归。流程改动`4f3379d`已推送master，专项回归、管理脚本、笔记CI与双架构镜像构建均通过；未重新部署应用或发布客户端版本。逐项证据、当前验收与交付状态见[复核记录](./progress-log.md#2026-10-27actions-部署与维护失败复核)。

### 运行时保护器生产部署（2026-10-27）

用户已要求部署新版。面板没有IPv6，因此采用实际入口执行证书握手、面板保留元数据和受限撤下事务的方式；专用SSH身份只允许固定检测命令，固定主机公钥，请求/响应绑定nonce、摘要和完整节点范围。新版运行时保护器已于北京时间09:24部署，28条AnyTLS每轮从实际入口验证，服务执行成功、timer active；文件摘要与提交一致。当前U08超时、U32不可达，U06/U07/U32/U41来源指纹变化，合计5条继续撤下；新加坡U04正确pin通过、合成错误pin明确拒绝。批准来源/pin未变，保留代码回退，不自动恢复；09:27公开路径验收36条、72次HTTPS全通过（含两条新加坡）；另5条确认实际拒绝，不能说41条全部恢复。09:29自然定时执行再次成功，故障范围与批准公钥保持。见[部署记录](./progress-log.md#2026-10-27新版运行时保护器部署)。

### 生产外接线路恢复（2026-10-27）

北京时间05:59的恢复验收中，授权范围内41条外接线路完成生产修复并恢复原订阅显示：39条修复线路发布前、发布后各完成78次严格HTTPS请求，另两条健康线路发布后4次请求通过，最终41/41、82/82通过；新加坡两条包含在内。首轮23条地址与34条pin的重叠变更集合已核准，维护期间发生的5条、22条再次公钥变化均单独复核后补修；3条公共CA线路保留CA校验，权限、倍率、用户身份和自建线路保持。28条AnyTLS批准映射已从发布后验证一致的数据库同步，原始出站备份与限定回退保留；客户端可更新Xboard订阅后重连，可见数量仍按套餐权限。

上游本次多次呈现不同公钥，因此这是本轮实测恢复，不代表长期稳定问题已消除；以后新身份仍须人工核验，不能靠刷新客户端自动接纳。该次运行时只读实测28/28通过；09:24新版自动守护已启用并撤下后来异常的5条线路，当前可用性以上方部署记录为准。完整时间、回执、回退边界与检查状态见[进展](./progress-log.md#2026-10-27生产外接线路人工恢复)。

### 卡皮巴拉订阅更新（2026-10-27）

0.1.6 在首页节点面板提供“更新订阅”，立即重新下载、校验并应用Xboard配置；单独显示配置成功时间，不再把流量同步时间当作节点更新时间。帮助设置可选30分钟或1/3/6/12/24小时，默认1小时，原生持久化并在后台检查到期；普通网络失败保留有效旧配置，认证或套餐失效继续停止连接。该功能同步服务器当前下发内容，不能自行修复外接节点旧公钥/地址。[0.1.6正式版](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.6)四目标构建及18附件核验完成，官网应用更新源已同步并通过公开下载校验；另一台电脑可在帮助与设置检查应用更新后使用。实现、验证与发布状态见[进展](./progress-log.md#2026-10-27卡皮巴拉订阅手动更新与自动周期)和[节点决定](./.agents/notes/implemented/feature/2026-10-26-capybara-ready-nodes.md)。

### Windows 0.1.5 美国01连接差异（2026-10-26）

用户确认 v2rayN 已退出，同一美国01家宽在 v2rayN 可用、卡皮巴拉失败；Windows 根因尚待现场证据。本机同版本可用，并复现五秒测速超时、十二秒成功，不能据此把 Windows 代理失败归结为测速期限。新增[只读诊断工具](./scripts/capybara/README.md)，直接用于已安装 0.1.5，分阶段检查回环内核、入口、检测站点和当前代理请求，输出不含凭据的报告；不修改客户端配置或生产。工具已通过本机 PowerShell 7 与 Windows PowerShell 5.1 各28项检查。验证及待办见[进展](./progress-log.md#2026-10-26windows-015-美国01连接差异诊断)。

### 运行时 AnyTLS 公钥身份检测（2026-10-26）

外接[保护器](./.docker/upstream/guard.py)补上已批准固定端点的 SPKI 握手检测，独立于订阅抓取宽限；公钥不符及无法验证均失败关闭，只撤下、不接纳新公钥、不自动恢复。新增只读 `--check-identity`，新加坡 U04/U05 可按 key 单独检查。本机用当天配置快照的旧 pin 实测两个端点，均准确返回 `runtime_public_key_mismatch`；该次检测当时未改生产脚本、信任映射和服务配置；后续授权恢复以本页最新记录为准。本地25项回归、专项CI、笔记校验与双架构镜像构建通过；代码 `de4ec6e` 已推送 master，交付状态见[进展](./progress-log.md#2026-10-26运行时-anytls-公钥身份检测)，输入格式和使用方法见[运维](./docs/zh-CN/installation/upstream-extension.md#运行时-anytls-公钥检查)。

### 外接原始订阅全量复测（2026-10-27）

原始订阅46个条目包含41条真实线路和5条提示，已逐条检查：入口服务器39/41条HTTPS成功，本机首轮27/41、复核后28/41。该次复测中，两条韩国未成功：移动优化为入口上游TCP超时；CDN先系统DNS失败，采用公共DNS候选地址复测两目标仍超时。8条名称标注IPv6线路入口通过、本机未成功，不据此推定地址族故障。原订阅可用性随接入网络和时间变化；该次复测当时未改生产旧pin/固定IP，不能据此宣称公开路径恢复；后续授权恢复见本页最新记录，不自动信任新公钥。完整41条逐项结果及边界见[全量复测](./progress-log.md#2026-10-27供应商原始订阅41条全量复测)，原8条生产公钥/地址差异见[单变量对照](./progress-log.md#2026-10-27供应商原始订阅与生产固定出站对照)。

### 卡皮巴拉 0.1.5 官网更新分发（2026-10-26）

用户反馈另一台电脑 0.1.2 手动检查仍显示无新版本；现场读取官网索引确认为 0.1.2，原因是 GitHub Release 已完成但官网静态分发尚未同步。沿用已发布的 0.1.5，先校验并镜像全部版本化安装/更新附件，再原子替换索引，同时同步官网下载页和教程。官网更新源、下载页与教程现已同步 0.1.5，主备域索引、12 文件完整下载和四平台旧公钥验签通过。手动检查立即请求，六小时仅约束后台检查；服务端同步与验证边界见[进展](./progress-log.md#2026-10-26卡皮巴拉015官网更新分发)。

### 卡皮巴拉统一页面框架（2026-10-26）

首页、套餐、邀请、账户和帮助页共用蓝色外框、侧栏与响应式尺寸，切换页面时 Logo、通知铃铛和导航不再跳动。首页保持固定视口及节点内部滚动，其他页面仅内容区滚动，切页回到内容顶部。前端 57 项、脚本 16 项及构建通过，五种窗口尺寸与明暗/未登录/长页预览已验；0.1.5 已正式发布并安装，本机五页切换与长页滚动通过，四目标构建和 18 附件已核验；官网更新源后续已同步到 0.1.5，完整终态见[进展](./progress-log.md#2026-10-26卡皮巴拉统一页面框架)，边界见[首页决定](./.agents/notes/implemented/feature/2026-10-26-capybara-scenic-home.md)。

### 卡皮巴拉连接按钮恢复左侧（2026-10-26）

根据用户反馈，将首页一键连接按钮恢复到插画左侧，避免遮挡卡皮巴拉。保持首页固定、节点内部滚动；按插画实际高度紧凑排列，小窗口出现错误提示时优先保证连接、登录和注册入口完整可见。前端 57 项、脚本 16 项及类型/构建检查通过；四种窗口和明暗、未登录、同步异常预览已验。0.1.4 已正式发布并安装，四目标与 18 附件已核验；本机未登录和已登录首页均确认按钮在左、卡皮巴拉无遮挡。官网更新源后续已同步为 0.1.5，完整终态见[进展](./progress-log.md#2026-10-26卡皮巴拉连接按钮恢复左侧)。

### 卡皮巴拉分流模式与自定义规则（2026-10-26）

客户端首页补上规则、全局、直连三种模式，以及自定义分流规则管理。全局模式提供独立的出口选择；规则支持域名、域名后缀和 IPv4/IPv6 网段，可走订阅节点/代理组、直连或拦截，并可编辑、删除、调整优先顺序。设置由原生层校验和保存，重新启动与刷新订阅继续使用。应用结果、本地检查、安装包发布和官网分发分别记录在[进展](./progress-log.md#2026-10-26卡皮巴拉分流模式与自定义规则)，取舍见[分流决定](./.agents/notes/implemented/feature/2026-10-26-capybara-routing.md)。分流本地合并检查已通过（前端 57、脚本 16、Rust 34，另 1 项既有手工钥匙串测试跳过），最小窗口与三模式内核流量验证通过。0.1.4 已正式发布并安装，四平台和 18 附件、签名及源码均已核验。本机三模式、全局节点、规则增改保存与重启恢复通过；测试规则已清除，恢复规则模式，现有系统代理未改变。官网更新源后续已同步为 0.1.5，详见进展。

### 卡皮巴拉邀请好友与首页适配（2026-10-26）

客户端新增邀请好友：查看本人邀请码、复制邀请链接、展示二维码、主动生成新码，以及注册人数、佣金统计和分页明细。规则与官网共用，无套餐也可使用；提现与余额划转仍在官网办理。首页按窗口高度适配，整页保持固定，仅节点列表内部滚动。明暗主题、760×620 最小窗口及异常状态已验；0.1.2 已安装，真实账号邀请读取、二维码和复制通过，官网配套接口已上线；结果见[进展](./progress-log.md#2026-10-26卡皮巴拉邀请好友与首页适配)，取舍见[邀请决定](./.agents/notes/implemented/feature/2026-10-26-capybara-invitations.md)与[首页决定](./.agents/notes/implemented/feature/2026-10-26-capybara-scenic-home.md)。

### 卡皮巴拉 0.1.2：通知、邀请与首页适配（2026-10-26）

0.1.2 汇总通知铃铛、邀请好友和首页固定窗口布局。已从提交快照排除后续分流功能，合并前端 50 项、脚本 16 项、Rust 23 项（另 1 项人工测试忽略）及类型/构建通过；完整 Desktop API 68 项 / 617 断言通过。[0.1.2 正式 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.2) 四目标及 18 附件、签名索引和源码已核验。官网邀请接口、12 个分发文件、下载页及文章 5 已上线，生产 a0915f8 Healthy；主备域签名索引和五种包下载通过。本机真实通知、授权页自动关闭、17 节点、既有邀请码/二维码/复制和重开恢复已验，手动更新检查为最新版本。验收边界见[发布进展](./progress-log.md#2026-10-26卡皮巴拉012发布与上线)。

### 卡皮巴拉系统通知（2026-10-26）

客户端侧栏增加通知铃铛，与官网读取同一公开公告源；支持未读红点、详情、分页、刷新和本页已读。启动、打开、回到窗口和每五分钟刷新，内容更新后重新提示；已读只保存在本机，不宣称与网页版已读互通。明暗主题、760×620、空态和失败提示已验；0.1.2 原生铃铛读取/刷新官网公告通过，正式公告源当前为空。已发布并同步官网，结果见[进展](./progress-log.md#2026-10-26卡皮巴拉系统通知)，取舍见[通知决定](./.agents/notes/implemented/feature/2026-10-26-capybara-notifications.md)。

### 卡皮巴拉授权页自动关闭（2026-10-26）

官网授权接口确认成功后，授权页自动尝试关闭，客户端继续独立兑换登录结果，无需升级现有 0.1.1 客户端。失败、过期和取消不自动关闭；浏览器限制关闭时保留明确的成功提示，避免重复授权。登录/注册跳转使用 replace 减少临时历史，网页不接触客户端令牌。本地网页 14 项、后端授权及并发 9 项 / 110 断言通过；Chrome 隔离页面确认新标签授权后消失，受限页面保留成功提示。官网双架构镜像与专项 CI 已通过，生产运行 d01331a 并 Healthy；主备域 v3 脚本逐字节匹配。正式 Chrome 临时请求批准后标签页自动关闭，随后取消该请求且未兑换设备令牌；现有客户端登录不受影响。详见[进展](./progress-log.md#2026-10-26卡皮巴拉授权页自动关闭)与[授权决定](./.agents/notes/implemented/feature/2026-10-25-capybara-browser-login.md)。

### 卡皮巴拉开机自启与后台运行（2026-10-26）

客户端新增“帮助与设置 → 启动与后台 → 开机自启”，默认关闭；开启后在登录电脑时后台启动，不自动开启系统代理。关闭窗口隐藏到后台，托盘提供打开和退出；明确退出仍恢复代理并停止内核。本地隔离检查为前端 35、网页/发布脚本 12、Rust 17 项通过；macOS 自启启停、注册项实际启动、单实例重开、关闭保留进程和 Cmd+Q 退出已验。按用户授权与节点优化合并为 0.1.1，合并版已验证节点加载/测速、关闭保留三进程、Cmd+Q 清理和重开恢复登录；现有系统代理未改变，托盘点击和开启系统代理后的关闭尚未实测。四目标正式 Release 已通过，官网分发状态见[进展](./progress-log.md#2026-10-26卡皮巴拉开机自启与后台运行)及[决定](./.agents/notes/implemented/feature/2026-10-26-capybara-background-startup.md)。

### 卡皮巴拉节点自动加载与一键测速（2026-10-26）

有效账号登录后自动下载并校验本人套餐配置，首页无需先连接即可显示、预选节点和一键测速；登录准备不自动开启系统代理；0.1.7起主动点击节点也可连接，见上方最新交互。切换只等待回环内核确认，界面立即反馈处理中，失败不误报成功；断开保留列表与选择。测速最多四路并发、每项五秒，逐个显示真实毫秒或超时/不可达，注销及配置变化丢弃旧结果。与用户授权的自启/后台功能合并为 0.1.1 正式版。

本地合并检查前端 38、脚本 12、Rust 19 项与 Mac 构建/签名通过，明暗及 760px 预览通过。真实账号未连接即加载 17 个节点与分流选项，延迟和超时逐项显示，点击日本节点约 446ms 观察到选中，实际经该节点 HTTPS 204 成功；关闭保留 App/看护/Mihomo，明确退出清理，重开恢复登录及节点。现有系统代理始终未变；托盘菜单点击、接管系统代理后关闭及 Windows/Linux 原生桌面尚未实测。[0.1.1 正式 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.1) 四目标与 18 附件、签名和源码已核验；官网安装包、下载页、更新源与文章 5 已同步到 0.1.1，生产 8d39e2c 健康检查通过，进展见[记录](./progress-log.md#2026-10-26卡皮巴拉节点自动加载与一键测速)，取舍见[节点决定](./.agents/notes/implemented/feature/2026-10-26-capybara-ready-nodes.md)。

### 卡皮巴拉 0.1.0 正式版（2026-10-26）

生产诊断确认浏览器批准后的令牌兑换遭遇 SQLite WAL 写竞争。修复在完整回滚后有限重试，耗尽时保留批准等待；真实双连接回归覆盖一次兑换、持续竞争和非并发错误。客户端及首屏默认版本统一读取构建版本 **0.1.0 正式版**，每六小时检查更新，发现新版弹出确认，帮助页保留“查看更新”。本地 60 项 Desktop API、30 项前端、12 项脚本和 16 项 Rust 检查通过；[0.1.0 正式 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0) 四目标和 18 附件已完成，生产已升级至 2ebf328 并 Healthy，官网正式下载页、12 个分发文件和签名更新索引已同步；本机已实测 alpha.11 应用内升级到 0.1.0、正式版网页授权登录、退出重开自动恢复和五个套餐加载，见 [进展记录](progress-log.md#2026-10-26卡皮巴拉授权修复与正式版) 和 [修复决定](.agents/notes/implemented/bug-fix/2026-10-26-capybara-browser-sqlite-contention.md)。

### 卡皮巴拉山水首页（2026-10-26）

`0.1.0-alpha.11` 按用户参考图更新蓝色山水、旅行水豚和大连接按钮。用户确认保留首页节点列表：移除侧栏独立“线路”页面，节点搜索、地区筛选、多分流组切换放在首页右侧，流量、规则分流说明和连接检测集中展示。未连接时不展示假节点，不填入未测的延迟/速率或无效模式开关。

前端 29 项、网页/发布脚本 12 项、Rust 15 项与生产构建通过；明暗、760px 窄窗口、模拟切换和耗尽状态验收通过。[alpha.11 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.11) 四目标及 18 附件验证通过，本机当时由 alpha.10 升级至 alpha.11，签名与原生首页验收通过；后续授权故障修复与升级 0.1.0 的当前结论见[正式版](#卡皮巴拉-010-正式版2026-10-26)，详见[进展](./progress-log.md#2026-10-26卡皮巴拉山水首页与节点入口合并)。此次无需服务端部署，官网分发源仍独立维护。取舍见[首页决定](./.agents/notes/implemented/feature/2026-10-26-capybara-scenic-home.md)。

### 卡皮巴拉登录弹窗简化（2026-10-26）

`0.1.0-alpha.10` 按用户反馈移除登录及注册弹窗底部重复的“取消”按钮，保留右上角关闭和 Esc 取消。账号登录、注册及授权返回功能不变。本地前端 25 项、网页授权 10 项、发布校验 2 项和生产前端构建通过；真实浏览器预览确认两个弹窗布局、关闭与 Esc，macOS App 已构建且签名检查通过。[alpha.10 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.10) 四目标构建与发布完成，18 附件及源码版本核验通过；本机已更新、授权登录成功，并恢复“美国01”连接。证据见[进展](./progress-log.md#2026-10-26卡皮巴拉登录弹窗简化)。

### 卡皮巴拉客户端注册账号（2026-10-25）

`0.1.0-alpha.9` 在未登录首页和登录弹窗提供“注册账号”。点击后进入官网注册，沿用邮箱验证码、邀请码、注册限制与密码规则；注册成功自动返回授权页，确认账号后登录客户端。官网已登录其他账号时先展示该账号，不自动退出或静默切换；超过五分钟可用已注册账号重新发起登录。

本地前端 25 项、网页授权 10 项、发布校验 2 项、Rust 15 项及 Desktop API 57 项 / 524 断言通过。真实浏览器完成入口、取消、明暗/760px 窄窗口及隔离官网注册表单自动跳转；隔离数据库验证新注册无套餐账号授权和一次性兑换。[alpha.9 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.9) 四目标构建及 18 附件核验完成；生产已部署 `1c60394`，本机已安装并从真实注册入口打开官网。未登录浏览器自动进入正式注册表单，已有会话显示账号确认；未新建真实生产账号或发送验证码。证据见[进展](./progress-log.md#2026-10-25卡皮巴拉客户端注册账号)。沿用[浏览器授权决定](./.agents/notes/implemented/feature/2026-10-25-capybara-browser-login.md)。

### 卡皮巴拉客户端套餐购买（2026-10-25）

`0.1.0-alpha.8` 将侧栏“我的账户”改为“套餐”。用户可在客户端浏览套餐、选择周期与优惠码、创建订单并确认金额，支持浏览器支付、二维码、零元开通、待支付订单恢复/取消和开通后同步。账户资料保留在左下角；价格、余额、折扣和续费资格均沿用网站服务。

本地检查与四平台发布已通过，购买功能及最终文案修正包含于 [alpha.9 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.9)。配套接口经用户授权上线，后续注册更新后运行 `1c60394`、容器 Healthy。本机 alpha.9 已读取正式 5 个套餐、展示真实周期/价格和同时在线 IP 数；实际扣款未执行，官网静态分发与更新源尚未同步本版。见[购买决定](./.agents/notes/implemented/feature/2026-10-25-capybara-store.md)、[API 说明](./docs/zh-CN/development/client-api-integration.md#客户端套餐与订单)及[进展](./progress-log.md#2026-10-25卡皮巴拉客户端套餐购买)。

### 卡皮巴拉蓝绿色桌面图标（2026-10-25）

`0.1.0-alpha.5` 将应用图标改为蓝绿色地球背景，保留金色水豚、蓝围巾与锁扣。原图的透明边距和预切圆角在 macOS 26.5 Finder 中触发灰色底板；改用满幅不透明正方形后，系统预览已确认灰框消失。三平台图标与应用内头像同步，官网图片副本保持独立。

素材与完整提示词见 [BRAND](./desktop/capybara/BRAND.md)，检查、安装和发布状态见[本次记录](./progress-log.md#2026-10-25卡皮巴拉蓝绿色桌面图标)。本地前端 14 项、发布校验 2 项与生产前端构建通过；macOS App/DMG 已构建并安装 alpha.5，Finder 实际图标无灰框，深浅主题头像通过。[四目标构建与发布](https://github.com/nanashiwang/Xboard/actions/runs/40181599657)全部通过，[alpha.5 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.5) 的 18 个附件已完整下载核对 SHA-256，四目标更新签名和两架构 Mac 包内图标通过；官网分发本轮未更新。

### 官网下载卡皮巴拉（2026-10-24）

官网首页继续使用 `/clients`，电脑端现默认提供自有卡皮巴拉 **0.1.0-alpha.3**，覆盖 Windows x64、macOS Apple Silicon/Intel、Linux x64 DEB/AppImage。安装后直接登录本站账号；自动同步流量与到期状态，无需复制订阅。手机明确标为第三方方案，Clash Verge 保留独立兼容入口。页面提供测试版、系统要求、签名限制、校验值及官方备用下载。

[官网下载页面](https://taige.us/clients)已部署 `8ecbd73`，生产容器 Healthy，两域名回读版本与新版五包链接一致。网站 17 项 PHP / 153 断言、5 项 Node、8 项同步回归通过；全部新版安装包、更新归档、签名及索引已从主站完整下载验 SHA，四目标更新签名通过，两域名五包 Range 共 10 项通过。文章 5 的更新说明已带备份同步。桌面 [alpha.3 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.3) 与网站分发均已验收；旧 alpha.1/alpha.2 需先手动安装一次。证据见[本次记录](./progress-log.md#2026-10-24卡皮巴拉六小时检查更新)。

### 卡皮巴拉官网首页（2026-10-23）

内置 Xboard 主题的公开首页采用用户参考的蓝天海岸、蓝围巾旅行水豚与木质路牌，配套服务概览、使用步骤、FAQ 和移动端菜单。按用户反馈移除右上角“简体中文”及地球语言标识，保留登录/注册入口；该调整已随 `20261023-6eb3c2f` [部署上线](https://github.com/nanashiwang/Xboard/actions/runs/39943939718)，桌面与手机复验通过。标题、按钮及说明均为可操作 HTML；不沿用未经当期核实的节点数量、带宽或稳定性承诺。横幅使用内置 ImageGen 衍生素材并压缩为 WebP，桌面约 197 KiB、手机约 63 KiB；[素材与提示词](./public/assets/capybara-home/README.md)随源码保存。

原 `/#/login`、`/#/register`、套餐/用户中心路由与 `/clients` 继续使用；公开首页不加载完整 Vue 面板，跨首页/面板的前进后退保持兼容。PHP 8.2 的首页与下载回归 15 项 / 91 断言、Blade 编译、JS/actionlint 和笔记检查通过；真实项目壳完成 320–1536px、菜单、FAQ、邀请码、登录保护、加载失败与无 JS 验收。首页保持浅色风景设计，不改变用户面板主题。方案见[首页决定](./.agents/notes/implemented/feature/2026-10-23-capybara-website-home.md)，发布与生产状态见[本次记录](./progress-log.md#2026-10-23卡皮巴拉官网首页设计)。慢加载导航竞态已修复，新增 5 项 Node 回归；最终 `16272a2` 的[首页 CI](https://github.com/nanashiwang/Xboard/actions/runs/39928577358)与 [GHCR 双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39928577323)成功。用户授权后已[部署生产](https://github.com/nanashiwang/Xboard/actions/runs/39929108999)，容器 Healthy；两个域名回读版本 `20261023-16272a2`，正式站登录/注册往返、手机布局与延迟加载回归通过。复验期间有连接超时，完整重测通过，网络采样边界见进展记录。网站沿用 GHCR 镜像发布，没有独立的网站 GitHub Release/安装包流程。

### 卡皮巴拉浏览器登录（2026-10-25）

`0.1.0-alpha.7` 将入口名称由“浏览器登录”调整为“账号登录”，功能沿用 alpha.6 的浏览器授权：复用 `taige.us` 当前网页登录状态，确认账号后客户端领取一次性登录结果；未登录时沿用官网表单，完成后自动返回授权页。客户端不再要求输入网站密码，原钥匙串静默恢复与按构建隔离继续保留。授权可取消、五分钟过期，仍受设备数量和封禁限制。

本地后端 Desktop 48 项 / 443 断言、前端 15 项、网页授权 7 项、发布校验 2 项、Rust 13 项通过；隔离浏览器完成官网登录返回、授权、一次性兑换与撤销。本版补充超时/连接/权限分类提示；服务端上线后的真实浏览器授权与原生重启恢复已通过，证据见下文。[alpha.7 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.7) 已完成四目标构建，18 附件摘要、四目标签名与源码均核实；本机 alpha.7 首页两处“账号登录”名称已验证，名称调整未改变授权功能。生产已从缺失接口的 `8ecbd73` 更新到 `e278451`，授权表迁移完成、容器 Healthy；主备域授权接口和网页返回脚本均通过验收，本机 alpha.7 已实际打开 Chrome 官网授权页。用户已在官网确认授权；本机 alpha.7 实际进入已登录首页。正常退出并重新启动后自动恢复账号与流量，没有再次要求网页登录或弹出钥匙串密码框。数据库一致性备份、部署与验收见[修复进展](./progress-log.md#2026-10-25修复账号登录提示服务端不支持)。见[授权决定](./.agents/notes/implemented/feature/2026-10-25-capybara-browser-login.md)与[进展](./progress-log.md#2026-10-25卡皮巴拉浏览器登录)。

### 卡皮巴拉钥匙串重复授权修复（2026-10-25）

`0.1.0-alpha.4` 修复 macOS 启动及重新登录反复读取旧钥匙串项的问题：启动/后台操作静默执行，授权受阻只提示；登录记录按当前二进制构建隔离，重新登录不覆盖旧版受限记录。升级后需重新登录一次卡皮巴拉账号，同一构建后续启动自动恢复；钥匙串锁定仍受系统解锁要求约束，未降低存储保护。

前端 14、Rust 11、发布校验 2 项与额外 1 项真实钥匙串跨进程读写测试通过。本机 App/DMG 已构建，/Applications 已更新并验证启动无钥匙串错误或授权弹窗；[alpha.4 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.4) 四目标构建成功，18 附件摘要、四目标签名和源码提交已核实；真实账号试用遇到网络失败，复启恢复仍待验收。GitHub Release 与官网生产更新索引分开处理，详情见[修复决定](./.agents/notes/implemented/bug-fix/2026-10-25-capybara-keychain-prompts.md)及[进展](./progress-log.md#2026-10-25卡皮巴拉钥匙串重复授权修复)。

### 卡皮巴拉应用更新（2026-10-24）

`0.1.0-alpha.3` 新增每 6 小时检查应用更新，重启保留周期，休眠恢复补查；帮助页可立即检查。发现新版后用户选择稍后或更新，确认后才下载；Windows/macOS/AppImage 验签并恢复系统代理后安装重启，DEB 打开官网下载页交由系统安装器。旧 alpha.1/alpha.2 需要先手动升级一次。更新签名不代表系统发行者签名或公证。

本地前端 11、Rust 8、发布校验 2 项测试、生产前端构建、macOS 签名更新包、深浅与小窗口交互通过。[四目标 CI 与发布](https://github.com/nanashiwang/Xboard/actions/runs/39988361814)已成功，[alpha.3 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.3) 的 18 个附件全量下载且 SHA-256 一致，四目标更新签名与源码提交已校验；官网索引、安装包、下载页面与教程均已上线核对；见[更新决定](./.agents/notes/implemented/feature/2026-10-24-capybara-updates.md)与[进展](./progress-log.md#2026-10-24卡皮巴拉六小时检查更新)。

### 卡皮巴拉桌面客户端（2026-10-23）

已新增 [卡皮巴拉桌面工程](./desktop/capybara/README.md)：首页采用用户指定的蓝围巾旅行水豚，桌面 Logo 采用蓝色地球头像，统一浅蓝/暖白与深蓝主题；复用 Mihomo 与本站桌面 API。登录后每 30 秒同步流量/到期状态，额度耗尽或到期会暂停连接并显示原因；支持系统代理、线路选择、每小时配置更新和系统凭据库。首页将账号异常置顶，不依赖手动刷新订阅才出现提示。根据本地试用反馈，`0.1.0-alpha.2` 已移除四个页面的公共顶部标语、标题和连接状态栏，主题切换移至侧栏底部；本机已由用户确认顶部栏移除，发布证据见[界面优化记录](./progress-log.md#2026-10-23卡皮巴拉移除重复顶部栏)。

上一版 `0.1.0-alpha.2` 为测试版本，构建目标是 Windows x64、macOS Apple Silicon/Intel 和 Linux GNOME x64；暂不含 TUN、签名自动更新、Windows 发行者签名或 macOS Developer ID 公证。前端 6 项、Rust 5 项、后端 Desktop 37 项测试通过，本地 macOS 应用和 DMG 已生成并启动验收；[测试版 Release](https://github.com/nanashiwang/Xboard/releases/tag/capybara-v0.1.0-alpha.2) 已发布，四个构建目标通过，5 个安装包及源码包均已下载并校验 SHA-256；证据见[本次发布](./progress-log.md#2026-10-23卡皮巴拉移除重复顶部栏)。真实账号、三系统代理权限与长期网络体验仍需验证；官网下载入口的生产状态以上方记录为准。方案见[决策笔记](./.agents/notes/implemented/architecture/2026-10-23-capybara-desktop.md)。

### 网站 Flawless 灰云入口已切换（2026-10-22）

`taige.us` 已改为 DNS-only A 指向 `155.103.118.155`，再严格 HTTPS 转发至原源站；两台权威 DNS、1.1.1.1 与 8.8.8.8 已返回新地址且无旧 AAAA，实际请求目的 IP 与响应头验证一致。独立证书、webroot 自动续期模拟、源站真实 IP/伪造头防护、压缩、下载 Range 和登录页通过；`board.taige.us` 保留 CF，节点与订阅域名保持。

同网预检新入口 9/9 完成，CF 对照 8/9；新入口首页/公开接口约 0.66–0.85 秒，但 CF 缓存 JS 略快。切换后 HTTP/1.1、HTTP/2 对照 12/12 完成，约 0.65–0.77 秒；含公网 DoH 解析的追加测试仍有一次 15 秒超时，不能宣称卡顿已彻底消失或全运营商更快。灰云主站不再享有 CF 边缘防护；源站原有 `/ws` 两路均返回 502，未标为成功。见[实施决定](./.agents/notes/implemented/architecture/2026-10-22-website-flawless-relay.md)、[运维与回退](./docs/zh-CN/installation/website-relay.md)和[完整记录](./progress-log.md#2026-10-22网站-flawless-灰云入口准备)。

### 网站切换前 Cloudflare 路径与速度核对（2026-10-22）

切换前 `taige.us` 与 `board.taige.us` 都经过 Cloudflare，公开 DNS 与 HTTP 响应头已实测确认；主域当前灰云状态以上方最新记录为准。当次本机代理路径命中洛杉矶 LAX，三次独立连接的首页约 2.05–2.14 秒、公开配置约 2.07–2.15 秒，其中 TLS 建连约 1.44–1.53 秒；主 JS 已 gzip 并可命中 CF 缓存，一次新连接在 25 秒超时。复用连接后配置接口约 0.52 秒、JS 约 0.91 秒，说明当次样本中建连开销明显。

用户随后确认慢发生在大陆无代理。绑定物理网卡、禁用本次请求代理并固定公开 CF 地址后，trace 确认 loc=CN / warp=off；12 次 IPv4 请求中，配置接口和主 JS 各一次 20 秒超时，其余完成。成功 JS 为 1.34–1.67 秒；严格 TLS 直接源站对照约 2.57 秒，源站未压缩主 JS 为 1.42 MB，CF 压缩后约 420 KB。因此大陆路径确有间歇卡顿，但不能断言关闭 CF 更快。IPv6 小样本全部成功，仍落在境外节点，不代表稳定性保证。浏览器登录页与站内验证码关闭已核验；没有修改 DNS、代理、防护或生产配置，详情见[测速记录](./progress-log.md#2026-10-22网站-cloudflare-路径与访问耗时核对)。

### 节点入口独立域名（2026-10-22）

节点入口已迁到 `lumavia.fyi`：主入口 `node.lumavia.fyi` 直连现有第一阶段，CF 备用 `edge.lumavia.fyi` 继续使用七云。面板与原订阅地址保持 `taige.us`，客户端更新原订阅即可。旧节点域名继续兼容；本次隔开注册域名故障范围，不代表服务器双活或面板停机后节点仍可冷启动。

新域名切换前后各 58 条监控线路真实 HTTPS 全部通过，四档两格式订阅 8/8 通过，数量仍为 **14 / 22 / 34 / 47**；普通美国保留两个 2× 家宽节点，独享池仍为 11 个出口。证书已签发，CF 使用完全（严格）模式。见[域名决定](./.agents/notes/implemented/architecture/2026-10-22-independent-node-domain.md)、[第一阶段运维](./docs/zh-CN/installation/vpn-stage1.md)与[执行记录](./progress-log.md#2026-10-22节点入口迁移至-lumaviafyi)。

### 节点名称统一与美国家宽倍率（2026-10-22）

客户端使用 `国家两位编号｜倍率×｜可选家宽/原生IP`，例如 `美国01｜2×｜家宽`、`日本01｜1×`。全部 13 个自建美国出口按用户定义标家宽，公开、固定别名与后端实际计费同步为 2×；香港两条原生 IP 标记沿用上游声明。其他倍率、四档数量 14/22/34/47 和权限保持，UDP 与共享限速仍有效。更新原订阅后可能需要重新选择当前节点。

四档两格式真实订阅无重名，13 条美国及 1×/第三方 2× 对照实际流量与扣量逐字节相符；测试账号已撤销。IP 属性标记不代表独立认证或物理独占，固定出口仍按原健康规则自动迁移。见[命名决定](./.agents/notes/implemented/simplification/2026-10-22-node-names-and-residential-rate.md)、[节点映射](./.docker/node-presentation.json)和[验证记录](./progress-log.md#2026-10-22节点短名称与美国家宽-2-倍率)。

### 自建美国出口已按套餐拆分（2026-10-21）

四档普通套餐仅保留原「美国自建｜06｜第一阶段入口」与「美国自建｜基础｜CF备用」两个美国出口（现名「美国01｜2×｜家宽」与「美国02｜2×｜家宽」）；加上香港、日本、荷兰、罗马尼亚，当前每档共 **6 条自建线路**。其余 **11 个去重美国出口**只供独享固定池使用，仍按每账号固定一个出口、每出口最多五名额和原健康迁移规则分配。三个同 IP 的重复 CF 入口/后端已停用，未删除数据。

48 项真实代理与拒绝检查、四档两种订阅格式共 8 项检查通过；17 条探针改用内部监控组后持续收到真实回报。25 个既有账号的身份、余额及权益对比备份保持（仅专用监控账号换组），客户价格、额度与固定订单不变。客户端需刷新订阅并切换保留线路，旧普通链接不能继续访问独享池。NAS 探测仍有波动，已配置 11 个出口不代表同时健康；见[拆分决定](./.agents/notes/implemented/architecture/2026-10-21-owned-us-package-split.md)和[执行记录](./progress-log.md#2026-10-21自建美国出口按套餐拆分)。

### 四档套餐拓展线路已接入（2026-10-22）

四档保留原 6 条自建，并累计加入 **8 / 16 / 28 / 41** 条第三方拓展，实际订阅为 **14 / 22 / 34 / 47** 条（不含流量提示）。刷新原订阅即可使用，独享套餐未增加第三方；原价格、额度、用户身份和固定池保持。

41 条完整 HTTPS 路径通过，四档 Clash Meta/Shadowrocket 实际订阅 8/8 通过且不含上游凭据；两用户的 1x/2x/5x 实际扣量与后端统计一致。33 条 UDP 通过，8 条美国 UDP 受限；4 条香港/台湾轻量线路每条共享限速 2 Mbps，限制明细见运维映射。上游额度/到期或批准配置变化会自动撤下相关拓展，恢复需复验；新增独立质量探针，原自建监控不变。节点数不代表独立 IP、共享额度增长或长期速度保证。见[接入决定](./.agents/notes/implemented/architecture/2026-10-21-tiered-upstream-route-family.md)、[运维与回退](./docs/zh-CN/installation/upstream-extension.md)和[验证记录](./progress-log.md#2026-10-22第三方拓展线路实际接入)。

### 第三方订阅转发评估（2026-10-21）

10 月 21 日该轮只评估转发可行性，后续实际接入见上方 10 月 22 日记录。配置解析和少量 HTTPS 成功不能代表服务器中转性能或多用户承载能力；实际接入需保留 Xboard 用户鉴权与计量，并核对共享额度、倍率、到期、证书校验及上游共享限制。订阅地址、令牌、节点凭据和账户额度不写入仓库；[评估边界与验证记录](./progress-log.md#2026-10-21第三方订阅转发可行性评估)。

### 节点管理显隐与清理核对（2026-10-21）

拆分前核对时，生产 53 条节点记录由 20 条普通订阅入口、13 条固定出口订阅别名、20 条隐藏后端组成；后续美国权限与重复项状态以本页最新拆分记录为准。本次逐条核对未发现无引用闲置节点，因此未删除。列表「显隐」开关控制是否进入订阅；「服务器在线」是服务器心跳状态，两者独立。隐藏后端仍须启用，供公开入口转发。用户指出的 `10.77.0.2:31006` 是「美国自建｜旗舰｜CF备用」依赖的后端，不能按显隐关闭误删；证据见[进展记录](./progress-log.md#2026-10-21节点显隐与闲置记录核对)。

### 荷兰与罗马尼亚节点已接入（2026-10-21）

`friendhosting-荷兰` 和 `friendhosting-罗马` 已加入轻量、标准、进阶、旗舰四个套餐，刷新订阅可见「荷兰｜friendhosting｜第一阶段入口」与「罗马尼亚｜friendhosting｜第一阶段入口」。第二台实际出口识别为罗马尼亚（RO），机器名保留用户原命名；接入当时四档节点数为 **17 / 18 / 19 / 20**（后续美国出口拆分后每档为 6），独享仍仅原固定出口及香港备用。

两台均完成三名普通账号的 HTTPS 出口与 UDP DNS、独享/无效身份拒绝和旧线路抽查；两种客户端订阅共 20 项权限检查通过。本机补充检查：荷兰 4/6 次 HTTPS 成功；罗马尼亚 5/6 次 HTTPS 成功。接入时扩展至 20 条质量探针和 16 条入口隧道；持续采样的成功、超时与速度不等同于长期性能保证。配置和回退见[欧洲节点运维](./docs/zh-CN/installation/europe-nodes.md)，本轮证据见[进展记录](./progress-log.md#2026-10-21荷兰与罗马尼亚节点接入)。

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
