# Agent Note: Clash Meta 的 Google 分流与代理 DNS

Status: implemented

## Problem

安卓 Clash Meta 的日志反复出现 services.googleapis.cn 被 .cn 规则分到 DIRECT 后解析失败；线上模板与默认 Clash 模板一致，境外域名的 nameserver-policy 只指定 Cloudflare DoH，没有指定查询出口。另有入口超时，配置修复不能代替手机业务验收。

## Decision

Clash Meta 使用独立默认模板：Google API、视频和下载域名规则优先于泛化中国直连规则；境外 nameserver-policy 及 fallback 使用双 DoH 并显式经 $app_name 策略组，节点域名由独立的国内 DNS 解析。保持 TLS 校验、节点参数、权限与其他客户端模板不变。默认模板只用于新安装；现有数据库模板通过后台备份、更新和回读，避免迁移覆盖自定义配置。

## Existing decisions

- [第一阶段入口](../../implemented/architecture/2026-10-17-stage1-replacement.md)：部分重叠，仅复用节点与严格 TLS，不修改网络架构。
- [质量探针](../../implemented/feature/2026-10-18-node-quality-probes.md)：部分重叠，验证位置与业务成功边界沿用；不修改探针。
- owned-hk-wireguard-ingress 为已有未提交工作，本轮不修改或提交。
- project-decision-kit 与本次配置行为无关。

## Alternatives considered

- 只提前 googleapis.cn 规则改动最少，但不解决全局模式仍失败时可能存在的 DNS 出口不可达。
- 修改共享 default.clash.yaml 能覆盖更多客户端，但代理 DNS 参数兼容范围不同，因此只分离 Clash Meta 模板。
- 全局 respect-rules 简洁，但改变所有 DNS 出站；显式指定境外 DoH 出站使范围更明确，并保留节点域名启动解析。

## Testing

- 真实 Laravel 协议输出与新安装迁移：10 项订阅测试、129 断言通过，包括 DNS 占位符替换、Google 优先级、国内直连及其他客户端和自定义模板保留。
- Mihomo 1.18.10 与 1.19.32 对候选与实际下载订阅的配置检查通过。首次检查因缺少 GeoIP 数据库下载超时，补齐官方数据库后重新验证通过，未删除 GEOIP 规则。
- 线上后台自动保存并刷新回读匹配候选（编辑器省略末尾换行）；重新获取订阅确认代理 DNS 与规则优先级，17 个代理定义和全部策略组保持不变。
- 本机 en0、严格 TLS 的真实代理 DNS 查询返回 A 记录，Google 下载取得完整 262144 字节、YouTube generate_204 返回 204。完整订阅首次连接出现入口超时，后续实际域名复测记录在 progress-log；HTTP 404 仅表示 Google 根路径无资源，不能当作 Play 功能成功。

## Consequences

境外 DNS 查询经 $app_name 当前选中的节点，代理节点域名通过独立国内 DoH 启动解析；用户主动选择 DIRECT 时该组仍会直连。已有自定义模板不会随代码升级被覆盖；本次授权站点通过后台更新生效，无需重启面板或节点。回退可恢复本次保存的旧模板；新安装使用独立 Meta 模板，旧安装需显式迁移其数据库内容。

手机内核版本未知，双内核检查不能替代 Android 验收。入口仍可能间歇超时，用户已在安卓手机更新订阅后确认 Play 下载与 YouTube 视频播放均恢复；该业务验收独立于 generate_204 与有限下载，不据一次恢复推断长期线路稳定。
