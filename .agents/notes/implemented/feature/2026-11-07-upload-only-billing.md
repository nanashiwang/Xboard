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

本地 Operations/耗尽提醒 30 项/178 断言通过：新任务经序列化和真实数据库处理只累加上传额度/日统计，覆盖纯上传、纯下载、双向、1×/2×/5×，节点原始双向统计保留。历史 download_only、upload_only 重试及无标记双向任务保持原语义。前端 4 项、JS/PHP 语法及笔记校验通过。CI 108 项/661 断言和双架构镜像完成，生产 1839948 已备份数据库后部署 Healthy；七个运行源哈希及三种模式匹配。

2026-11-07 23:04:10→23:05:58 两笔新任务上传 60,279 字节、下载 7,880 字节、倍率 2，账户与日统计均只增加上行 120,558，下行不变。公网页面已确认仅上传说明。七条自有线路 HTTPS/UDP DNS 通过，既有扩展 #392 仍失败，整体探测工作流为失败。Release web-20261107-1839948 三项附件已回读验证，详见[进展证据](../../../../progress-log.md#2026-11-07计费改为只上传)。

## Consequences

旧代码不认识 upload_only，因此回退旧镜像前须处理新模式的排队任务，不能直接假设旧镜像兼容。原有倍率仍作用于上传；历史已扣下载留在总额中。客户端规则/全局未上报的边界不变。
