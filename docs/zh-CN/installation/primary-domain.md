# taige.us 主域名与旧域名兼容

目标主站为 `https://taige.us`，`https://board.taige.us` 保持直接可用，共用原有应用和数据库。旧域名的订阅、下载和支付通知不跳转，避免客户端或支付平台无法处理重定向。

## 配置流程

Cloudflare 中先将 `taige.us` 的 A 记录指向 `107.173.191.23` 并开启代理。保留旧 `board` 记录和“完全（严格）”加密模式。HTTP 的 `/.well-known/acme-challenge/` 路径必须可公开访问，不能被强制跳转规则、访问认证或 WAF 挑战拦截。

在 `master` 上手动运行 GitHub Actions 的 **Configure Primary Domain**。该流程复用现有服务器密钥，通过固定 SSH 主机公钥校验服务器身份，并执行 `.docker/production/configure-primary-domain.sh`：

1. 备份数据库、环境文件和 Nginx 配置到 `/root/Xboard/backups/primary-domain-时间/`，准备独立的主域名 HTTP 验证入口。
2. 从 Actions 运行器检查验证文件，然后使用 Certbot webroot 为 `taige.us` 申请 Let's Encrypt 证书。
3. 配置主域名 HTTPS，复用现有代理和下载目录；检查 Nginx 语法、证书信任及两个域名的公开访问。
4. 验证成功后，将 `app_url`、`subscribe_url`、`APP_URL` 更新为 `https://taige.us`，替换知识库中的本站下载链接，并设置 Stripe 通道的通知域名。原有支付宝通知域名保持可用。
5. 清理 Laravel 配置缓存并平滑重载 Octane，再从两个域名核对公开配置接口的主站地址。

Stripe Dashboard 的既有 Webhook 端点 URL 需另行更新为新域名，路径和签名密钥保持不变；切换域名不会自动启用尚未完成密钥配置的 Stripe 通道。

## 自动续期和排查

证书位于 `/etc/letsencrypt/live/taige.us/`。`certbot.timer` 定期检查续期，成功后 `/etc/letsencrypt/renewal-hooks/deploy/xboard-nginx` 检查配置并重载 Nginx。ACME 账户不配置联系邮箱，应自行监控工作流、续期计时器与证书有效期。

若申请证书失败，流程会停止在更新应用主地址之前，旧域名继续可用。不要通过降低 Cloudflare 加密模式来规避证书错误。排查 HTTP 验证入口、DNS、`/var/log/letsencrypt/letsencrypt.log` 和 `journalctl -u certbot.service`。

回滚只恢复本次修改的站点设置、文章链接和 Nginx 配置，不要直接覆盖整个数据库，以免丢失切换后的订单或用户数据。旧域名配置未被流程修改。
