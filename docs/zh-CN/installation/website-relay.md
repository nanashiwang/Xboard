# taige.us 网站 Flawless 入口

本文件只管理网站入口。VPN 节点的 lumavia.fyi、套餐、订阅 URL、支付回调域名和应用镜像不随本次入口调整变化。决定见[方案笔记](../../../.agents/notes/implemented/architecture/2026-10-22-website-flawless-relay.md)。

## 当前路径

当前为 `taige.us → DNS-only A 155.103.118.155 → HTTPS 107.173.191.23`；`board.taige.us` 保留原 CF 代理路径。2026-10-22 已完成 DNS 切换、两台权威及两个公共解析器核对；A 的 TTL 为 300 秒，AAAA 为空。实际连接目的 IP、公开页面及压缩已验收；仍有一次追加超时，不宣称已消除全部卡顿，详情见[执行记录](../../../progress-log.md)。

跳板配置源为 [website-relay.conf](../../../.docker/production/website-relay.conf)，安装到 `/etc/nginx/sites-enabled/taige.us`。上游固定 IP、SNI 与 Host，严格验证源站证书；开启 gzip，保留请求方法、正文、Range 与 Upgrade，不做公共代理缓存。访问日志不包含路径、查询参数、Cookie 或 Authorization，避免记录订阅凭据。

## 证书与真实 IP

跳板首次通过 DNS 验证取得独立证书，到期 2027-01-20。正式切换后已使用 `certbot reconfigure --cert-name taige.us --authenticator webroot --webroot-path /var/www/xboard-relay-acme --preferred-challenges http` 成功模拟并保存自动续期配置；nginx 检查/reload hook 已执行，timer active/enabled。Certbot 仍保留旧 manual_auth_hook 字段，但当前 authenticator 为 webroot，实际模拟使用 HTTP 验证。

80 端口的 ACME challenge 优先读取跳板 `/var/www/xboard-relay-acme`，缺失时转发到源站 `/var/www/xboard-acme`，以支持两端独立续期。其他 HTTP 请求保持路径和参数跳转 HTTPS。

跳板覆盖传入的客户端身份头；源站仅在 taige.us vhost 精确信任该跳板及 CF 官方网段，并清洗发送给应用的 X-Forwarded-For。不得只把 relay IP 加入全局信任或信任公网任意头。源站运维通过[手动工作流](../../../.github/workflows/website-relay-origin.yml)和[限定脚本](../../../.docker/production/website-relay-origin.py)执行，沿用现有 SSH Secret 和固定主机公钥，不导出密码。

## 切流与回退

切流前固定域名与新 IP，严格 TLS 检查首页、公开配置、主 JS 压缩及完整内容、下载页、Range，并验证身份头伪造被覆盖。对比同一大陆网络原 CF 路径；不将单次成功写成全运营商提速。现有 `/ws` 在直接源站和 relay 都返回 502，未将其标为 WebSocket 业务验收成功。

只把 CF 控制台原 `taige.us A 107.173.191.23 / 已代理 / TTL自动` 改成 `155.103.118.155 / 仅DNS`。原记录没有独立 AAAA，橙云生成的 IPv6 地址应随代理关闭撤下；需从权威 DNS 与公共解析器检查 A/AAAA，再验证实际连接 IP。旧缓存短期仍可能指向 CF。

如出现入口退化，先将主域 A 恢复 `107.173.191.23` 并开启代理，再等待 DNS 缓存收敛。源站保留对 CF 的精确信任，正常回退不必立即撤销真实 IP 修正。需要撤销源站变更时，只使用本次备份和候选 SHA 保护，不能覆盖其他后续修改。跳板备份位于 `/root/xboard-website-relay-20261022/`；撤销时只移除本次 taige.us vhost，通过 nginx -t 后 reload，保留现有其他站点、证书和监控。

灰云路径不再经 CF 边缘缓存和防护，依赖该共享跳板及跨境线路；源站与跳板均使用严格 HTTPS。不得把 board 兼容入口描述成自动故障切换。
