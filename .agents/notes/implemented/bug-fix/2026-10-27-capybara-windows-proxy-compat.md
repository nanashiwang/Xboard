# Agent Note: Windows 系统代理地址兼容原生 HTTP 客户端

Status: implemented

## Problem

用户确认 Windows 同一个节点在 v2rayN 正常，卡皮巴拉规则和全局模式下 YuanHeng OpenAI Official /responses 均报上游超时（os=10060），浏览器访问正常。卡皮巴拉将 ProxyServer 写为分协议列表，YuanHeng 锁定的 reqwest 0.12.28 / hyper-util 0.1.20 在 Windows 将整个值当单个 URI，无法识别列表后可能直连。此兼容问题发生在进入 Mihomo 之前，切换分流模式无法改变它；该用户现场尚未抓取连接证据。

## Decision

Windows 系统代理使用单一 `127.0.0.1:<mixed-port>` 地址；HTTP 和 HTTPS 使用同一 Mihomo mixed 监听端口。恢复时严格识别本次端口的新格式和旧版完整分协议格式，继续逐字节恢复原设置；其他端口、地址和混合第三方配置不视为本程序所有。保留现有通知、恢复记录和独立守护流程。

## History audit

- [桌面架构](../../implemented/architecture/2026-10-23-capybara-desktop.md)部分重叠，沿用回环监听、独立恢复进程及原值快照；本篇细化 Windows 代理格式与旧版本恢复。
- [Windows 诊断](../../implemented/process/2026-10-26-capybara-windows-diagnostics.md)部分重叠；保留历史节点问题的现场证据边界，不以本次源码缺陷覆盖所有旧故障。
- [点击节点即连接](../../implemented/feature/2026-10-27-capybara-select-connect.md)部分重叠；上次未连接问题已由用户确认，与本次已连接后的原生应用超时分开。
- [分流模式](../../implemented/feature/2026-10-26-capybara-routing.md)无需修改，接入代理之前的兼容错误不能靠全局或规则模式处理。

## Alternatives considered

- 在 YuanHeng 实现分协议注册表解析可以兼容更多系统代理软件，但只修复一个使用方；卡皮巴拉所有协议本来就指向同一 mixed 端口，单地址可修复更多原生 HTTP 使用方。
- 调整 chatgpt.com DNS 或增加超时可以处理真实解析或链路问题，但无法修复网络库忽略系统代理的解析失败，不基于报错中的通用建议改变节点配置。

## Verification

隔离临时Rust工程使用YuanHeng精确锁定hyper-util0.1.20，目标为chatgpt.com的codex/responses：旧列表intercepted=false，单地址与带http协议单地址均true。仓库新增真实matcher回归验证HTTP/HTTPS选中代理，以及新旧格式所有权保护；Windows独立临时HKCU子键覆盖原值/类型/缺失字段恢复、旧journal及第三方代理保护，不修改实际系统代理。本地前端74、脚本16、Rust53通过（1项既有手动钥匙串测试忽略），类型/构建/格式通过；Windows CI54项及四目标构建通过，18附件Release和四目标签名已验证；公网分发与用户现场状态见[进展](../../../../progress-log.md#2026-10-27windows-原生应用代理兼容修复)。

## Consequences

统一地址可被浏览器与原生HTTP库共同识别，HTTPS使用同一mixed监听的HTTP CONNECT，不需要单列SOCKS协议映射。恢复需要同时维护两个精确格式，换成其他地址/端口时不覆盖。应用自身忽略系统代理或使用显式/环境代理仍按各自规则处理，不包含TUN。用户Windows真实请求需安装后复验；本次不把旧美国01诊断或其他上游故障一并宣称解决。客户端二进制、Release及官网分发分别核验。
