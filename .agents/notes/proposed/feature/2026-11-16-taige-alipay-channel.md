# Agent Note: taige 账户独立支付宝通道

Status: proposed

## Problem

用户要求将 taige（acct_1UGbyu1DvmJXrFlV）的支付宝接入 Xboard。2026-11-16 浏览器核实目标 pmc_1UGbzR1DvmJXrFlVLsBXHPnq 中支付宝已启用、微信不符合资格；原 Raymi 微信/银行卡仍有用途。目标账户已有 Xboard 受限密钥及旧 Webhook，不能只替换 pmc 或混用另一账户的密钥。

## Proposal

复用 StripeCheckout 的按通道配置及 CNY 收款能力，新增独立支付宝通道，保留当前 Raymi 通道。沿用[人民币原价决定](../../implemented/feature/2026-11-13-checkout-no-surcharge.md)，固定/比例手续费及美元成本预算为零。先通过既有 GitHub SSH 凭据只读核验生产通道与旧配置，再决定是否能复用旧密钥。日志仅输出安全白名单字段，密钥和签名秘密始终留在服务器。

## Alternatives considered

- 将现有通道整体切换到 taige：配置简单，但该账户微信不符合资格，会丢失现有微信能力，故选择独立通道。
- 仅替换支付方式配置 ID：无需额外通道，但配置属于另一 Stripe 账户，不能与 Raymi 密钥混用。

## Acceptance criteria

- 确认目标账户、正式模式、支付宝可用与对应签名回调。
- 生产备份后写入独立通道并回读；真实 Checkout 验证人民币原价和支付宝，立即过期且不付款。
- 支付回调及通道隔离回归通过；分别记录配置上线、真实付款与订单开通验证边界。

## Risks

旧密钥可能撤销或未在服务器保留，旧回调可能仍用于历史订单；核验前不启用、不覆盖。授权连接不等于生产已接入。

## Related notes audit

活跃 Stripe/支付宝/收款检索仅命中人民币原价决定，属于部分重叠，本篇复用其价格政策并新增账户隔离边界，无需替代旧决定。

## Inspection evidence

2026-11-16 正式 API 已确认目标 pmc 支付宝 available=true、微信=false。生产只读工作流 43801765868 成功：通道 1 为停用的 EPay，通道 2 为 Raymi；目标账户旧 Webhook 同样指向通道 2，不能直接复用地址。容器内仅发现 11 月 13 日的 Raymi 配置备份，继续在项目宿主备份内只读检查旧 Stripe 凭据是否存在。

完整补充核验 43802313152 成功，检查 58 个项目备份文件，仅发现 Raymi 账户凭据，未找到目标 taige 密钥。
需要创建新的受限密钥；浏览器已准备 Checkout Sessions 写、Payment Method Configurations 读、Webhook Endpoints 写三项权限及名称 Xboard taige Alipay，尚未提交创建。
生产通道保持原状，待凭据后继续独立回调、CNY 收银台与签名校验。
