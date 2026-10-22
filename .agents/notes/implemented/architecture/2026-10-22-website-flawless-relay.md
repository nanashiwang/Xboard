# Agent Note: 网站经 Flawless 灰云入口

Status: implemented

## Problem

用户确认 taige.us 在大陆无代理访问慢，实测出现接口和主 JS 的 20 秒超时。用户提供既有 Flawless 跳板 155.103.118.155 的密钥，要求网站灰云直连该跳板，并询问是否更快。服务器当前共用多个 HTTPS 站点，不能为面板替换它们的监听器。

## Decision

仅 taige.us 网站主域名使用 DNS-only A 指向 155.103.118.155；board.taige.us 保留现有 CF 路径供兼容和回退。跳板新增独立 Nginx HTTPS vhost，经严格证书校验、固定 SNI/Host 的 HTTPS 转发到现有源站 107.173.191.23。应用、数据库、订阅地址、支付回调域名和节点配置保持原值。

跳板独立签发 taige.us 证书，先用 DNS 验证准备证书而不切流；切换后使用自动 HTTP webroot 续期。HTTP ACME 路径本地优先，缺失时转源站，保留源站独立证书续期。页面资源在跳板 gzip 压缩，私有接口不做公共缓存；保留 Range、WebSocket、HTTP 方法与 HTTPS scheme。

跳板覆盖所有客户端身份代理头，源站仅新增对该跳板的精确信任，并将校正后的真实客户端 IP 传入应用。先检验实际源站配置，避免把全部用户识别成一个跳板 IP 或信任任意伪造头。使用现有手动 GitHub 运维工作流的认证与固定主机校验，不导出密码或证书私钥到日志。

## Existing decision audit

- [节点独立域名](../../implemented/architecture/2026-10-22-independent-node-domain.md)部分重叠：面板与订阅继续 taige.us；lumavia.fyi 节点路线不变，本笔记只接管网站网络入口。
- [第一阶段替换](../../implemented/architecture/2026-10-17-stage1-replacement.md)无关：其 143.203.200.5 是 VPN 入口，不能当作网站源站或本次跳板。
- 现有主域名运维文档保留原切换和证书历史，新增灰云入口现状；没有完全吸收或过时提案需要归档。未提交香港入口文件保持原归属。

## Alternatives considered

- 保留 CF 可继续享有缓存和边缘防护，但大陆样本有间歇超时，不能满足用户本次切换路线的要求；保留 board 作为兼容路径。
- 直接灰云指向源站步骤最少，但当前源站公网延迟较高、JS 未压缩，也不复用用户指定跳板。
- SNI stream 透传可复用源站证书，但共享跳板当前 443 已由多个 HTTP vhost 承载；改全局监听影响其他业务，且还需额外解决源站 PROXY protocol、真实 IP 与压缩，因此新增 HTTPS vhost 更局部。

## Verification scope

- 变更前保存精确 DNS 与服务器配置备份；新增站点通过 nginx -t，既有业务及监控继续可用。
- DNS 切换前以 --resolve 和物理网卡验证新入口严格 TLS、首页、公开配置、JS gzip、客户端页、Range、WebSocket，以及伪造 IP 头被覆盖。
- 同一大陆网络对照原 CF 与新跳板，区分完整下载和半途超时；若新入口明显退化，不切流。
- DNS 切换后核对 A/AAAA、实际连接目的 IP、浏览器页面、自动续期和源站 challenge 转发，保留原主域 DNS 可回退。

## Consequences

灰云主入口不再享有 CF 的缓存和边缘防护，仍受跳板容量、跨境网络及单机故障影响；短时测速不能保证全天或所有运营商更快。证书与真实 IP 链必须在切流前完成。旧 DNS 缓存可能短期继续走 CF，不能仅凭控制台保存宣称所有用户迁移完成。

## Implementation and verification

2026-10-22 已部署独立 vhost、严格回源、gzip 和安全日志；源站 prepare/apply/verify 工作流成功，原 SHA 校验、私有备份、精确 CF/relay 信任和清洗 XFF 生效。12 项针对性测试覆盖漂移、符号链接、备份篡改、nginx 检查/reload 失败恢复、回退保护和临时诊断清理。真实 HTTP 头进入已安装 Laravel 中间件的身份/HTTPS/Host 断言通过，没有更改运行应用或注入业务路由。

用户确认保存后主域灰云至指定 IP；权威与公共解析一致、AAAA 已撤下、临时 TXT 已清理。跳板 webroot/http-01 模拟续期及 reload hook 成功；源站 challenge 回退测试通过，未执行源站完整模拟续期。15 份共享跳板旧配置 SHA 不变，既有业务和监控抽查成功。

大陆同网预检 relay 9/9、CF 8/9，下载页与 Range 字节相同；切后 HTTP/1.1 与 HTTP/2 12/12。追加公网 DoH 样本仍出现一次 15 秒超时，不能把路由切换视为彻底修复。原 `/ws` 在源站与 relay 均 502，本轮仅确认未产生差异，不把它标为业务成功。登录页通过，未冒充客户登录或发起支付。细节、Actions、测速和回退材料见[执行记录](../../../../progress-log.md)及[运维](../../../../docs/zh-CN/installation/website-relay.md)。
