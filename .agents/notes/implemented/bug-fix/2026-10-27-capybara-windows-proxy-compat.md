# Agent Note: Windows 系统代理地址兼容原生 HTTP 客户端

Status: implemented

## Problem

用户确认 Windows 同一个节点在 v2rayN 正常，卡皮巴拉规则和全局模式下 YuanHeng OpenAI Official /responses 均报上游超时（os=10060），浏览器访问正常。卡皮巴拉将 ProxyServer 写为分协议列表，YuanHeng 锁定的 reqwest 0.12.28 / hyper-util 0.1.20 在 Windows 将整个值当单个 URI，无法识别列表后可能直连。此兼容问题发生在进入 Mihomo 之前，切换分流模式无法改变它；该用户现场尚未抓取连接证据。

用户随后报告本机15721的裸502 Unknown error。本轮尚未收到新错误的系统/版本确认，按前述Windows场景审查发现另一遗漏：旧测试只验证外网HTTP/HTTPS，单地址生效后未为本机URL补旁路。YuanHeng当前及既有Core版本对正常转发错误均富化Provider/model/cause，裸502优先排查进入Core之前的链路，不能仅凭状态码认定上游故障。

## Decision

Windows 系统代理使用单一 `127.0.0.1:<mixed-port>` 地址；HTTP 和 HTTPS 使用同一 Mihomo mixed 监听端口。恢复时严格识别本次端口的新格式和旧版完整分协议格式，继续逐字节恢复原设置；其他端口、地址和混合第三方配置不视为本程序所有。保留现有通知、恢复记录和独立守护流程。

Windows代理例外保留原列表并补齐显式loopback地址，避免Codex到元衡的本机请求进入Mihomo。不能仅依赖Windows的`<local>`或`127.*`，旧原生HTTP匹配器不理解这些模式。新增例外原值快照与所有权判断：旧journal没有该字段则不修改它，新journal显式null才代表原本缺失；断开时只恢复自己写入的值，用户后来改动的例外保留。

## History audit

- [桌面架构](../../implemented/architecture/2026-10-23-capybara-desktop.md)部分重叠，沿用回环监听、独立恢复进程及原值快照；本篇细化 Windows 代理格式与旧版本恢复。
- [Windows 诊断](../../implemented/process/2026-10-26-capybara-windows-diagnostics.md)部分重叠；保留历史节点问题的现场证据边界，不以本次源码缺陷覆盖所有旧故障。
- [点击节点即连接](../../implemented/feature/2026-10-27-capybara-select-connect.md)部分重叠；上次未连接问题已由用户确认，与本次已连接后的原生应用超时分开。
- [分流模式](../../implemented/feature/2026-10-26-capybara-routing.md)无需修改，接入代理之前的兼容错误不能靠全局或规则模式处理。

## Alternatives considered

- 在 YuanHeng 实现分协议注册表解析可以兼容更多系统代理软件，但只修复一个使用方；卡皮巴拉所有协议本来就指向同一 mixed 端口，单地址可修复更多原生 HTTP 使用方。
- 调整 chatgpt.com DNS 或增加超时可以处理真实解析或链路问题，但无法修复网络库忽略系统代理的解析失败，不基于报错中的通用建议改变节点配置。

- 只在Mihomo规则内加本机DIRECT能保护规则模式，但全局模式跳过规则，不能保护进入代理之前的本机请求；在Windows系统代理例外层处理。
- 给应用永久设置全局NO_PROXY可快速绕过，但会覆盖用户环境并影响其他进程，且已运行进程未必重读；只管理卡皮巴拉开启期间的系统代理字段。

## Verification

隔离临时Rust工程使用YuanHeng精确锁定hyper-util0.1.20，目标为chatgpt.com的codex/responses：旧列表intercepted=false，单地址与带http协议单地址均true。仓库新增真实matcher回归验证HTTP/HTTPS选中代理，以及新旧格式所有权保护；Windows独立临时HKCU子键覆盖原值/类型/缺失字段恢复、旧journal及第三方代理保护，不修改实际系统代理。本地前端74、脚本16、Rust53通过（1项既有手动钥匙串测试忽略），类型/构建/格式通过；Windows CI54项及四目标构建通过，18附件Release和四目标签名已验证；公网分发与用户现场状态见[进展](../../../../progress-log.md#2026-10-27windows-原生应用代理兼容修复)。

回环复现：hyper-util0.1.20对空列表、`<local>`和`127.*`仍代理127.0.0.1；显式loopback列表让三个本机地址直连，同时chatgpt.com继续代理。内置Mihomo隔离环境仅使用本机HTTP服务与不可达本机代理：直接请求200，全局经代理返回空502，规则的127/8 DIRECT返回200。未发送模型请求或修改真实系统代理。0.1.9本地前端74、脚本16、Rust56项与类型/构建/格式通过；新增3项跨平台回归、Windows原生61项通过，含隔离注册表6项（比0.1.8净增4项），包含原值/旧journal/用户改动/非法格式/失败重试。类型或UTF-16损坏在写journal前拒绝；例外读取异常保留journal，ProxyServer最后恢复以保留失败重试所有权。四目标构建、18附件正式Release与4目标签名已核验；分发状态见[本机502进展](../../../../progress-log.md#2026-10-27windows-本机调用502修复)，故障电脑仍待复验。

## Consequences

统一地址可被浏览器与原生HTTP库共同识别，HTTPS使用同一mixed监听的HTTP CONNECT，不需要单列SOCKS协议映射。恢复需要同时维护两个精确格式，换成其他地址/端口时不覆盖。应用自身忽略系统代理或使用显式/环境代理仍按各自规则处理，不包含TUN。用户Windows真实请求需安装后复验；本次不把旧美国01诊断或其他上游故障一并宣称解决。升级后连接代理并完整退出重开Codex可避免沿用已缓存的HTTP代理匹配器；YuanHeng定期刷新不覆盖Codex到本机的前一段。客户端二进制、Release及官网分发分别核验。
