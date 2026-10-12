# 香港中转入口运维

香港入口使用 `hk.taige.us`，Cloudflare A 记录指向 `103.24.217.171`，代理状态为「仅 DNS」。旧入口 `edge.taige.us` 保持橙云，原线路仍可选择。

```text
客户端 → hk.taige.us:443 → 香港 Nginx → 本机 xboard-node → 各地区出口
客户端 → edge.taige.us:443 → Cloudflare → 七云入口 → 各地区出口
```

香港机器只承担第一跳，流量会再转发到用户选择的地区出口，不作为独立的香港出口展示。订阅主线路直接使用最终出口名称，例如「美国凤凰城|高速下载」；经过旧 Cloudflare 入口的线路在名称末尾标记「｜CF备用」。已有香港地区线路指其各自的上游香港出口，与这台中转机器不同。

批量整理节点名称时必须保留入口区别。香港主线路与 CF 备用线路若同名，Clash/Mihomo 会报 `is the duplicate name` 并拒绝整份订阅；HTTP 200 或 YAML 可解析不能代替内核配置校验。

订阅生成器在协议兼容性过滤和插件处理后，对仍然同名的节点附加稳定节点编号，并使用相同名称生成策略组引用。此处理保留所有线路，不修改数据库名称。运维仍应使用清晰的入口后缀；发布前用 `mihomo -t -f <订阅配置文件>` 校验实际生成的配置，验证后删除包含个人凭据的临时文件。

香港机器的 500 Mbps 是整台服务器的端口带宽；每月 1 TB 流量由运营方补充，不代表每个用户拥有 500 Mbps。大陆实际速度应在用户所在运营商网络测试。

## 服务与配置

- 香港入口：Ubuntu，原生 systemd 服务 `xboard-node`、`nginx`、`nftables`；面板机器 ID 为 `3`，名称为「香港中转入口-01」。
- `xboard-node` 使用独立机器 Token，同步面板用户、流量和出口配置；不能与七云机器共用身份。
- 节点程序沿用七云现有兼容版本，SHA-256：`480c224aff5315263646863c8a76cd18d21f58e0facbb2e202b883b3bd2254ce`。
- 节点配置：`/etc/xboard-node/config.yml`，权限 `root:xboard-node 0640`。
- 服务配置：`/etc/systemd/system/xboard-node.service`；程序以非 root 用户运行。
- Nginx 站点：`/etc/nginx/sites-available/hk.taige.us.conf`。
- WebSocket 转发：`/etc/nginx/snippets/hk-xboard-routes.conf`；每条路径对应一个本机后端端口。
- `/etc/nftables.conf` 只阻止非回环接口访问 `31000–31999/tcp`，避免明文后端被公网直接访问，不覆盖其他 nftables 表。
- TLS：`/etc/letsencrypt/live/hk.taige.us/`，`certbot.timer` 自动续期，部署钩子先校验再重载 Nginx。
- 面板：`/root/Xboard`、Compose 服务 `xboard`。数据库备份位于 `/root/Xboard/backups/hk-ingress-20261011-184457/`，只供服务器管理员访问，禁止上传仓库。

公开节点标签为 `hk-direct-public`，隐藏后端标签为 `hk-direct-backend`。公开记录通过 `parent_id` 关联本机后端；实际转发由后端的 `custom_outbounds` 和 `custom_routes` 完成。已有套餐、用户 UUID 和订阅地址继续使用。

## 验收

在香港服务器检查：

```bash
systemctl is-active xboard-node nginx nftables
systemctl is-enabled xboard-node nginx nftables certbot.timer
nginx -t
nft list table inet xboard_ingress
curl --noproxy '*' --resolve hk.taige.us:443:127.0.0.1 https://hk.taige.us/healthz
certbot renew --dry-run --no-random-sleep-on-renew
```

在独立外部机器检查 DNS、TLS 和健康地址，再使用有效的临时测试账号逐条发起 VLESS over WebSocket over TLS 请求，核对实际 HTTPS 出口响应。`/healthz` 返回成功只表示 Nginx 就绪，不能代替代理请求。根路径返回 404 是预期配置。

发布前检查 Clash、sing-box 等订阅实际包含直连域名、正确 SNI、443 端口和对应路径；只展示测试通过的线路。验证完成后撤销临时账号，并确认节点同步移除该账号。

macOS 本机若启用 Shadowrocket TUN，强制解析或 `--noproxy` 不一定绕过 TUN。不要把这种环境下的结果当作大陆直连速度证据。

## 2026-10-12 部署验收

30 条香港入口候选线路中，28 条通过从独立服务器发起的完整 TLS → WebSocket → VLESS → 出口 HTTPS 请求，已公开展示。两条「香港原生 IP」线路从香港入口连接上游 6001 端口超时，但从原七云入口请求成功，因此其香港入口副本保持隐藏，原线路继续可用。

Clash Meta、sing-box、通用 Base64 订阅均返回 HTTP 200，包含 28 条经香港中转的主线路和 30 条 CF 备用线路。面板会额外生成流量/到期提示节点，验收计数应排除这类提示。临时测试账号的上传和下载用量均有入账，后端 31001 端口在外部连接测试中被阻止。

## 切换与回退

用户更新原订阅后，按目标出口地区选择没有「｜CF备用」后缀的主线路，即经过香港中转。需要旧入口时选择同名的 CF 备用线路。订阅列表排序不会强制切换用户当前选中的节点；名称更新后，客户端可能需要重新选择线路。

需要回退时，在面板隐藏标签为 `hk-direct-public` 的公开节点，让用户更新订阅并选择原线路。确认没有用户连接后才停止香港节点服务。不要删除或改灰 `edge.taige.us`，也不要为回退整库恢复备份，否则会覆盖部署后的订单和用量。

修改节点配置后应核对真实流量和用户同步。首次部署沿用面板的 REST 同步回退机制；现有面板 WebSocket 管理地址的端口可达性需要单独维护，不应把一次 WS 连接日志当作所有节点离线。

本次部署只新增入口，不包含「美国独享家宽 IP」套餐的五账号分配、售罄隐藏或失效迁移功能。
