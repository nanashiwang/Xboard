# Agent Note: 家宽代理正式销售与客户端连接

Status: implemented

## Problem

用户明确要求完成购买、端点分配、到期停用及客户端连接后部署。现有二十个双协议端口未绑定用户，独立预览没有业务接口；原 VPN 套餐权益不能被代理购买覆盖。

## Decision

复用订单、余额、支付回调和客户端登录，代理订单显式区分 product_type，隐藏专用商品计划仅供代理服务使用。每月人民币 39 元，不折抵 VPN 权益。下单在数据库事务中预留一个端点；支付幂等延长日历月期限并生成独立认证；取消退回已扣余额并释放预留。所有代理库存写入以商品行作为共同数据库锁，禁止超卖。VPN 折抵计算排除代理订单。

端点凭据加密保存，用户 API 只能读取本人代理。节点使用各自令牌拉取授权快照，按固定端口映射运行独立认证进程；期限与短租约共同约束，控制服务失联后有限时间内停止，过期连接也必须被终止。既有 GOST 100 Mbps 限速与私网隔离保留。过期端点保留归属供续费，首版不自动复售，避免旧凭据与新用户重叠。

官网「我的代理」和原生客户端共用实际用户数据；新用户显示空状态和购买入口。用户可以选择 SOCKS5/HTTP，端口与认证保持相同。客户端复用内核与系统代理恢复机制，代理权益独立于 VPN 流量资格；一次仅运行一种连接。无真实统计则不显示虚构用量、ISP 或可用率。

## History audit

- [原设计](../../implemented/feature/2026-11-18-residential-proxy-workspace.md)部分重叠，保留视觉及产品约束，正式数据接入由本篇负责。
- [端点部署](../../implemented/architecture/2026-11-18-dual-protocol-proxy-endpoints.md)部分重叠，复用转发、限速及私网防护，认证进程由授权代理管理。
- [客户端恢复](../../implemented/architecture/2026-11-03-client-hub-recovery.md)复用固定源、签名升级和受控请求。

## Alternatives considered

仅发布预览入口可快速上线，但用户明确要求正式全流程，故不采用。复用 VPN 的 user.plan_id 最省代码，但购买代理会覆盖原套餐并错误折抵金额，必须保持独立资产与订单类型。

Web 服务直接持有 root SSH 凭据可以立即变更配置，但扩大权限且难保证失联撤权；使用节点专属拉取令牌和短租约，保留本地截止时间。

## Validation

验证库存并发、支付回调幂等、取消/回调竞争、续费期限、用户隔离、凭据更新、到期关闭及控制故障关闭；真实两台服务器分别验收 SOCKS5/HTTP、错误认证和到期停用。官网与客户端完成购买/读取/连接流程，原 VPN 行为回归。分别完成官网镜像部署、四平台 Release 与分发验收。

## Consequences

SQLite 忽略 SELECT FOR UPDATE。重复并发验证曾触发读事务升级写锁失败，现以商品 allocation_version 原子递增作为事务首条 SQL，先取得写锁再读取库存；MySQL 同样使用该商品行序列化代理变更。拒绝用增加重试次数掩盖读后升级锁竞争。

短租约以可用性换取失联后及时撤权；明确记录超时窗口。代理带宽为每端点上限，不承诺物理线路始终达到 100 Mbps。真实第三方支付只能在用户授权付款范围内验证；不把创建支付会话作为实际到账证明。

Local validation: PHP 172 tests / 1470 assertions passed, one external-core check skipped; 78 frontend and 17 script tests passed; 67 Rust tests passed and one manual keychain test ignored; proxy agent validation passed. Production deployment and cross-platform release remain pending until individually verified.

生产部署暴露了原发布检查的缺口：容器 Running/Healthy 不代表应用已能响应。2026-11-18 镜像部署后的磁盘耗尽使 Octane 无法启动、外网返回 502；库存保持关闭。恢复只清理本仓库标签的悬空镜像，不碰数据卷、数据库或已引用镜像；恢复后须重验 HTTP 与业务授权，不能沿用容器健康状态作为成功证据。

管理脚本 1.0.1 在拉取前要求 Docker 和业务分区各至少 4 GiB 空间，拉取后保留至少 512 MiB，再允许迁移；启动后必须在 90 秒内通过实际账户健康 HTTP 接口，拒绝仅凭容器 Running 判成功。真实脚本使用假 Docker 的 20 项操作测试通过，覆盖低磁盘在拉取前停止，以及容器运行但 HTTP 失败不得报成功。
