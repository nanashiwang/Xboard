# 卡皮巴拉桌面客户端

蓝围巾旅行水豚首页与地球头像图标，面向本站账号的 Windows、macOS、Linux 桌面客户端。版本 **0.1.0-alpha.9**。未登录首页及登录弹窗提供“注册账号”，在官网注册后返回授权页，确认即可登录客户端；沿用官网验证码、邀请码及注册策略。代码位于 Xboard 仓库的独立 desktop/capybara 工程，PHP 镜像不包含桌面构建文件。

## 已实现

- 套餐页：公开浏览套餐、登录后选择周期/优惠码并下单，沿用网站余额/折扣/换购计算；恢复待支付订单、选择支付方式、浏览器支付或客户端二维码、取消和完成后同步。账户资料从左下角进入。需要服务器部署 `client/plans` 与 `client/store/*`；支持零元开通，支付平台返回不代表开通成功。见[购买决定](../../.agents/notes/implemented/feature/2026-10-25-capybara-store.md)。

- 账号登录（浏览器授权）：复用 taige.us 已登录账号，确认后返回客户端；未登录先走官网，支持取消/重开和五分钟过期。客户端不收集网站密码，网页令牌不离开浏览器；桌面令牌只经原生一次性兑换，设备 UUID、系统凭据库、串行续期和退出登录保留。见[授权决定](../../.agents/notes/implemented/feature/2026-10-25-capybara-browser-login.md)。
- macOS 启动和后台同步静默访问钥匙串；需要权限时显示“登录记录等待授权”，用户点击“恢复登录”后才请求系统授权。macOS 凭据按当前二进制摘要隔离，升级后需重新登录一次账号，同一构建后续启动自动恢复；拒绝后不自动重试，也可重新登录；不会放宽钥匙串权限或明文保存令牌。见[授权决定](../../.agents/notes/implemented/bug-fix/2026-10-25-capybara-keychain-prompts.md)。
- 每 30 秒直接请求 `user/subscription`，展示剩余流量、用量、重置时间和到期时间；耗尽、到期、无套餐与同步失败有不同提示。资格失效会停止连接，状态发生变化时尝试系统通知（是否显示受系统通知权限控制）。
- 一键系统代理、规则分流、线路选择、连接检测。连接前重新核对套餐并下载校验配置；连接期间每小时更新配置，失败继续使用上次配置。
- 独立连接管理进程，在主程序退出、崩溃或内核退出时尝试恢复原代理；保留恢复记录供下次启动修复。检测到已有系统代理时拒绝覆盖，需先关闭其他代理客户端。
- 浅色、深色、窄窗口、登录弹窗、账户中心/支持入口与不含凭据的诊断摘要。
- 每 6 小时检查应用更新，重启保留周期、休眠恢复补查，帮助页可立即检查。用户确认后才下载；Windows/macOS/AppImage 验签、恢复系统代理后安装重启。DEB 确认后打开官网下载页，交由系统安装器更新。更新检查独立于套餐同步。

## 首版边界

| 平台 | 构建目标 | 首版系统代理 |
| --- | --- | --- |
| Windows | x64，NSIS 安装包 | 当前用户 Internet Settings |
| macOS | Apple Silicon / Intel，DMG | networksetup；最低系统版本 12 |
| Linux | x64，DEB / AppImage | GNOME / gsettings，需要桌面会话和系统密钥环 |

