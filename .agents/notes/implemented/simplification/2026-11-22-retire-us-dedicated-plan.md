# Agent Note: 下架旧美国独享家宽套餐

Status: implemented

## Problem

旧套餐把公共线路与五席固定出口捆绑。该出口 IP 同时用于单独销售的代理端口，用户决定收回旧商品。

## Decision

以现有展示、新购和续费开关下架指定套餐，写入前在同一事务内核对有效持有人及全部待支付、处理中的订单。容量页在三项开关关闭且没有有效订阅、占位后收起该套餐。

## Alternatives considered

删除套餐会损失订单关联；只隐藏卡片仍允许发起购买和续订。

## Consequences

官网和桌面商品目录撤下旧计划，旧链接无法下单，历史订单仍可关联名称。独立代理和普通共享节点继续显示。

官网和桌面下单在原分配锁内重读套餐，旧页面不能在下架后创建订单。后台仍可查询历史订单。上线验收见[进展](../../../../progress-log.md#retire-us-plan-20261122)。

## Existing decision audit

[固定出口池](../feature/2026-10-19-owned-fixed-exit-pool.md)的分配与历史数据保留，本决定取代旧套餐继续销售的选择。[容量页](../feature/2026-10-30-residential-capacity-dashboard.md)沿用去重和占位口径。[独立代理](../feature/2026-11-18-residential-proxy-sales.md)继续按端口销售。
