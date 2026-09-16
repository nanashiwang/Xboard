# Stripe Checkout（人民币）

后台支付方式选择 `StripeCheckout`。采用 Stripe 托管收银台，卡号不会经过 Xboard；前端返回订单页不作为到账凭据，只有通过签名校验并匹配订单金额、币种和通道的回调才确认付款。

## 配置步骤

1. 保持站点币种为 `CNY`。该插件以人民币分为单位提交金额，包含订单手续费，不做汇率换算。
2. 在 Stripe 测试环境取得 `sk_test_` Secret Key，在 Xboard 新增或编辑 Stripe 支付通道，填写密钥并保持币种为人民币。不要填写 `pk_` 公钥。
3. 保存通道后，复制后台生成的完整通知地址到 Stripe Webhooks。地址结构为 `https://你的域名/api/v1/guest/payment/notify/StripeCheckout/通道UUID`。
4. 选择 `checkout.session.completed`、`checkout.session.async_payment_succeeded` 事件，端点事件 API 版本使用 `2024-06-20`。将此端点的 `whsec_` 签名密钥填回该支付通道。
5. 配置完整后在测试环境验证支付成功、取消、失败、回调重试以及订单只开通一次。测试模式下的通道不要向正式用户开放。
6. 确认 Stripe 账户支持人民币银行卡收款后，切换到正式环境的 `sk_live_` 和对应正式 Webhook 的 `whsec_`，再启用通道。两个环境的密钥不能混用。

未配置真实账户密钥时，只能完成模拟接口和签名回调测试，不能宣称实际收款联调成功。当前仅开放银行卡支付，不自动启用支付宝、微信或订阅自动扣款。若 Stripe 拒绝人民币收款或小额订单，请在 Stripe 后台核实账户支持情况及最低交易金额。

## 内置插件下拉框为空

Docker 的 `/www/plugins` 是持久化挂载目录。镜像必须保留 `/opt/default-plugins`，并在 Laravel 启动前复制到挂载目录。否则数据库虽显示插件启用，下拉框仍拿不到支付方式。此修复同时保留缺失插件的数据库记录，不将文件暂时缺失当作卸载。

## 验证

`vendor/bin/phpunit tests/Feature/Payments` 覆盖人民币金额、手续费、幂等键、签名与时间窗口、错误币种/通道/环境、重复回调、缺失配置及插件下拉框。

参考：[Stripe Checkout](https://docs.stripe.com/payments/checkout/how-checkout-works)、[Webhook 签名验证](https://docs.stripe.com/webhooks/signature)。
