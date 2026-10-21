# FriendHosting 日本节点运维

2026-10-21 接入。本页数量为日本接入时的验收快照；后续[欧洲节点扩容](./europe-nodes.md)后的当前数量见[第一阶段运维](./vpn-stage1.md)。节点名为「日本｜friendhosting｜第一阶段入口」，供轻量、标准、进阶、旗舰套餐使用。独享套餐不包含该节点，后端也不下发独享用户身份。方案见[决策笔记](../../../.agents/notes/implemented/architecture/2026-10-21-friendhosting-japan-node.md)，验证见[进展记录](../../../progress-log.md#2026-10-21friendhosting-日本节点接入)。

## 拓扑与权限

```text
客户端 → hk.taige.us:443（VLESS / WebSocket / TLS）
       → 第一阶段 143.203.200.5
       → WireGuard 10.79.0.18:31443
       → 日本 185.39.31.75 出网
```

| 对象 | 配置 |
| --- | --- |
| 机器 #18 | `friendhosting-日本`，Ubuntu 24.04，SSH 3333 |
| 公开节点 #354 | `hk.taige.us:443`，show=true，enabled=false，machine_id=null，parent_id=353 |
| 隐藏后端 #353 | `185.39.31.75`，server_port=31443，show=false，enabled=true，machine_id=18 |
| 两层节点权限 | group_ids 仅字符串 `1/2/3/4`，dedicated_exit_id=null，倍率 1 |
| 隧道 | `wg-vpn-stage1`，UDP 51872，MTU 1380；日本 10.79.0.18/32、入口 10.79.0.1/32 |
| 监控 | NAS probe #1 包含 #354，预期出口 185.39.31.75；ingress #1 映射 #354 → 10.79.0.18 |

现有 13 个出口继续使用原配置；加入日本后四档普通套餐分别为 15/16/17/18 个真实节点。固定出口池不新增容量或记录。复制已有美国后端时，必须移除其组 5 授权，不能只隐藏独享订阅中的节点名称。

## 日本机器服务

使用已验证的原生 xboard-node，运行用户为 `xboard-node`，工作目录 `/var/lib/xboard-node`。配置为 `/etc/xboard-node/config.yml`，权限 root:xboard-node 0640；禁止将机器 token 写入运维文档或日志。Go 内存软目标 128 MiB、GOGC 75，systemd MemoryMax 256 MiB；新机约 458 MB 内存，实际容量仍需观察。

- `/etc/systemd/system/xboard-node.service` 依赖隧道与防火墙成功启动，开机启用、失败自动重启。
- `/etc/xboard-jp.nft`、`/usr/local/sbin/xboard-jp-firewall` 和 `xboard-jp-firewall.service` 只管理独立 `inet xboard_jp` 表，不清空全局规则。
- 后端 TCP 31443 仅允许回环或 `wg-vpn-stage1` 上源 10.79.0.1；其他 IPv4/IPv6 来源及 UDP 31443 拒绝。
- 隧道 UDP 51872 仅允许源 143.203.200.5。两端精确 /32 AllowedIPs 保留默认路由。
- `/etc/wireguard/wg-vpn-stage1.conf` 和 `.key` 仅 root 可读，私钥在日本机生成。保留原 SSH 3333 和原认证方式。

## 入口与监控

入口现有 `/etc/nginx/snippets/hk-xboard-routes.conf` 追加一条独立 WebSocket 路径，只转发至 `10.79.0.18:31443`。客户端仍必须验证 `hk.taige.us` 的证书，不设置 insecure。日本路径未复制到旧香港备用入口，因此若将域名回切旧入口，需先同步日本 peer 和路由或临时隐藏本节点。

入口 `/etc/vpn-stage1.nft` 的隧道来源集合追加日本 IP，原其他规则保持一致。修改时先 `nft -c -f`，然后直接运行现有原子加载脚本；避免 restart 防火墙服务触发依赖服务停止。Nginx 修改先 `nginx -t` 后 reload。

入口 `/etc/xboard-ingress-monitor.json` 的 peers 追加 `10.79.0.18`，资源采集器重启后应报告 14 peers。面板 probe #1 的 server_ids 和 expected_exits、ingress #1 的 server_tunnels 同步增加日本节点；NAS 自动重新取得配置，无需变更探针凭据。完整线路探测范围为 18 条，入口隧道为 14 条，4 条 CF 备用仍不绑定此入口。

## 检查与局部回退

日本机器可检查 `systemctl status xboard-node`、`systemctl show xboard-node -p MemoryCurrent -p NRestarts`、`wg show wg-vpn-stage1 latest-handshakes`、`nft list table inet xboard_jp`。节点心跳不能替代真实 HTTPS 出口、UDP DNS 和独享身份拒绝检查。

面板一致性数据库备份、旧配置快照和清单位于容器 `/www/storage/app/backups/friendhosting-jp-20261021/`；实际代理验收脚本位于面板主机 `/root/Xboard/backups/friendhosting-jp-20261021/`。入口原配置位于 `/root/xboard-jp-20261021/`，包含敏感信息，仅供管理员访问。

若需撤回，先隐藏公开 #354、移除 probe #1 的新检测项与 expected_exits，以及 ingress #1 / 入口采集器的新映射；再移除日本专用 Nginx location、WireGuard peer 和精确路由，并检查、重载对应运行配置。停用日本后端 #353 和机器 #18 后停止日本节点服务。仅修改本次新增对象；备份用于逐项比对，不用整库覆盖运行中的订单、账号或用量。已有配置后续如被修改，应按条目撤销，不能直接覆盖完整旧文件。

三名普通用户 HTTPS / 日本出口及 UDP DNS、独享与无效 UUID 拒绝、旧线路抽查已通过。未执行整机重启、长时间压测或大陆各运营商测速，也未修改面板应用镜像。
