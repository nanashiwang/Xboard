# Agent Note: 从节点管理删除已退役的自建线路记录

Status: implemented

## Problem

节点管理逐项展示公开入口、机器后端和独享别名。两次美国出口退役后，旧记录仍占列表空间。

## Decision

按生产只读清单和退役决定定向删除 38 条。事务内复核节点身份、授权、机器启用、存续子节点、独享占用和探针引用。核对保留节点的配置，先保存一致性备份。

## Alternatives considered

按显隐开关批量删除会影响公开线路的隐藏后端。筛掉所有停用项会掩盖保护器暂时撤下的第三方线路。

## Consequences

13 个旧入口、13 个后端和 12 个独享别名列入清理。删除登记后，旧脚本无法按原 ID 重跑当年的拓扑验收。数据库备份可追溯旧配置，账务和探针历史继续按原 ID 保存。仅在后端及采样源同时退役时解绑停用出口的引用；普通美国线的两个在用后端仍保留。没有探针覆盖的退役入口如有旧监控映射，只清理对应键。[生产结果](../../../../progress-log.md#prune-retired-nodes-20261122)

## Existing decision audit

本决定取代[普通与独享套餐拆分](../architecture/2026-10-21-owned-us-package-split.md)和[美国出口退租](../architecture/2026-10-28-owned-us-retirement.md)中保留这些撤权节点供回退的选择。[第三方线路](../architecture/2026-10-21-tiered-upstream-route-family.md)的 41 对节点由保护器按清单管理。
