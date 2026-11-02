# Agent Note: Hub 导航与 Go 应用双域分工

Status: implemented

## Problem

用户指定 capybarahub.fyi 为导航域、capybarago.uk 为实际应用域，最初要求方案和本地预览，随后明确授权直接上线。截图确认首次流程：导航 → 白底、仅一个「点击进入官网」蓝色按钮 → 原有登录/用户中心。参考站已有登录会话不能代表首次访问流程；本项目继续使用原账号和同一数据源。

## Decision

| 域名或路径 | 当前职责与边界 |
| --- | --- |
| capybarahub.fyi `/` | 独立静态导航，保留应用/下载入口；删除用户指定的账号说明、帮助区与页脚；无需登录、不加载 Go API、不自动跳走 |
| Hub `/downloads` | Windows、双架构 macOS、Linux AppImage/deb 五种 0.1.9 安装包链接及校验文件；主下载为 Go，备用为独立 GitHub Release；不含模拟交互 |
| capybarago.uk `/` | 白底单按钮，点击后进入 `/#/login`；仅根浏览器页面启用，不强制已经收藏的 hash 深链接经过按钮 |
| Go `/api/*`、订阅、`/desktop/login`、`/clients`、`/downloads/*`、支付回调 | 复用现有服务，不加点击 Cookie、额外鉴权或全局 302；保持机器接口与原 hash 加载生命周期 |
| taige.us / board.taige.us | 保留原网站、API、订阅、下载和历史回调配置；不能把旧域 API 统一重定向到新域 |
| node/edge.lumavia.fyi | 保留节点路径、身份、独享出口；网站迁移不改节点 |

Go 由明确自有域名白名单进入同一 Xboard 容器；safe_mode 仍拒绝未知域。首次新域浏览器登录可能需要输入原账号，Cookie 不跨域复制，不在跳转参数中传令牌。现有原生客户端仍固定 taige.us，控制接口不会因网站迁移自动改写；恢复版、独立更新索引和签名入口清单仍归属[客户端恢复提案](../../proposed/architecture/2026-11-02-client-entry-resilience.md)。

### 托管、发布与回退

Hub 使用 Cloudflare Pages 项目 `capybarahub`，生产部署 `9156107f-1a62-4077-bebf-8e89f87b51f7`，自定义域 CNAME 指向 capybarahub.pages.dev；控制台确认活动、SSL 已启用。正式六文件产物由 [.docker/hub/build.py](../../../../.docker/hub/build.py) 构建，源码版本 0a068f7。首次 Sites 上传失败，没有产生公开版本，改用既有 Cloudflare 账户；私有 Sites 草稿不属于生产依赖。未来复用 Pages 项目和[发布说明](../../../../.docker/hub/README.md)，不要创建重复项目。

Go上线时的橙云网络路径已由[Go直连跳板决定](2026-11-02-go-direct-relay.md)局部取代：现为仅DNS A155.103.118.155，再严格HTTPS回源。以下保留初始部署的边界和回退基础。初始Go A为107.173.191.23、橙云代理、TTL自动；Cloudflare 已设为完全（严格）。源站新 vhost 独立于 taige/board，从已验证 SHA256 的 taige 配置派生，移除节点 include 和旧 Flawless 跳板信任，保留官方 CF 地址、请求身份清洗与独立下载路由。源配置漂移即停止，nginx 检查/重载失败恢复前状态。复用现有 ACME 账号、续期 hook 与 certbot.timer；不在日志记录 URL 查询或凭据。

主域操作只改 app_url/subscribe_url 两个公开地址，原值必须是 https://taige.us；先验证 Go HTTPS 与接口，再备份到仅 root 可读的 settings.before.json，比较后写入并重载 Octane。运行时 ApplyRuntimeSettings 使用数据库值，所以不改 APP_URL、账号或套餐。支付 notify_domain 保持原配置，支付真实性不由页面 200 推断。`rollback-settings` 只在当前值仍为 Go 时恢复原地址；`rollback` 只移除本次管理的 vhost，回退前应先恢复主设置并调整导航链接。

生产应用沿用 Docker Build and Publish → Production Deploy，应用镜像 revision 为 `0a068f78a70e3c36bff118a55ef75d5bdbc716e6`。后续主域运维脚本和文档提交使用 `[skip ci]`，不把文档 SHA 当作运行镜像 SHA；没有发行新客户端或 GitHub Release。

### 已验证结果与限制

