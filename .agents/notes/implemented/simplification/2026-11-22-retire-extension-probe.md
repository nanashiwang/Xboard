# Agent Note: 退役面板服务器的拓展线路探针

Status: implemented

## Problem

管理员要求删除节点质量页面下方的拓展线路探针。管理列表读取全部探针，停用后仍有卡片。

## Decision

停止专用采样服务并撤销开机启动，删除经身份核实的探针登记与其专属采样。使用现有生产工作流和数据库备份。NAS 与此探针共用监控账号。

## Alternatives considered

页面过滤可隐藏卡片，但后台仍消耗监控流量。只停服务会在后台留下失联卡片。

## Consequences

旧令牌随登记删除而失效。历史人工恢复流程的公开路径验收绑定探针 2，退役后不能用该令牌重新验收或发布线路。自动保护定时器独立核对订阅及已批准公钥。生产验收以[进展记录](../../../../progress-log.md#retire-panel-probe-20261122)为准。

## Existing decision audit

本决定取代[拓展线路接入](../architecture/2026-10-21-tiered-upstream-route-family.md)中新增常驻探针 2 的选择。通用[节点质量采样](../feature/2026-10-18-node-quality-probes.md)仍由 NAS 使用。
