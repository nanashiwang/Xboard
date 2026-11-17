# Agent Note: 两台美国出口独立双协议代理端点

Status: implemented

## Problem

用户在页面设计任务中追加真实部署要求，并提供两台服务器登录方式，确认每台十组、共二十组独立端点。216.36.108.173 为当前美国10固定池出口，192.204.56.29 为历史七云出口；现场两台均为 Ubuntu 24.04 amd64，实际 IPv4 出口与地址相同，已有 sing-box、Nginx、Xboard 等服务不能覆盖。

## Decision

新增独立 GOST 3.3.3 服务，验证官方发行归档 SHA256 后安装专用路径；每台仅新增 TCP 20001–20010。每端点使用 GOST TCP listener 转发到仅监听回环的独立 sing-box mixed inbound，同端口处理 HTTP CONNECT/HTTP 正向代理和 SOCKS5；唯一随机账号密码、独立服务级双向限速，每方向 12,500,000 B/s（100 Mbps），不设累计流量额度。验证 SOCKS4 不得绕过密码认证。

服务使用非 root 账号、只读系统目录、独立配置与受限凭据目录；阻止访问本机/私网/链路本地管理地址。保留现有服务、监听、路由、WireGuard 和 Xboard 套餐/授权。私密交付清单不进入 git、Actions 日志或公开预览。页面使用示例地址，协议切换不会修改生产服务。

## History audit

- [固定出口池](../../implemented/feature/2026-10-19-owned-fixed-exit-pool.md)部分重叠，216 出口复用机器，但原五名额分配和流量套餐未改。
- [探针恢复](../../implemented/bug-fix/2026-11-05-dedicated-probe-panel-origin.md)部分重叠，保持 xboard-node 和探针链路；新服务需独立验收。
- [代理页面预览](../feature/2026-11-18-residential-proxy-workspace.md)关联但独立交付。本次服务器开端口不代表订单开通、自动续费或到期撤权已接入。

## Alternatives considered

复用当前 sing-box mixed inbound 可用更少二进制，但现有实例承载其他代理业务，且其原生配置没有本任务要求的独立端点合计带宽限制。独立 GOST listener 使用服务级 limiter，回环认证使用另一 sing-box 实例，避免每连接限速被并发绕过，也不改变原服务。

分别开十个 SOCKS5 和十个 HTTP 端口能直接配置单协议，但用户选择每台十组、同端口两协议。公共端口只做固定 TCP 转发，认证由回环 mixed inbound 处理，协议选择不需要额外公网端口和凭据。

直接使用 GOST auto handler 的配置更简洁，但固定依赖 x v0.28.1 的源码存在独立 TLS sniffing 转发分支，没有同等认证调用；本地公网 TLS 探测超时不能证明该分支安全。因此不采用 auto，以固定目的 TCP 转发加 mixed 认证隔离；实际拒绝验收覆盖原始 TLS。参考 [固定版本源码](https://github.com/go-gost/x/blob/v0.28.1/handler/auto/handler.go)、[官方限速说明](https://github.com/go-gost/docs/blob/master/en/docs/concepts/limiter.md)。

## Validation

两台20端点在服务器本机及独立入口143.203.200.5分别完成每端点13项检查，包含两协议HTTPS出口、普通HTTP、匿名/错密/跨端口、SOCKS4、私网及原始TLS拒绝；独立入口20/20、260检查通过。Mac公网直连复测216为7/10、192为3/10，存在传输与握手超时，不能宣称国内长期稳定。Mac与Linux固定GOST程序各用四连接实测限速隔离，低额度模型约7秒完成；配置核对每端点12,500,000B/s，并非证明物理线路持续跑满100Mbps。两台新服务重启后凭据摘要保持、原服务PID/配置摘要与部署前基线相同；原Xboard业务回归单列进展。

## Deployment corrections

首次启动因umask077使新目录缺少服务账号遍历权限，已显式设置配置目录0750与程序目录0755；其后补充认证服务所需AF_NETLINK，原服务始终未重启。安装器增加服务账号读取/执行检查，并同时核验限速服务与认证服务active及回环监听，避免只把公网TCP监听视作成功。验收脚本使用curl --fail正确识别HTTP拒绝状态；早期403/502被误判的检测结果已纠正并全量复验。

## Consequences

独立端点目前由运维交付；39元支付、用户订单、自动到期、客户密码重置与实时统计尚未接入。100 Mbps 是每端点速度上限，不是物理线路保底；同一公网 IP 的端点共享出口。住宅属性沿用用户命名，没有独立 ISP 认证。未经实测的 UDP 不承诺支持。