- 本地：PHP 首页/下载 21 测试、198 断言；前端 6 测试；域名运维 7 测试；模板缓存编译、actionlint 与笔记/链接检查通过。
- 云端：网站检查、工作流检查和双架构镜像构建成功；[生产部署](https://github.com/nanashiwang/Xboard/actions/runs/41468674095) 核对运行 revision；[主域切换](https://github.com/nanashiwang/Xboard/actions/runs/41471128961) 成功。
- 首次 activate 已签发证书并重载 nginx，但立即执行的回环 TLS 探针报 issuer 错误；[稍后同探针复验](https://github.com/nanashiwang/Xboard/actions/runs/41470464617) 的五项检查及续期计时器通过，不能将首次失败记录掩盖为成功，也未独立证实其根因。后续探针使用已确认的实际源站地址，保留严格证书校验，不使用 insecure。
- 浏览器实际通过 Hub → Go 单按钮 → 真实登录页；独立下载页列出五种真实文件及备用链接，导航的帮助/页脚和预览标识已移除。没有提交真实账户密码或进行支付。
- 新域五种安装包 Range 返回 206，大小与发布清单一致；Hub 的五项 SHA256 和源站的 40 项校验清单与仓库清单一致。本次没有重新下载所有完整包或做覆盖安装，因此不声称新客户端已恢复。
- Mac 公网请求出现间歇超时，重试路径与浏览器有成功样本；没有做干净的大陆三网无代理验收，不能从本机 curl --noproxy 推断全网可达。旧 taige 国内受阻的原结论仍保留。

### 切流前无代理 Windows 单点验收（23:39–23:45）

用户追加要求实际无代理测试。已核对 Windows 系统/WinHTTP/环境代理、PAC、WLAN 路由、hosts 和常见代理进程；HTTP 探针显式 no_proxy 并保留 Schannel 严格证书验证。Hub 首页/下载及 Go 首页有 200 样本，Go 公开 JSON 配置成功，Windows 安装器 4096 字节 Range 返回 206；但默认顺序请求仍有超时，IPv4 和 IPv6 均有异常样本，主登录脚本在 IPv4 上通过 TCP/TLS 后等待20秒无响应。故公开页可以直连不等于登录/订阅/安装等完整流程可用。

同期百度2/2 HTTPS成功、网关8/8无丢包且1–3ms，仅支持当前到CF访问路径有波动，尚不能确定具体环节，也不能将新域直接归因为旧主域同类封锁。后续需要第二国内网络及独立服务路线验证；单独关IPv6不能由本次证据保证修复。当前生产、DNS和客户端未改；[完整实测](../../../../progress-log.md#2026-11-02新双域-windows-无代理验收)保留全部成功/失败边界。

## Existing decision audit

- [原官网首页](../feature/2026-10-23-capybara-website-home.md)：部分重叠；Go 根页增加单按钮模式，旧域仍使用原首页，不改压缩 umi.js。
- [客户端恢复规划](../../proposed/architecture/2026-11-02-client-entry-resilience.md)：部分重叠；本篇仅实施网页分工与发布，未来选路、缓存、更新信任独立推进。
- [客户端下载](../feature/2026-10-23-capybara-client-downloads.md)：复用既有版本、资产和清单；GitHub 完整包备份独立于应用服务器，未建立第二个自有包仓。
- [节点独立域名](2026-10-22-independent-node-domain.md)、[原网站跳板](2026-10-22-website-flawless-relay.md)：保持旧配置；本次未吸收其他香港入口或 Windows 兼容改动。

## Alternatives considered

- **单一域名承载应用及恢复页**：维护简单，但会一起失联，采用导航/应用分工。
- **Hub 自动跳到 Go**：少一次点击，但无法在应用故障时保留独立导航和下载入口，因此不采用。
- **Go 直接显示登录**：步骤更少；用户截图明确要求单按钮，根页遵循该要求，深链接与机器接口直达。
- **把按钮做全站门禁**：规则统一，但原生客户端、订阅和回调不能点击，因此按钮仅用于浏览器展示。
- **拆分新老站账号**：适用于独立业务，本次是入口迁移；复用原账号、套餐和数据库。
- **继续等待 Sites 上传恢复**：能保留最初托管选择，但归档上传重复失败；采用用户已有 Cloudflare Pages，公开版本独立于 Xboard。

## Consequences

导航与应用是两个发布单元，Go 服务故障不会阻止 Hub 静态内容和 GitHub 备用链接展示。两个域名仍共用 Cloudflare，Go 仍是单应用源站；它们不是两条应用备用线路，也不能保证永久不被阻断。空白按钮页或 hash 路由不消除域名/SNI 层干扰。

旧客户端 0.1.9 仍依赖 taige.us，下载相同版本不能修复其硬编码入口；独立更新分发、恢复版、自动切换、有效缓存和通知客户都不在此次网站发布内。已登录权益、真实订阅导入、支付回调、客户端覆盖升级和三网长期观察仍需各自验收，不能从公开登录页成功代替业务验收。历史[预览](../../../../docs/previews/capybara-entry/README.md) 保留作为设计产物。

后续[登录加载优化](../bug-fix/2026-11-03-panel-startup-latency.md)保持按钮与业务分离；[客户地址通知](../process/2026-11-03-hub-address-notification.md)由用户明确授权，发送状态独立核验。
