# Agent Note: Windows 代理故障的脱敏现场诊断

Status: implemented

## Problem

用户确认 Windows 0.1.5、v2rayN 已退出，美国01家宽在 v2rayN 可用而卡皮巴拉失败。本机相同内核可测通该节点，不能用 macOS 结果推断 Windows 根因。已有界面将内核 HTTP 错误简化为不可达，诊断摘要也不含出站证据。

## Decision

提供独立 PowerShell 5.1 诊断脚本，复用正在运行的回环控制器，只发送 GET、有限节点延迟请求及固定 HTTPS 探针。读取代理开关、进程计数、节点入口 DNS/TLS、内核版本及当前选择，对 Google/Cloudflare 做 5 秒与 12 秒对照。不改系统代理、分流、节点选择、防火墙、凭据或内核配置。控制器只允许 127.0.0.1，禁止重定向；秘密仅留内存。内核日志只输出固定错误分类及计数，原文不保存。报告不含 UUID、密码、令牌、订阅链接、账户、完整配置或机器路径。

## History audit

- [桌面架构](../../implemented/architecture/2026-10-23-capybara-desktop.md)部分重叠，继续保持回环鉴权和凭据边界；本次只补现场工具。
- [节点测速](../../implemented/feature/2026-10-26-capybara-ready-nodes.md)部分重叠，诊断增加对照期限，不改变产品五秒行为。
- [外接线路](../../implemented/architecture/2026-10-21-tiered-upstream-route-family.md)无关，美国01为自建出口，外接 AnyTLS 公钥错误不能代替本次 Windows 证据。

## Alternatives considered

- 直接改超时或 DNS 能快速改变症状，但不能解释同机不同客户端差异；先收集本机分阶段结果。
- 导出原始配置及日志信息最完整，但包含连接凭据及其他访问记录；只保留白名单状态与错误类别。
- 在主应用加入诊断需要所有平台重新打包并升级；独立工具可直接用于已安装 0.1.5，故本轮不增加桌面版本。

## Verification

本机 PowerShell 7.6.9 的 28 项检查通过，覆盖非回环控制器拒绝、鉴权不泄漏、重定向拒绝、HTTP 头及正文超时、真实 TCP/HTTP/WebSocket 夹具、错误分类和报告凭据金丝雀。macOS 实际控制器美国01对照：5 秒返回504，12秒返回200/959ms，Cloudflare返回200/869ms，当前出口代理GET为204；不据此声称 Windows 根因或修复。Windows PowerShell 5.1 CI（run 40319157833）28项通过；修正异步Task空结果后的实际报告为单一对象，秘密扫描通过。用户故障电脑的现场报告仍待采集，不能把合成夹具当作实际网络已恢复。

## Consequences

诊断产生少量探针流量并更新内核测速历史，网络错误会受当时状态影响。系统代理及后台进程只读状态不能证明其他软件 TUN 已完全释放。报告只含类别可能需追加针对性复验，不能宣称捕获到的全部内核事件均由本轮探针触发。
