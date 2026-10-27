# Agent Note: 卡皮巴拉内网域名自动直连

Status: implemented

## Problem

Windows 用户反馈办公网站在退出客户端后可访问，其他代理客户端的 PAC/系统代理也可访问，本客户端出现连接关闭。域名解析返回私网地址；隔离 Mihomo 实验复现订阅私网规则含 no-resolve 时，域名在后续 GEOIP 才解析，随后落入代理出口。实际故障电脑尚未采集运行配置，不能用这个复现解释所有模式的报错。

## Decision

客户端净化配置时加入可解析域名的私网直连规则，覆盖 RFC1918、回环、链路本地、IPv6 ULA 与共享地址空间，不加入公开 Apple 网段、fake-ip 网段或全部中国地址。规则模式保持用户显式规则优先，然后服务域名、内网规则、订阅规则。

全局模式在内核使用 rule，规则仅为内网 DIRECT 和 MATCH,GLOBAL；界面模式、持久化和节点选择仍使用 Global。公网继续使用已选节点，内网自动直连。配置确认、可见节点列表与回退均区分界面模式和内核模式。直连 DNS 在订阅没有显式设置时使用 system，保留订阅已有 direct-nameserver 与公网 DNS 策略。

## History audit

- [分流模式](../../implemented/feature/2026-10-26-capybara-routing.md)：部分取代全局模式直接映射内核 global 的决定；原有设置、验证及回退保留。
- [模式节点保留](../../implemented/bug-fix/2026-10-27-capybara-mode-selection.md)：部分重叠，模式按界面语义切换，不因内核 rule 映射重置选择。
- [Windows 代理](../../implemented/bug-fix/2026-10-27-capybara-windows-proxy-compat.md)：独立的系统代理格式与回环例外，本次不修改恢复契约及既有未提交记录。
- [桌面架构](../../implemented/architecture/2026-10-23-capybara-desktop.md)：复用净化、私有控制器，无 TUN 或新增监听。
- [Google DNS](../../implemented/bug-fix/2026-10-18-clashmeta-google-dns.md)：保持订阅公网 nameserver-policy/fallback 和节点启动解析，本次只补直连解析默认值。
- 香港入口、网站、邀请及节点探针与此次客户端路由无关，保留未提交内容。

## Alternatives considered

- Windows 代理例外能绕开内核，但 IP 通配符不能可靠覆盖域名，逐个让用户设置不符合开箱即用；不采用手工设置作为产品方案。
- 只删私网 no-resolve 改动小，但内核 global 会忽略全部规则；在客户端统一生成全局公网出口规则。
- 全部 DNS 改为 system 能发现更多企业私有域，但会破坏既有公网代理 DNS 策略；只为直连设置系统解析默认值。仅企业 DNS 可解析的域名仍可能需要用户的显式直连规则。
- 硬编码反馈中的企业域名见效直接，但不能解决同类网络且泄露用户信息；仅使用通用地址分类和合成测试域名。

## Verification

- 已通过固定 Mihomo 的混合端口 HTTP 与 CONNECT 域名访问在三模式下均可抵达合成内网目标，公网全局请求确实经过选定代理；全局忽略普通自定义规则，规则模式保留显式覆盖。
- 已验证直连 DNS 默认 system、已有显式解析与订阅公网策略保留；模式选择、热更新、回退、首刻 GLOBAL 选择回归通过。
- 本地前端75、脚本16、Rust59（1项既有手动钥匙串忽略）、TypeScript/Vite和cargo fmt通过；笔记校验与四目标发布见进展。实际 Windows 办公网由用户升级复测，不能以本机隔离测试替代。

## Consequences

全局语义变为“公网全局代理、内网直连”，需在界面与发布说明明确；IP 规则需解析域名，可能增加 DNS 等待。无公开解析结果的纯企业域名不保证自动发现。用户显式规则仍可拦截或代理内网。不会替用户绕过办公网络权限，也不修改操作系统 DNS。

实现与发布状态见[项目进展](../../../../progress-log.md#2026-10-27办公网域名自动直连)。
