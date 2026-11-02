# 注册防滥用运维

决定见[注册防护](../../.agents/notes/implemented/feature/2026-11-03-registration-abuse-defense.md)。只保护注册、发邮箱验证码、找回密码；不对订阅/支付/桌面授权叠加挑战。

## 当前额度

- IP 发码：5次/10分钟、20次/小时、50次/天；邮箱：1次/分钟、5次/小时、10次/天。
- IP 注册请求：10次/分钟、60次/小时、100次/天；验证通过后原子预占3个注册名额/小时、10个/天。
- 每邮箱验证码：5次校验/5分钟，重发不清空尝试数；有效验证码在写账号/密码之前一次性消费。
- 暂限 `fldubai.com` 新注册和新用户发码；已有用户登录/恢复继续可用。`registration_allowed_emails` 为精确邮箱例外，默认空。不自动封禁/删除账号。

这些是初始参数，需结合共享出口正常用户反馈调整。限流窗口独立、拒绝不延长窗口；下游创建失败保留预占名额，避免错误释放造成并发超额。

## 启用、检查、回退

先修正代理和 Turnstile 三域允许列表，部署已通过检查的镜像，再运行 `php artisan security:registration apply`。命令要求共享 Redis、已有验证码密钥，保存权限0600的配置快照，只改固定策略项，保留邮箱例外与其他设置。`inspect` 只显示非敏感配置和例外数量；`rollback` 要求当前策略与快照完全匹配，配置已被其他操作修改时拒绝覆盖。Production Deploy 中对应 registration-inspect/apply/rollback 操作均校验完整镜像SHA，变更后 reload Octane。

快照默认 `storage/logs/security-backups/registration-20261103.json`，生产已核实 storage/logs 持久挂载；使用其独立0700子目录，避免容器重建丢失快照；不要上传快照。上线7天后每天09:00检查到期复核标记，在注册专用日志记录警告；到期不会自动放开受限域。管理员配置API已有字段校验，现成管理页面不新增隐藏绕过入口。

审计日志 `storage/logs/registration-YYYY-MM-DD.log` 仅保留7天：服务端请求ID、结果、原因、邮箱域、带应用密钥的邮箱/IP摘要、成功账号ID，不存密码/验证码/原始IP/完整邮箱。单域1小时8个成功注册时每小时最多记录一次警告；常见邮箱不会因此被自动封禁。结合发码/注册结果、订单和流量继续人工复核，告警不自动发信给第三方。

## 代理和主题维护

`registration-proxy.py board|relay inspect|prepare|apply|rollback` 仅接受已检查的生产配置SHA，复用原备份/原子替换/nginx -t/失败恢复工具。board源站及taige跳板仅信任CF官方22个IPv4/IPv6网段；公开请求身份头用可信 `$remote_addr` 覆盖，Go直连配置保持原先规则。官方地址2026-11-03核对：[IPv4](https://www.cloudflare.com/ips-v4)、[IPv6](https://www.cloudflare.com/ips-v6)。旧安装模板保留为历史基线；已加固配置不能用旧模板覆盖。

源站运行 `registration-proxy-verify.py`，检查三个公网域名、直连伪造头和跳板伪造头，并将实际收到的头送入已安装Laravel TrustProxies核验。随机临时诊断路径限定来源、关闭日志，finally恢复配置；失败应核对清理标志，不能以200替代身份断言。

主题只提供压缩产物，维护源放在 `theme/Xboard/patches/turnstile-component.js`，运行 `python3 scripts/security/patch-turnstile.py` 幂等重建；未知上游锚点拒绝修改。表单每次发码/注册取独立token，失败显示提示等待显式重试，不再自动 reset 循环。服务端核对 hostname/action、单次token、3秒连接/8秒总超时；不匹配或服务异常拒绝。

检查：`node --test tests/Frontend/turnstile.test.cjs`，PHP Security及BrowserLogin回归；CI使用真实Redis和8个独立进程验证并发名额/一次性码。测试中的模拟挑战不能代表生产真人完整注册验收。
