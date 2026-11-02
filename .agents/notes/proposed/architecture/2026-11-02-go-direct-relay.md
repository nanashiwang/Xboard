# Agent Note: Go 应用改用 DNS 直连跳板

Status: proposed

## Problem

用户要求无代理测试后，Windows 证实新 Hub/Go 经 CF 有成功样本但反复超时，Go 主登录脚本20秒无响应；用户随后明确决定应用无需橙云、直接使用既有跳板。单按钮只是页面流程，不是阻断规避能力。

## Proposal

仅 capybarago.uk 从 CF 橙云直源改为 DNS-only A 155.103.118.155 → 严格 HTTPS 107.173.191.23。Hub 保留独立 Pages，旧 taige/board、节点、账号、主链接和客户端版本不变。先签跳板独立 Go 证书，新增独立 vhost，保留原共享站点；源站只在 Go vhost 增加对这一个跳板的真实 IP 信任，复用既有 guarded 备份/恢复与 Laravel 身份头断言。

跳板覆盖来自公网的身份头，支持 gzip/Range/原方法与正文，不做私有 API 公共缓存；ACME 本地优先，缺失时转源站，切流后切换自动 webroot 续期。证书在切 DNS 前通过 DNS-01 验证取得，临时 TXT 验证后清理，复用现有 ACME 账号，不复制私钥。新路径固定IP验收通过后才关闭橙云，并核对 A/AAAA、默认解析与无代理真实连接。

## Existing decision audit

- [Hub/Go 双域](../../implemented/architecture/2026-11-02-hub-application-domain-split.md)：局部替代 Go CF 网络路径；角色分工、按钮、账号与下载边界保留。
- [旧 taige 跳板](../../implemented/architecture/2026-10-22-website-flawless-relay.md)：复用已实现模板与身份校验，不修改旧站/旧 DNS。
- [客户端恢复](2026-11-02-client-entry-resilience.md)：仍 proposed；入口改线不修复旧客户端硬编码域名。

## Alternatives considered

- 保留 Go 橙云：可复用边缘防护，但单台无代理短样本已经反复超时，用户明确选跳板，因此替换应用路径。
- 灰云直源：步骤更少，但没有复用用户要求的既有跳板，先采用已验证的跳板配置。
- 仅禁用 IPv6：变更小，但 IPv4 也出现超时，不能作为本次完整修复。

## Acceptance criteria

共享跳板原站点配置哈希保持不变；新站及源站 nginx 检查、严格证书校验、真实 IP/伪造头与 ACME 转发通过；Windows 固定跳板与切流后普通解析分别验证首页、公开 API、完整主脚本及安装包 Range，保留任何超时。检查自动 webroot 续期和部署 hook。DNS 回退恢复 Go A 107.173.191.23+橙云，保留 CF 信任；不把短样本解释为三网长期稳定。

## Risks

共享跳板仍是单点，公网路径仍可能波动；DNS缓存短期仍走CF。网站灰云不代表用户账号/付款/节点全链路验收，也不会让旧客户端自动切换新域。移除CF边缘路径是用户明确选择，源站和跳板的HTTPS、鉴权及安全日志仍保留。
