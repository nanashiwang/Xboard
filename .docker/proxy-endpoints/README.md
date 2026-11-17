# 独立家宽代理端点

用户确认在 `216.36.108.173`、`192.204.56.29` 每台建立10组，共20组独立认证端点。两台现场公网出口均与上述IP一致。216为现有美国10固定出口（机器12、后端335、固定出口14）；192为历史七云节点。家宽名称沿用用户提供的分类，没有额外ISP认证。

## 运行结构

每台公网 **TCP 20001–20010** → 独立 GOST TCP listener（每端点合计限速）→ 回环 **127.0.0.1:21001–21010** 的独立 sing-box mixed inbound（每端点独立用户名密码）。同一公网端口同时支持 SOCKS5 和 HTTP，包括 HTTP CONNECT。UDP 不开放。

服务为 `xboard-proxy-endpoints.service` 与 `xboard-proxy-auth.service`。原有 `sing-box.service`、`xboard-node.service`、Nginx、WireGuard和套餐权益保持原样；共用已安装sing-box二进制，配置/进程单独运行。新服务有独立非root账号与systemd沙箱，配置目录0750、认证配置0640。sing-box需要AF_NETLINK订阅路由信息，未授予网络管理能力。

每端点 limiter 为 `$ 12500000B 12500000B`，即上传、下载各最高100 Mbps，多连接与两协议共同占用该端点限额。没有累计流量配额。20组各有不同凭据；同IP的10个端点不构成10个不同公网IP。这里是运维预配置，**尚未与39元订单、有效期、自动停用或用户密码重置接口连接**。

## 安装与版本

GOST固定3.3.3，官方[归档](https://github.com/go-gost/gost/releases/tag/v3.3.3)中`gost_3.3.3_linux_amd64.tar.gz` SHA256：

```
f4c1255dc892a7014c0ad6e5f1c3573108f7bea4403f04f21873406ab58aa666
```

解压后的gost SHA256固定为 `a60f87707d679d154fad93d05313284baf3dea71fdb9ec18afecaac35db946dd`，安装器再次验证。没有使用GOST的auto handler；固定依赖源码存在额外TLS转发路径，选择固定TCP目的地转发，由mixed inbound执行认证。见[设计取舍](../../.agents/notes/implemented/architecture/2026-11-18-dual-protocol-proxy-endpoints.md)。

首次安装仅允许明确的两台机器，检查本机IP和公网/回环端口空闲，生成随机凭据并保存现有服务PID、配置摘要、防火墙快照。重复安装拒绝覆盖配置及凭据。

```sh
python3 manage.py install --host 216.36.108.173 --binary /已校验/gost
python3 manage.py status
```

`/etc/xboard-proxy-endpoints/`为运行配置；`/usr/local/lib/xboard-proxy-endpoints/gost`为固定二进制。私密清单、基线和验收结果位于服务器 `/root/xboard-proxy-endpoints/`（0700目录）；`endpoints.json`为0600，不要cat到公共日志或提交git。

仅对新服务UID生效的`inet xboard_proxy_guard`输出规则防止访问回环、私网、链路本地及两台本机管理地址，并允许必需的本机DNS。GOST仅允许转发到指定回环认证端口。192机器沿用现有UFW，新增绑定本机IP的20001:20010/tcp规则；216原输入策略accept，无需添加宽泛放行规则。私网拒绝同时有sing-box路由与UID输出规则。

## 验证与回退

```sh
python3 verify.py /root/xboard-proxy-endpoints/endpoints.json
GOST_TEST_BINARY=/已校验/gost python3 -m unittest discover -s tests/ProxyEndpoints -v
```

验证脚本不打印密码；每端点检查两协议HTTPS实际出口、普通HTTP、匿名/错密/跨端点认证拒绝、SOCKS4拒绝、私网目标拒绝及原始TLS拒绝。HTTP错误状态应按失败处理，不能把正常403/502拒绝响应误判为目标访问成功。限速测试用低额度和四条实际并发传输，区分“按连接限速”“每端点合计限速”“所有端点共用限速”。Mac和Linux固定程序均通过。

仅回退本次新服务与其防火墙规则，保留私密清单供核查，不恢复整库或覆盖原网络配置：

```sh
python3 manage.py stop
```

`stop`停用两个新服务并撤销本次UFW规则；独立nft表由服务退出动作移除。重新启用前核对凭据、配置、UFW放行和实际连接，不能只根据端口监听判断可用。已有安装调整需定向备份与验证，安装器不会直接覆盖。

2026-11-18的实际结果、早期启动修复和公网网络波动见[进展记录](../../progress-log.md#2026-11-18家宽代理预览与双协议端点)。前端只交付[设计预览](../../docs/previews/proxy-workspace/README.md)，未发布正式网页或客户端版本。