- 首版不含 TUN，不能接管忽略系统代理的应用。Linux KDE 等其他桌面的自动代理适配、Windows/Linux ARM 安装包不在此次矩阵中。
- 服务端计费上报有延迟，30 秒轮询不代表字节级实时计费。节点更新与流量状态查询是两个独立周期。
- 站点 API 固定为 `https://taige.us`，使用系统外的直连 HTTP 客户端并禁止重定向；其他软件或系统级 TUN 仍可能影响真实路由。
- 配置只接收本站下发的内置节点、代理组、规则和 DNS。不会继承订阅中的 TUN、对外监听、脚本、外部 UI 或本地证书路径；依赖外部 providers 的自定义模板需要单独适配。
- 未配置 Windows 代码签名或 macOS Developer ID 公证；更新签名只验证来源与更新包完整性。旧 alpha.1/alpha.2 需手动安装 alpha.3 或更新版本一次，之后才能接收后续更新。构建成功不代表三系统真实账号、代理权限、安装升级、休眠恢复和所有网络环境已验收。
- 服务端配套支持 `X-Core-Version`，应用版本不再误作 Mihomo 版本。alpha.6 浏览器授权需要服务端部署相应接口并迁移 `client_browser_logins`，生产终态见根目录进展记录；只安装新客户端不能补齐服务端能力。

## 开发与检查

需要 Node.js 22、Rust stable 和 Tauri 各平台的编译依赖；Linux 还需 WebKitGTK 4.1、DBus、libsecret、AppIndicator 和 librsvg 开发包。

```sh
cd desktop/capybara
npm ci
npm run core:prepare
npm test
npm run build
cargo test --locked --manifest-path src-tauri/Cargo.toml
npm run desktop:dev
```

`core-assets.json` 固定 Mihomo v1.19.33 的官方资产及 SHA-256。`core:prepare` 校验压缩包后解压，不在用户首次连接时下载内核。可通过 `CAPYBARA_CORE_ARCHIVE` 提供预下载的同一官方压缩包，摘要不符即失败。内置 `geoip.metadb` 同样验证固定摘要，避免首次启动依赖远端规则下载。

开发界面：`npm run dev` 后访问 `http://127.0.0.1:1420/`。套餐预览支持 `?preview=store-guest`、`store-pending`、`store-qr`、`store-processing`、`store-empty`、`store-error`。只有开发服务器支持 `?preview=active`、`?preview=exhausted`、`?preview=offline`，明确标注模拟数据；生产构建关闭模拟桥接，普通浏览器不能登录或修改系统代理。

## 构建与发布

```sh
npm run desktop:build
```

[Capybara Desktop 工作流](../../.github/workflows/capybara-desktop.yml)在各平台运行前端测试、Rust 测试、真实打包内核的控制接口/配置回退测试，构建四个目标的五个安装包并产生摘要。手动触发且 `publish=true` 时，只有全部目标成功才创建 `capybara-v<version>` 预发布及源码附件；正常 push 仅构建。版本需同步 package.json、Cargo.toml 和 tauri.conf.json，说明写入 RELEASE_NOTES.md。

本地检查、GitHub Actions、安装包发布和生产验证分别记录在[进展日志](../../progress-log.md)。架构约束见[决策笔记](../../.agents/notes/implemented/architecture/2026-10-23-capybara-desktop.md)；图片说明见 [BRAND.md](BRAND.md)，许可证和来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 更新分发

开发预览另支持 `?preview=keychain` 查看授权受阻状态，不访问真实钥匙串。

开发预览另支持 `?preview=update` 与 `?preview=update-deb`，不会下载或安装文件。

发布必须配置 `CAPYBARA_UPDATER_PRIVATE_KEY` 仓库 Secret；PR 构建不读取密钥，不生成可分发的签名更新索引。发布前验证四目标的包体及可信注释签名，缺包或验签失败阻止发布。更新签名与 Windows 发行者签名/macOS 公证是两回事。

Release 的 `capybara-latest.json` 包含四目标版本、说明、签名和 taige.us 下载地址。发布后将安装包及更新附件加入 `.docker/downloads/manifest.json`，索引文件必须最后列出；执行现有 `sync-downloads`，前面的文件全部验证通过后才原子替换索引，不能只上传新索引。客户端使用每次检查的新查询参数避免静态缓存拖延检查。

密钥只保存在受限本机目录和 GitHub Secrets；公钥随应用配置发布。需保留私钥备份才能继续给已安装用户更新。机制与边界见[更新决定](../../.agents/notes/implemented/feature/2026-10-24-capybara-updates.md)。
