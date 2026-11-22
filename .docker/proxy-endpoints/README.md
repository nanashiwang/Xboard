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
## 正式销售授权管理

正式实现见 `app/Services/ResidentialProxyService.php` 和 `proxy:inventory`。`init --address=IP --output=/受限路径` 只创建停用库存，将节点专属令牌写入 0600 文件；令牌不得提交、记录或放入 URL。`bootstrap` 工作流安装每端口独立认证进程，保留原 GOST 转发、限速及私网防护。`acceptance` 创建一次性余额测试账号，验证二十端点后清理并保持停售；通过后才执行 `enable`。已售端点存在时验收脚本拒绝运行，不覆盖客户归属。

节点每 20 秒拉取授权，最长 120 秒租约；到期或租约耗尽停止认证进程及现有连接。同步请求最多 10 秒，异常请求可能使停止比截止时间晚约 10 秒；代理进程退出时 systemd 绑定停止端口服务。过期端点不自动释放给新客户，保留原用户续费。`disable` 会停止该机代理授权，不能当作只暂停新购的操作。

每个端口的认证配置位于 `/etc/xboard-proxy-endpoints/port-PORT.json`，主令牌配置为 `agent.json`，备份目录为 `/root/xboard-proxy-agent-backup-*`。安装脚本不修改原 Xboard 节点、Nginx 或 WireGuard 配置。回退旧认证服务可能恢复历史手工凭据，回退前必须停用公网端点，核对有效订单后再恢复；不得直接恢复旧认证文件继续销售。

### 桌面家宽第一阶段

桌面端连接 `wss://node.lumavia.fyi/residential/v1/{a或b}/{已购端口}`。入口逐端口转发到家宽机器 23001–23010 的 WSS 服务，验证各机公钥证书，再由 GOST 接回原 20001–20010 的限速、认证监听。客户端始终校验入口 TLS，两个域名身份分别由各自的信任根验证。

1. 两台已有 GOST 3.3.3 的 PX 机器分别以 root 执行 `python3 stage1.py exit a` 和 `python3 stage1.py exit b`。UFW 规则仅允许第一阶段源地址，服务也执行同一来源白名单。
2. 通过已验证主机密钥的 SSH 将每台的 `/etc/xboard-px-transport/server.crt` 拷至入口管理目录，分别命名为 `a.crt` 和 `b.crt`。私钥留在对应 PX 上。
3. 入口执行 `python3 stage1.py entry /path/to/public-certs`。安装器检查证书身份、固定 vhost 和 nginx 配置，再平滑 reload。原路由继续使用原 include。
4. 在已有 Production Deploy 流程运行 `verify-residential-stage1`。它用临时账户和一席空闲端口检查真实租约、出口和两种协议，随后清理测试记录。生产验证需要至少一席可售库存。
5. 回退时从该 vhost 移除 `include /etc/nginx/snippets/xboard-px-stage1.conf;`，执行 `nginx -t && systemctl reload nginx`，再在两台 PX 上停用 `xboard-px-transport` 和对应的 23001:23010 防火墙规则。续证时先在入口预置信任新旧证书的组合，再逐台更换服务端证书并重启此独立服务，验证后移除旧证书。首次生成证书有效期 1095 天。

## 后台接入新出口（桌面 0.1.24）

1. 管理后台进入「家宽订阅与容量」，点击「添加家宽出口」，填写名称、地区和已核实线路属性的固定公网 IPv4。
2. 将生成的命令复制到新机终端执行。使用带 systemd 的 Debian / Ubuntu x86_64，公网地址须直接配置在本机。新机需要 Python 3、curl、sudo，并能访问面板和固定版本软件下载源。已领取身份的同一台机器可重跑原命令恢复安装。领取前可在出口行重新签发，旧命令随即失效。
3. 云防火墙允许 TCP 20001–20010 对客户开放，23001–23010 仅需允许第一阶段来源。现有本机 UFW 启用时安装器设置相应规则。每台使用十个端口，均有独立授权及上下行各 100 Mbps 限速。
4. 机器上报后点击「验收并上架」。第一阶段使用十组临时凭据检查 HTTP/SOCKS5 的直连、桌面固定路径、实际出口及错误认证。十个端口均确认测试授权已撤回后进入可售库存。失败或超时可在修复后重试。
5. 桌面用户连接新登记出口需要 0.1.24 或更新版本。已部署的两个历史出口继续使用原有固定路径。

第一阶段首次接入由运维在 Proxy Sales Production 选择 `pair-ingress`，提交已部署镜像版本和一次性 X25519 公钥。工作流输出 libsodium sealed box 密文（十六进制）；使用对应私钥解密得到安装命令，仅在现有第一阶段执行。令牌只允许同步已登记路由及报告当前验收结果，配置在第一阶段私有目录。之后每台新增出口只需在新 VPS 运行一次命令。自动化也可通过同一工作流的 `register-host`、`host-command`、`accept-host` 和 `host-status` 定向操作。
