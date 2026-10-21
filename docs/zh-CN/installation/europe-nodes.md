# FriendHosting 荷兰与罗马尼亚节点运维

两台节点复用[日本节点的接入约束](./japan-node.md)，只供轻量、标准、进阶、旗舰四个套餐使用。机器名称 `friendhosting-罗马` 保留原命名，订阅按实际出口国家 RO 标为「罗马尼亚」。方案见[共用决策](../../../.agents/notes/implemented/architecture/2026-10-21-friendhosting-japan-node.md)，实际验收见[进展记录](../../../progress-log.md#2026-10-21荷兰与罗马尼亚节点接入)。

## 拓扑与对象

客户端经 `hk.taige.us:443` 的严格 TLS / VLESS / WebSocket 到第一阶段入口 `143.203.200.5`，再经各自 WireGuard peer 到出口后端 TCP 31443。两层节点均只允许字符串权限组 `1/2/3/4`，倍率 1，`dedicated_exit_id=null`，不扩充固定出口池。

| 项目 | 荷兰 | 罗马尼亚 |
| --- | --- | --- |
| 机器 | #19 `friendhosting-荷兰` | #20 `friendhosting-罗马` |
| 出口 | `185.198.165.162`，NL | `94.131.17.12`，RO |
| 公开节点 | #356「荷兰｜friendhosting｜第一阶段入口」 | #358「罗马尼亚｜friendhosting｜第一阶段入口」 |
| 隐藏后端 | #355 | #357 |
| 隧道地址 | `10.79.0.19/32` | `10.79.0.20/32` |
| 独立防火墙表 | `inet xboard_nl` | `inet xboard_ro` |
| 配置/服务前缀 | `xboard-nl` | `xboard-ro` |
| 备份标识 | `friendhosting-nl-20261021` | `friendhosting-ro-20261021` |

公开记录 `show=true`、`enabled=false`、`machine_id=null`，分别以 `parent_id` 指向隐藏后端。隐藏记录 `show=false`、`enabled=true`，绑定对应机器。四档普通套餐最终节点数为 17/18/19/20；独享账号仍仅获原分配出口及香港备用，后端也不下发其身份。

## 机器服务与访问边界

两台为 Ubuntu 24.04.5 / x86_64 / 约 458 MB 内存。使用 `/usr/local/bin/xboard-node` 原生二进制，非 root 用户 `xboard-node`、工作目录 `/var/lib/xboard-node`、`xboard-node.service`。二进制 SHA256 为 `28662b4803bf5cbf3db9079b6fe24921f43b1ebb06e64ec187de6a85e548a4f0`；配置 `/etc/xboard-node/config.yml` 为 root:xboard-node 0640，Go 软内存目标 128 MiB，服务 MemoryMax 256 MiB。

- `wg-vpn-stage1`：UDP 51872、MTU 1380、入口 `10.79.0.1/32`，每端只配置精确 /32，不改默认路由。
- 对应 `/etc/xboard-nl.nft` 或 `/etc/xboard-ro.nft` 及 firewall service：TCP 31443 仅回环或 WireGuard 上源 `10.79.0.1` 可达；其余 TCP/UDP 31443 拒绝，UDP 51872 只允许入口 IP。inet 表覆盖 IPv4/IPv6。
- SSH 3333 及原认证方式保持。WireGuard 私钥在各机器生成，文件 root:600；不要把配置、令牌或用户 UUID 写入仓库或日志。

## 入口与监控

入口 `/etc/nginx/snippets/hk-xboard-routes.conf` 为两台各追加独立随机 WebSocket 路径，分别指向 `10.79.0.19:31443`、`10.79.0.20:31443`。修改前备份，先 `nginx -t` 再 reload。不要修改或复制实际路径到公开文档。

入口 `/etc/wireguard/wg-vpn-stage1.conf` 与运行态各追加两个 peer；`/etc/vpn-stage1.nft` 的 UDP 来源集合加入两出口 IP。先 `nft -c -f` 再使用 `/usr/local/sbin/vpn-stage1-firewall` 原子加载，避免 restart 防火墙服务触发业务依赖停止。

NAS probe #1 的 server_ids 增加 #356/#358，expected_exits 对应各自公网 IPv4；ingress #1 的 server_tunnels 分别映射到两台隧道 IP。入口 `/etc/xboard-ingress-monitor.json` peers 同步扩为 16 条，完整质量探针范围为 20 条。重启采集器后检查真实 `reported:true`，不把配置保存当作采样成功。4 条 CF 备用不绑定本入口。

## 验证与局部回退

检查实际普通账号 HTTPS 出口、UDP DNS、独享与无效身份拒绝、Clash Meta/Shadowrocket 订阅和已有日本/美国/香港/CF 线路。心跳、隧道 ping 或订阅中出现名称都不能替代业务请求；完整证据、间歇失败与持续采样见进展记录。服务 active/enabled 也不代表已做整机重启验收。

面板容器 `/www/storage/app/backups/<备份标识>/` 保存一致性数据库备份、旧对象快照及私有清单；面板主机 `/root/Xboard/backups/<备份标识>/` 保存验收脚本。入口备份分别位于 `/root/xboard-nl-20261021/`、`/root/xboard-ro-20261021/`，包含敏感配置，权限保持 0700/0600。

撤回时先隐藏对应公开节点，移除探针/预期出口和两处隧道映射；再撤销该节点专用 Nginx location、WireGuard peer、精确路由与防火墙来源项，并检查、重载。最后停用对应后端和机器、停止该机节点服务。只撤回对应新增条目，不能整库回滚或覆盖后来新增的另一台配置。

日本、荷兰、罗马尼亚的新路径均未复制到旧香港入口。若将域名切回旧入口，须先同步这三条 peer/路由并验收，或隐藏对应节点并撤下探针；其余回退约束见[第一阶段运维](./vpn-stage1.md)。
