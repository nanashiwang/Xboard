# Agent Note: 用户套餐改为只计上传

Status: implemented

## Problem

用户在只下载计费上线后明确改为“只计算上传，下载不算”。需要切换新上报口径，同时保证已排队的只下载任务和更早的双向任务按原口径执行。

## Decision

沿用 TrafficBilling 与入队快照，新增 upload_only；UserService 新任务使用该模式，用户额度与日统计只计算客户端发向节点的上传乘原节点倍率，下载免费。保留 download_only 和缺标记的双向语义，节点原始双向统计不变。页面说明与只读审计同步三种口径。

## Related decisions

已检索活跃笔记。[只下载决定](../../implemented/feature/2026-11-07-download-only-billing.md)被部分取代：新上报默认翻转，旧任务兼容和历史证据继续保留。[UDP 计数修复](../../implemented/bug-fix/2026-11-07-node-udp-traffic-direction.md)和[统计原子性](../../implemented/bug-fix/2026-11-07-traffic-stat-retry-atomicity.md)继续适用；倍率决定不变。无需重复升级节点。

## Alternatives considered

- 直接翻转 download_only 的含义改动最少，但会让已排队/重试任务换方向，拒绝；新增独立模式快照。
- 清零历史下载可立即降低账面已用量，但用户要求的是计费规则，本次保留历史结算，避免追溯改变既有证据。

## Verification

本地 Operations/耗尽提醒 30 项/178 断言通过：新任务经序列化和真实数据库处理只累加上传额度/日统计，覆盖纯上传、纯下载、双向、1×/2×/5×，节点原始双向统计保留。历史 download_only、upload_only 重试及无标记双向任务保持原语义。CI、镜像、生产和 Release 待完成。

## Consequences

旧代码不认识 upload_only，因此回退旧镜像前须处理新模式的排队任务，不能直接假设旧镜像兼容。原有倍率仍作用于上传；历史已扣下载留在总额中。客户端规则/全局未上报的边界不变。
