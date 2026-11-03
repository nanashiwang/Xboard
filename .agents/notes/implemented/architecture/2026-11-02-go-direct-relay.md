# Agent Note: Go 应用改用 DNS 直连跳板

Status: implemented

## Problem

用户要求无代理测试后，Windows证实新Hub/Go经CF有成功样本但反复超时，随后明确决定应用无需橙云、使用既有跳板。单按钮只是页面流程，不是阻断规避能力。

## Decision

仅capybarago.uk使用DNS-only A155.103.118.155 → 严格HTTPS107.173.191.23。Hub保留独立Pages，旧taige/board、节点、账号、主链接和客户端版本保持原值。跳板新增独立vhost和证书，13份邻站配置哈希不变；源站只在Go vhost增加一个跳板地址的真实IP信任，复用既有guarded备份/恢复和Laravel身份头断言。

跳板覆盖公网身份头，固定回源Host/SNI并严格验证证书，支持gzip、安装包Range及原方法/正文，不做私有API公共缓存；ACME本地优先，缺失转源站。证书通过DNS-01先取得，临时TXT清理，切流后成功模拟并保存HTTP webroot自动续期，沿用现有timer/hooks。没有复制私钥、导出SSH Secret或修改用户网络。

## Existing decision audit

- [Hub/Go双域](2026-11-02-hub-application-domain-split.md)：部分替代Go的CF网络路径；角色分工、按钮、账号及下载边界保留。
- [旧taige跳板](2026-10-22-website-flawless-relay.md)：复用已实现模板和身份校验，不改旧站/DNS；其橙云试验保持独立。
- [客户端恢复](../../proposed/architecture/2026-11-02-client-entry-resilience.md)：仍proposed；改入口网络不修复旧客户端硬编码域名。

## Alternatives considered

- 保留Go橙云：可复用边缘防护，但无代理样本反复超时且用户明确选跳板，因此替换应用路径。
- 灰云直源：步骤更少，但未复用用户要求的既有跳板；当前采用已验证配置。
- 仅禁用IPv6：变更小，但IPv4同样出现超时，不能作为完整修复。

## Verification

25项运维测试、actionlint、笔记校验通过。源站prepare/apply/verify Actions成功，伪造头对照、HTTPS/Host、ACME fallback和诊断清理通过；跳板五项严格HTTPS复验成功，13份邻站哈希不变。首次重载后curl35失败保留为暂态记录，根因未独立证实。权威及公共DNS均A155.103.118.155/无AAAA；普通Windows连接确认为跳板。

最终无代理同连接顺序：首页/API/完整主JS为200，约0.857s/0.278s/1.975s；JS1420663字节，SHA256与发布文件一致。独立安装器Range返回206。浏览器按钮到真实登录页通过，未用真实账号登录。此前独立连接多次15–25秒无响应，不能被最终成功样本抹去；Windowscurl不支持HTTP/2，不能归因为HTTP/2。详见[完整记录](../../../../progress-log.md#2026-11-03go-应用关闭橙云并切至跳板)与[运维回退](../../../../docs/zh-CN/installation/website-relay.md#go-应用直连跳板2026-11-03)。

### 点击后登录显示延迟

后续用户明确慢在按钮之后。现有home.js跨页面模式整页刷新，再动态加载约1.42MB主JS（gzip约434KB）；等待期间app为空且未显示进度。当前主JS响应没有明确Cache-Control/ETag/Last-Modified。新一轮Windows主JS约2.45s、小页/API约0.8s；跳板侧压缩JS也有4.73s样本，因此不能把全部延迟只归为客户端网络。公开配置请求不是根应用挂载的前置await。导航独立静态缓存路径与应用不同；用户看到导航快不代表Go可用性相同。

静态资源版本化缓存、提前加载和等待提示是后续优化方向，本次仅诊断，未改上述行为；若取消整页刷新需保留已有hash/history/BFCache契约。详情及完整失败样本见[诊断](../../../../progress-log.md#2026-11-03点击进入官网后登录页显示延迟)。

### 第三方订阅导入和流量同步诊断（2026-11-03）

当前只确认手机报告的 net/http TLS handshake timeout 在取得 HTTP 订阅响应前发生；两端客户端、实际订阅域名及手机网络尚未确认，不能直接认定为同一原因。新域公开接口在同局域网无代理 Windows 本轮 6/6 成功，跳板/源站严格 TLS 和有效证书均通过；旧 taige 默认错误解析、指定正确 CF 地址后仍 TLS 重置，board 同时有成功与 HTTP 阶段重置样本。流量数据随 subscription-userinfo 返回，但未验证用户客户端实际刷新逻辑及真实订阅。沿用现有入口，先核对旧链接与手机网络，不因这次报错修改 TLS 安全设置或订阅模板；详见[本次证据及待办](../../../../progress-log.md#2026-11-03订阅导入与流量同步网络诊断)。

## Consequences

Go已不经过CF橙云，网站与导航职责分离；代价是共享跳板单点及没有CF边缘防护，跨境路径仍波动。切换已完成，长期稳定性、第二国内网络和实际用户业务尚未验收；不把本note的implemented解释成稳定性目标已达成。后续独立入口与客户端恢复仍需实施。DNS回退为Go A107.173.191.23+橙云，保留CF信任；生产应用仍0a068f7，原生客户端0.1.9，无新Release。

后续[登录加载优化](../bug-fix/2026-11-03-panel-startup-latency.md)已实现内容寻址缓存、提前加载及等待恢复，替代下文的未实施建议；网络路径与线路稳定性边界保持。
