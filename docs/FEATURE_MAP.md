# Xboard 能力地图

核对日期：2026-10-17；业务代码基线：`61919aa`。此表是检索入口，变更前仍需读当前实现；代码存在、测试存在与生产可用是不同结论。本次核对不包含线上账号、支付、节点或管理后台浏览器验收。

路由总入口为 [RouteServiceProvider](../app/Providers/RouteServiceProvider.php)，分别加载 `/api/v1` 和 `/api/v2`；后台使用动态安全路径及 `admin`、`log` 中间件，用户接口使用 `user` 中间件，实际权限须沿路由逐层检查。

| 能力 | 页面或入口 | 权限、实现与数据来源 | 边界与相关验证 |
| --- | --- | --- | --- |
| 用户首页与管理后台 | [Web 路由](../routes/web.php)、[后台视图](../resources/views/admin.blade.php) | 首页由 [ThemeService](../app/Services/ThemeService.php) 加载；[管理路由](../app/Http/Routes/V2/AdminRoute.php)由 [Admin](../app/Http/Middleware/Admin.php)校验管理员身份 | 管理前端为 `public/assets/admin` 子模块，本地未展开；不能据后端代码声称页面已验收。涉及 UI 时须在真实项目壳中检查 |
| 套餐、订单、折抵与余额 | [用户路由](../app/Http/Routes/V1/UserRoute.php)的 `plan/fetch`、`order/*`；管理路由的 `plan/*`、`order/*` | `user` / `admin`；[OrderService](../app/Services/OrderService.php)、[PlanService](../app/Services/PlanService.php)，[Order](../app/Models/Order.php)、[Plan](../app/Models/Plan.php)、[User](../app/Models/User.php) | 复用现有价格、折抵与开通流程；回归入口：[OrderCreditMigrationTest](../tests/Feature/Payments/OrderCreditMigrationTest.php)、[DedicatedExitTest](../tests/Feature/Dedicated/DedicatedExitTest.php) |
| Stripe Checkout 与回调 | 用户 `order/checkout`、[访客支付回调路由](../app/Http/Routes/V1/GuestRoute.php)、后台 `payment/*` | [PaymentService](../app/Services/PaymentService.php)、[Stripe 插件](../plugins/Stripe/Plugin.php)、[UsdPricing](../plugins/Stripe/UsdPricing.php)；`v2_order`、`v2_stripe_quotes` | 内部按人民币最小单位记账，美元报价持久化；回调校验签名、金额、币种、订单和项目归属；[StripeCheckoutTest](../tests/Feature/Payments/StripeCheckoutTest.php)。测试通过不等于真实结算 |
| 订阅与多客户端协议 | Web `/{subscribe_path}/{token}`、[ClientRoute](../app/Http/Routes/V1/ClientRoute.php)的 `client/subscribe` | `client` 中间件；[ClientController](../app/Http/Controllers/V1/Client/ClientController.php)、[ServerService](../app/Services/ServerService.php)、[协议输出目录](../app/Protocols)；用户、节点与分组数据 | 保留节点过滤、专属出口隔离和名称唯一性；[SubscriptionNamesTest](../tests/Feature/Desktop/SubscriptionNamesTest.php)。实际连通性需客户端请求验证 |
| 桌面客户端认证与设备管理 | [DesktopRoute](../app/Http/Routes/V1/DesktopRoute.php)：`auth/*`、`devices/*`、`user/profile`、`client/config` | 认证接口限流；受保护接口经 `client.auth`，部分还需 `client.device`；[客户端服务](../app/Services/Client)、[ClientDevice](../app/Models/ClientDevice.php)、[ClientRefreshToken](../app/Models/ClientRefreshToken.php) | 刷新令牌轮换、设备解绑与限额；配置下载使用短期授权；[ClientAuthTest](../tests/Feature/Desktop/ClientAuthTest.php)、[ClientApiTest](../tests/Feature/Desktop/ClientApiTest.php) |
| 客户端下载与一键导入 | 公开 `/clients`；用户 `client/import` 见[用户路由](../app/Http/Routes/V1/UserRoute.php) | [下载视图](../resources/views/client/downloads.blade.php)、[ClientDownloadService](../app/Services/ClientDownloadService.php)、[下载清单](../.docker/downloads/manifest.json) | 下载页公开，个人订阅导入需用户身份与资格；[ClientDownloadTest](../tests/Feature/Desktop/ClientDownloadTest.php)；安装包同步和可下载性另行核验 |
| 知识库、公告与工单 | 用户路由的 `knowledge/*`、`notice/*`、`ticket/*`；后台相应管理路由 | [KnowledgeController](../app/Http/Controllers/V1/User/KnowledgeController.php)、[TicketService](../app/Services/TicketService.php)，[Knowledge](../app/Models/Knowledge.php)、[Notice](../app/Models/Notice.php)、[Ticket](../app/Models/Ticket.php) | 知识库按语言、显示状态和有效订阅处理内容；修改时覆盖登录、无有效订阅、普通用户与管理员；本次未执行专项业务验收 |
| 节点、机器、路由与热同步 | 后台 `server/manage`、`server/machine`、`server/route`；[节点路由](../app/Http/Routes/V2/ServerRoute.php) | [ServerService::buildNodeConfig](../app/Services/ServerService.php)输出 routes、custom_outbounds、custom_routes；[ServerObserver](../app/Observers/ServerObserver.php)通知变更；[Server](../app/Models/Server.php)、[ServerMachine](../app/Models/ServerMachine.php) | 节点接口经 `server`；机器接口由 [MachineController](../app/Http/Controllers/V2/Server/MachineController.php)校验机器 ID、token 和启用状态。配置下发成功不等于网络路径可用 |
| 节点与机器监控覆盖 | 后台服务器详情的 1–24h 负载趋势、节点状态；[覆盖核对](../progress-log.md#2026-10-18节点稳定性监控覆盖核对) | [机器上报](../app/Http/Controllers/V2/Server/MachineController.php)保存资源与速率历史；[Server](../app/Models/Server.php)公开子节点读取父后端心跳；[掉线命令](../app/Console/Commands/CheckServer.php)未在主调度表注册 | 2026-10-18 后台 14 台在线、资源上报正常；新入口未列入机器管理。尚未确认面向用户网络、逐公开节点的持续全链路探测和通知闭环，后端在线不等于入口可用 |
| VPN 第一阶段替换与 SSH 加固 | [第一阶段运维](./zh-CN/installation/vpn-stage1.md)、[替换决策](../.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md) | 原入口域名保留，新机 TLS → 独立 WireGuard → 原 13 个后端；公钥 SSH、Fail2ban、默认拒绝入站防火墙；复用现有公开 ID、parent_id、用户身份和权限组 | 切换前按新 IP、切换后按域名完成 13 条 HTTPS 出口和 UDP DNS；无效身份拒绝、套餐数量、CF 备用及端口隔离通过。旧入口可回退，模板兼容、长期稳定性和大陆速度另行验收 |
| 专属出口、容量与故障迁移 | 订单开通和订阅获取；[PrepareDedicatedPlan](../app/Console/Commands/PrepareDedicatedPlan.php)、[CheckDedicatedExits](../app/Console/Commands/CheckDedicatedExits.php) | [DedicatedExitService](../app/Services/DedicatedExitService.php)、[健康检查](../app/Services/DedicatedExitHealthService.php)，[DedicatedExit](../app/Models/DedicatedExit.php)、[DedicatedAssignment](../app/Models/DedicatedAssignment.php) | 复用每出口五账号、下单预留、取消释放和备用出口迁移；[专属出口测试](../tests/Feature/Dedicated)覆盖容量、隔离、失败与并发；线上库存和健康状态需实时检查 |
| 插件与配置 | [管理路由](../app/Http/Routes/V2/AdminRoute.php)、[PluginServiceProvider](../app/Providers/PluginServiceProvider.php) | [PluginManager](../app/Services/Plugin/PluginManager.php)、[HookManager](../app/Services/Plugin/HookManager.php)、[SettingService](../app/Services/SettingService.php)，插件目录与数据库配置 | 沿用插件启停、迁移与钩子机制；持久化插件目录与镜像内容需分别核对；[插件开发说明](./en/development/plugin-development-guide.md) |
| 运维、构建与部署 | [xboard 管理脚本](../.docker/production/xboard.sh)、[Docker CI](../.github/workflows/docker-publish.yml)、[手动生产工作流](../.github/workflows/deploy-production.yml) | 主线 `master` 推送构建 amd64/arm64 镜像；部署工作流通过 `workflow_dispatch` 选择 inspect/deploy/install-cli | [操作测试](../tests/Operations/test_xboard_manager.py)、[操作检查 CI](../.github/workflows/server-manager-check.yml)；更新后需核验运行镜像 revision。当前无 GitHub Release/安装包发布工作流 |
| 能力核对、决策与进展 | [README](../README.md)、[progress-log](../progress-log.md)、[决策说明](./AGENT_NOTES.md) | [项目规则](../AGENTS.md)、[workflow.py](../.agents/workflow.py)、[安装清单](../.agents/workflow-install.json)、[笔记 CI](../.github/workflows/agent-workflow.yml) | Python 3.9+、Bun；`doctor` 检查完整性，`verify` 检查结构、相对链接和归档封印；不替代业务验收或自动配置分支保护 |
| 节点质量探针 | 后台首页监控卡片、侧栏节点质量、内部明细对话框；`/<安全路径>/node-probes`；`probes:create` | 管理 API 使用 admin/log；agent 使用独立哈希令牌，仅获取自身配置及上报指定节点。NodeProbeService、SingBox 出站复用、五张探针表；NAS Python + sing-box | 双目标 HTTPS、上下行完整字节、过期/故障/恢复、24h 明细/30d 汇总；独立监控账号、无直连回退。见[运维文档](./zh-CN/installation/node-probes.md)、[决策](../.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)、`tests/Feature/Probes` 与 `tests/Probes`；NAS 探针 1.0.2 已接入正式后台，实际验收状态见进展记录 |

## 验证入口

仅运行改动相关的检查，记录实际结果；以下是入口，不代表本次已全部执行。

```bash
python3 .agents/workflow.py doctor
python3 .agents/workflow.py verify
# PHP 业务改动：先准备 composer 依赖及测试运行时
php vendor/bin/phpunit
# 服务器管理脚本改动
bash -n .docker/production/xboard.sh
shellcheck .docker/production/xboard.sh
python3 -m unittest discover -s tests/Operations -v
```

[`phpunit.xml`](../phpunit.xml) 使用测试环境、SQLite 内存库、array 缓存和 sync 队列。根 [`package.json`](../package.json) 没有前端构建脚本；前端或子模块变更需按其实际工程验证。当前依赖以 [`composer.json`](../composer.json) 的 PHP ^8.2、Laravel ^12.0 为准。
