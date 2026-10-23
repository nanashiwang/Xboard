# 卡皮巴拉桌面客户端

蓝围巾旅行水豚首页与地球头像图标，面向本站账号的 Windows、macOS、Linux 桌面客户端。版本 **0.1.0-alpha.2**。代码位于 Xboard 仓库的独立 desktop/capybara 工程，PHP 镜像不包含桌面构建文件。

## 已实现

- 账号登录、设备 UUID、系统凭据库保存续期令牌、串行续期及退出登录；密码和访问令牌不落盘，前端拿不到令牌。
- 每 30 秒直接请求 `user/subscription`，展示剩余流量、用量、重置时间和到期时间；耗尽、到期、无套餐与同步失败有不同提示。资格失效会停止连接，状态发生变化时尝试系统通知（是否显示受系统通知权限控制）。
- 一键系统代理、规则分流、线路选择、连接检测。连接前重新核对套餐并下载校验配置；连接期间每小时更新配置，失败继续使用上次配置。
- 独立连接管理进程，在主程序退出、崩溃或内核退出时尝试恢复原代理；保留恢复记录供下次启动修复。检测到已有系统代理时拒绝覆盖，需先关闭其他代理客户端。
- 浅色、深色、窄窗口、登录弹窗、账户中心/支持入口与不含凭据的诊断摘要。

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
- 未配置 Windows 代码签名、macOS Developer ID 公证或签名自动更新。当前只能手动安装测试版；构建成功不代表三系统真实账号、代理权限、休眠恢复和所有网络环境已验收。
- 服务端配套支持 `X-Core-Version`，应用版本不再误作 Mihomo 版本。此提交不部署服务器，生产仍需在后续部署后核对。

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

开发界面：`npm run dev` 后访问 `http://127.0.0.1:1420/`。只有开发服务器支持 `?preview=active`、`?preview=exhausted`、`?preview=offline`，明确标注模拟数据；生产构建关闭模拟桥接，普通浏览器不能登录或修改系统代理。

## 构建与发布

```sh
npm run desktop:build
```

[Capybara Desktop 工作流](../../.github/workflows/capybara-desktop.yml)在各平台运行前端测试、Rust 测试、真实打包内核的控制接口/配置回退测试，构建四个目标的五个安装包并产生摘要。手动触发且 `publish=true` 时，只有全部目标成功才创建 `capybara-v<version>` 预发布及源码附件；正常 push 仅构建。版本需同步 package.json、Cargo.toml 和 tauri.conf.json，说明写入 RELEASE_NOTES.md。

本地检查、GitHub Actions、安装包发布和生产验证分别记录在[进展日志](../../progress-log.md)。架构约束见[决策笔记](../../.agents/notes/implemented/architecture/2026-10-23-capybara-desktop.md)；图片说明见 [BRAND.md](BRAND.md)，许可证和来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
