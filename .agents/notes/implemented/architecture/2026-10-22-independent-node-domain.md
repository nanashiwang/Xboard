# Agent Note: 节点入口独立主域名

Status: implemented

## Problem

面板、订阅与节点入口均在 taige.us 下。用户购买 lumavia.fyi，授权将节点入口迁到独立注册域名，降低一个主域名整体不可达时面板与代理同时受影响的风险。更换域名不构成服务器双活，也不解除节点冷启动对面板的依赖。

## Decision

面板、订阅、支付回调和管理 API 保留 taige.us。主入口使用 node.lumavia.fyi，DNS-only A 指向现第一阶段服务器；CF 备用使用 edge.lumavia.fyi，保持原备用源站与代理方式。两者均不 CNAME 回 taige.us。

DNS、新证书和独立 Nginx 站点先就绪，复用既有路由片段，严格 TLS 与完整线路验证通过后同事务修改公开源、固定别名的 host/SNI/WebSocket Host，以及原入口监控 host。保留 ID、用户、倍率、组权限、隧道、上游出站和监控凭据。旧 DNS、站点和证书继续兼容未刷新订阅的客户端，不以重定向替代 WebSocket 服务。

## Existing decision audit

- [第一阶段替换](../../implemented/architecture/2026-10-17-stage1-replacement.md)部分重叠：保留现入口服务器与隧道，仅替换客户端域名；旧域名保留由过渡兼容说明接管。
- [第三方拓展](../../implemented/architecture/2026-10-21-tiered-upstream-route-family.md)部分重叠：41 条线路同步域名，既有鉴权、计量和上游保护保持。
- [自建固定池](../../implemented/feature/2026-10-19-owned-fixed-exit-pool.md)部分重叠：源与别名必须同事务同步，避免健康检查因参数不一致触发迁移。
- 未提交的香港入口笔记与文档保留原归属，不混入本次提交；无过时提案需要归档。

## Alternatives considered

- 同一 taige.us 下分配新子域名可以隔开站点规则，但仍共享主域名生命周期，不能满足用户本次隔离目标。
- 将面板和节点一起换到新域名改动集中，但仍共享同一主域名，并影响订阅和支付回调，因此只迁节点。
- 直接改订阅字段步骤少，但新证书或 CF 源站未就绪会让全部更新客户端断开，因此先验证新入口再切换。

## Testing

新域名在切换前完成 57 条主入口与 1 条七云 CF 线路的严格 TLS、Cloudflare HTTPS 200 / 预期出口、Google 204、无效 UUID 拒绝及有效身份复核，全部首轮通过。切换后从实际数据库重新生成的 58 条线路再次全部通过；四档 Clash Meta / Shadowrocket 共 8 项真实订阅数量为 14/22/34/47，节点名唯一，host/SNI/WS Host 均为新域且保持严格 TLS。旧主入口与旧 CF 备用各抽验一条真实代理通过。

事务更新 74 条记录：69 条主入口源/别名及 5 条 CF 源/别名/停用记录；不恢复停用项。原入口监控 ID 1 仅换 host，11 个固定别名与源的参数一致，绑定在事务中不变。固定别名验证为参数等价与对应源路径实测，本轮不额外触发客户固定分配或使用客户身份。持续采样、配置全量对比和测试身份清理结果见[执行记录](../../../../progress-log.md#2026-10-22节点入口迁移至-lumaviafyi)。

## Operations and rollback

两个新站点分别为 `/etc/nginx/sites-available/node.lumavia.fyi.conf` 与 `/etc/nginx/sites-available/edge.lumavia.fyi.conf`。主入口仍共用 `hk-xboard-routes.conf`；CF 源站继续复用 `qiyun-cdn-routes.conf` 和 `xboard-dedicated-routes.conf`，保留仅允许 CF 来源的规则。片段内部旧 Host 是发给既有后端的 HTTP 字段，不依赖旧域名 DNS，不批量替换共享片段。

两张证书均在 2027-01-19 到期；现有 `certbot.timer` 与部署后 nginx 检查/reload hook 已核验，HTTP-01 分别使用 `/var/www/xboard-acme` 和 `/var/www/letsencrypt`。CF 为完全（严格）；本轮未单独运行新证书模拟续期。不能重跑 `probes:ingress` 按新 host 创建第二入口，而应保留原 ID、机器、令牌和映射。

私有备份与精确 before/after 位于面板 `storage/app/backups/lumavia-20261022/`，入口机 `/root/xboard-lumavia-20261022/` 保存站点材料。回退须核对当前字段后在同一事务仅恢复本次 host/SNI/WS Host 和入口 host；不还原整个数据库，不覆盖后来订单、用量与固定分配。新域名停用前先确认用户已刷新回退订阅，旧站点继续维护。

## Consequences

共同入口、DNS 服务商及管理账户仍可能带来共同故障。证书签发和边缘部署需要等待实际就绪；原客户端须刷新订阅才能获得新域名。回退只恢复本次字段与站点，不整库覆盖订单、用量或固定分配。
