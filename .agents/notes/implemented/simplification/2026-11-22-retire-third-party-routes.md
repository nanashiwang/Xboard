# Agent Note: 退役全部第三方拓展线路

Status: implemented

## Problem

上一轮保留了 41 对可恢复的拓展线路。用户现明确要求全部删除，其中含仍向进阶、旗舰套餐下发的线路。

## Decision

使用原分配清单校验每一对的 ID、角色、标签和机器，停止拓展专用服务和定时任务，移除 82 条节点登记。保留自建入口、家庭 NAS 及独享分配。

## Alternatives considered

隐藏订阅仍会留下节点管理记录和转发服务。仅删数据库登记无法验证旧客户端配置已失效。

## Consequences

旧订阅更新后移除第三方节点，旧缓存对应的入口路径和监听也要撤下。四档普通套餐各保留同一组六条自建线路。停用机器 21 的面板认证，历史统计继续按原 ID 留存。独立备份面板数据库及入口配置。恢复必须先验证上游，再按需恢复指定配置。见[生产进展](../../../../progress-log.md#retire-third-party-routes-20261122)。

## Existing decision audit

本决定取代[第三方线路接入与保护](../architecture/2026-10-21-tiered-upstream-route-family.md)和[上轮节点清理](./2026-11-22-remove-retired-node-rows.md)中保留可恢复第三方线路的决定。[面板探针](./2026-11-22-retire-extension-probe.md)已单独退役。
