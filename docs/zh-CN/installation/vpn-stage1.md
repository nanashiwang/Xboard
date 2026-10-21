# VPN 第一阶段入口运维

本页记录第一阶段迁移后的职责和维护边界；验证证据见 [progress-log](../../../progress-log.md)，方案取舍见[架构笔记](../../../.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)。不保存私钥、用户 UUID、订阅 token 或实际 WebSocket 路径。

## 拓扑与客户端

- 第一阶段：`143.203.200.5`，管理端口 `22`，现有域名 `hk.taige.us:443` 继续作为 VLESS / WebSocket / TLS 入口。域名中的 hk 是兼容名称，不代表新服务器地域。
- 第二阶段：原 12 台美国出口和 `103.24.217.171` 香港出口；2026-10-21 增加 [FriendHosting 日本出口](./japan-node.md)和[荷兰、罗马尼亚出口](./europe-nodes.md)，共 16 条主线路。原出口身份保持不变。原香港机器同时保留旧入口，供 DNS 缓存过渡和局部回退。
- 新隧道：`wg-vpn-stage1`，UDP `51872`，入口 `10.79.0.1/32`、香港 `10.79.0.3/32`、美国 `10.79.0.4–15/32`、日本 `10.79.0.18/32`、荷兰 `10.79.0.19/32`、罗马尼亚 `10.79.0.20/32`。AllowedIPs 仅为对应 `/32`，不改默认路由。
- 公开节点 ID `314–326` 保持不变，仍关联原隐藏后端；四条 CF 备用维持原入口。日本 #354 → #353、荷兰 #356 → #355、罗马尼亚 #358 → #357，权限组均仅 1–4；四档普通套餐节点数为 `17 / 18 / 19 / 20`，独享套餐不含三台 FriendHosting 节点。
- 更新原订阅即可获得「第一阶段入口」名称；原订阅地址、身份和节点协议参数保持不变。旧客户端缓存旧 DNS 时仍能经过旧入口。既有 sing-box 订阅模板兼容待办另行记录，本次代理验收不能代替全部客户端验证。

## 新服务器防护

SSH 使用已有 `flawless_la_02` 密钥，保持 root / 22；禁用密码和键盘交互认证，限制为 publickey，`MaxAuthTries=3`、`LoginGraceTime=30`、`MaxStartups=10:30:40`，关闭 X11 转发。

`vpn-stage1-firewall.service` 加载独立 `inet vpn_stage1` 表，默认拒绝输入和转发，保留回环、已建立连接及 ICMP/ICMPv6，开放 TCP 22/80/443；UDP 51872 仅允许已登记的 16 个出口源 IP。Fail2ban 的 sshd jail 在 10 分钟内累计 5 次失败后封禁 1 小时，重复失败递增，最长 1 天。防护降低猜测和意外暴露风险，不构成 DDoS 防护或绝对安全保证。

文件位置：

- `/etc/ssh/sshd_config.d/00-vpn-stage1.conf`
- `/etc/vpn-stage1.nft`、`/usr/local/sbin/vpn-stage1-firewall`
- `/etc/fail2ban/jail.d/vpn-stage1.local`
- `/etc/wireguard/wg-vpn-stage1.conf`（含私钥，只能在服务器内查看）
- `/etc/nginx/sites-available/hk.taige.us.conf` 与 `/etc/nginx/snippets/hk-xboard-routes.conf`

Nginx 依赖防火墙和 WireGuard 启动成功，关闭版本信息，保留 WebSocket 长连接；443 严格 TLS，80 保留 ACME 验证和 HTTPS 跳转。证书续期由新入口的 `certbot.timer` 负责，模拟续期已通过；原香港机器的旧续期定时器已停用。

出口机保留原 `xboard-private` 隔离规则，只增加 `wg-vpn-stage1` 上源地址 `10.79.0.1` 对 TCP 31443 的访问；独立 `vpn_stage1_peer` 表限制 UDP 51872 来源。香港旧入口的附加端口隔离表也必须包含这一精确允许规则，否则香港出口会被另一条链丢弃。

## 检查与维护

### 分段监控

后台「节点质量」现已接入本入口：NAS 直连 HTTPS 健康请求、入口机器资源、16 条出口隧道与原完整线路结果分层展示。4 条 CF 备用不绑定此入口。入口与资源历史在页面内查看；指标口径、映射调整及采集器配置见[节点质量运维](./node-probes.md#第一段入口机器资源与出口隧道)。

入口采集程序为 `/opt/xboard-ingress-monitor/monitor.py`，systemd 服务为 `xboard-ingress-monitor.service`，私有配置为 `/etc/xboard-ingress-monitor.json`（root:600）。日常可用 `systemctl status xboard-ingress-monitor` 和 `journalctl -u xboard-ingress-monitor -n 20` 检查上报；不要将配置内容写入日志。仅停止此采集服务不会停止业务 Nginx 或 WireGuard。

### 入口服务检查

在新入口执行：

```bash
sshd -t
sshd -T
nginx -t
systemctl is-active ssh vpn-stage1-firewall fail2ban nginx wg-quick@wg-vpn-stage1
systemctl is-enabled vpn-stage1-firewall fail2ban nginx wg-quick@wg-vpn-stage1 certbot.timer
fail2ban-client status sshd
wg show wg-vpn-stage1 latest-handshakes
nft list table inet vpn_stage1
curl -fsS https://hk.taige.us/healthz
```

健康检查应返回 `vpn-stage1-ready`；它只证明 TLS 入口，不能代替每条出口的代理请求。面板主机 `/root/Xboard/backups/stage1-20261017/` 保存本次受限备份和验证脚本；`panel_new.py verify` 固定新 IP、保留正确 SNI，用实际身份逐条检查 HTTPS 出口和 UDP DNS，`audit` 检查套餐节点数和机器心跳。测试文件会临时包含用户凭据，只能保留在 root 私有目录，测试结束删除客户端配置。

修改防火墙时，先检查候选语法，保留独立 SSH 会话和限时回退。使用自有加载脚本原子更新自有表，避免 `flush ruleset`。不要直接重启防火墙服务而忽略 `Requires` 依赖可能停止 Nginx 或隧道；加载规则后重新核验关联服务。

## 局部回退

本次没有替换旧 `wg-xboard`，也没有删除原香港 Nginx 路由。新入口故障时，可把 `hk.taige.us` 的 A 记录恢复到 `103.24.217.171`，保持 DNS only；恢复前先按旧 IP 与严格 SNI 验证旧入口。日本、荷兰、罗马尼亚新增路径未同步到旧入口，回切前需同步其隧道及路由，或先隐藏这三条节点并撤下对应探针。DNS 缓存生效时间内新旧连接可能并存。

服务器配置备份在各机器 `/root/xboard-stage1-20261017/`；公开节点名称变更前后快照在面板上述私有目录。仅恢复明确受影响的文件或节点字段，不能用旧整库覆盖新订单、用户或用量。若回退长期保留旧入口，需重新接管并验证其证书续期。

保留旧路径意味着仍需维护旧机；清退旧入口及旧隧道应作为后续独立操作，并先确认 DNS 缓存和连接已迁移。本次不证明大陆运营商速度、长期稳定性、全机重启恢复或逐字节计费准确性。
