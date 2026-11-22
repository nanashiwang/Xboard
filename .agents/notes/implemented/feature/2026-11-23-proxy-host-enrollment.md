# Agent Note: 管理员登记家宽出口并验收上架

Status: implemented

## Problem

普通机器可复制安装命令，家宽销售库存、第一阶段和桌面端却分别枚举两个地址。扩容需要改程序，普通节点在线也不能证明固定代理可用。

## Decision

管理员登记固定 IPv4 和地区后签发限时安装凭据，机器自行领取本机租约身份。第一阶段受信任的同步服务只接受面板登记的公网地址和公钥证书，按出口生成固定路径。验收在停售库存上使用短时测试授权，检查两协议、真实公网出口和错误认证，清除测试授权后才计入可售库存。

## Alternatives considered

复用普通机器令牌不能区分普通节点权限与代理租约。Web 保存 SSH 密码增加跨机器权限。手工添加第三个地址可快速扩一台，但后续每台仍要重新发布客户端并改入口。

## Testing

回归覆盖安装码重签和重放、验收失败或超时、旧修订不能启用库存、十个端口全部撤权才上架。生产链路独立记录在[进展](../../../../progress-log.md#proxy-enroll-20261123)。

## Consequences

第一阶段需一次性安装同步服务；工作流离线时新库存保持停售。登记与验收只能验证指定出口及功能，线路属性由管理员核实。

## Related decisions

[销售与租约](../../implemented/feature/2026-11-18-residential-proxy-sales.md)、[固定第一阶段](../../implemented/architecture/2026-11-22-residential-stage1.md)和[容量看板](../../implemented/feature/2026-10-30-residential-capacity-dashboard.md)分别保留原有职责。
