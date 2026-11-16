# Agent Note: taige 账户独立支付宝通道

Status: implemented

## Problem

用户要求将 taige（acct_1UGbyu1DvmJXrFlV）的支付宝接入 Xboard。该账户支付宝可用、微信不可用，现有 Raymi 微信/银行卡仍需保留。旧 taige 回调指向 Raymi 通道 2，不能用于独立支付宝通道。

## Decision

复用 StripeCheckout 的按通道配置及 CNY 收款能力，新增通道 3「支付宝（taige）」，使用目标 pmc_1UGbzR1DvmJXrFlVLsBXHPnq。沿用[人民币原价决定](./2026-11-13-checkout-no-surcharge.md)，固定/比例手续费及美元成本预算为零，关闭 Adaptive Pricing。原 Raymi 通道和旧回调保持原样。

[接入脚本](../../../../.docker/production/provision-taige-alipay.php)通过[手动工作流](../../../../.github/workflows/stripe-alipay-provision.yml)执行；用户已明确授权将新受限密钥保存到 GitHub 加密 Secret XBOARD_TAIGE_STRIPE_KEY 并写入本站服务器。SSH 使用固定主机公钥，临时凭据包权限仅限所有者并在执行后清理；备份仅保留于服务器私有目录。

先备份、创建停用通道，再创建独立回调 we_1UcJKi1DvmJXrFlV4oqriAnb，地址为 /api/v1/guest/payment/notify/StripeCheckout/9c6bc4e15d688363。端点仅订阅 checkout.session.completed 和 checkout.session.async_payment_succeeded，版本 2026-07-29.dahlia。端点创建结果写入私有恢复记录；重复运行复用通道与端点，遇到不受脚本管理的同账户通道或配置漂移则中止。

受限密钥只有 Checkout 写、支付配置读、Webhook 写。无法读取账户身份时，以能够读取且匹配唯一的目标正式 PMC 核验账户归属；不扩大密钥权限。当前真实收银台验证通过，说明这组权限足够本次 CNY 接入。

## Alternatives considered

- 将现有通道整体切换到 taige：配置简单，但该账户微信不可用，会丢失现有能力，因此选择独立通道。
- 仅替换支付方式配置 ID：无需额外通道，但配置属于另一 Stripe 账户，不能与 Raymi 密钥混用。
- 复用服务器旧密钥：可减少新增凭据；只读检查 58 个项目备份仅找到 Raymi 密钥，因此由用户新建三项权限的受限密钥。

## Verification

2026-11-16 14:24（北京时间）[生产接入 43816465969](https://github.com/nanashiwang/Xboard/actions/runs/43816465969)成功：实际生产 PaymentService 创建 CNY 990/3200 收银台，返回指定 PMC 且包含 alipay，两个验证会话均立即过期，未创建本地订单、未付款。公开回调正确签名返回 success、错误签名拒绝；原通道完整快照对比一致。

随后[只读回读 43816611823](https://github.com/nanashiwang/Xboard/actions/runs/43816611823)成功。Payments 本地禁网测试 25 项/114 断言通过，包括独立通道、重复执行、金额异常会话过期、回调失败自动停用；PHP、工作流 YAML/Shell 和笔记门禁通过。

## Consequences

支付宝与微信分别使用独立账户、密钥及回调，报表需按账户汇总。配置启用后，公开回调验证失败会停用本次启用的新通道，原通道不受影响。真实付款、订单开通及商户到账尚未验证，不能把未付款收银台和签名探测称为付款成功。此项为运行配置更新，不改客户端版本、不重启应用、不创建 GitHub Release。

## Related notes audit

活跃 Stripe/支付宝/收款检索仅命中人民币原价决定，属于部分重叠；本篇复用价格政策，新增账户隔离和接入恢复边界，不替代原决定。
