# Agent Note: 客户导航地址更新通知

Status: implemented

## Problem

用户明确授权向所有客户发送地址更新邮件，要求收藏https://capybarahub.fyi/。既有群发控制器直接入队，没有本次活动持久去重；工作流中断不能导致重复通知，SMTP接受也不能写成全部入箱。

## Decision

复用MailService和既有SMTP，固定中文主题、正文及独立模板，所有链接指向Hub。账号/套餐保留，文案仅承诺持续优化稳定性。首发冻结127个有效唯一注册邮箱；发信期间新增账号不补入快照，不导出名单。

手动preview/send/status工作流；send校验生产revision。每批25封、间隔3秒，私有原子账本及互斥锁放在持久数据库目录的operations下；只记录用户ID、邮箱哈希及状态。发送前写attempting，结合MailLog核对sent，成功跳过；中断无成功日志变uncertain，不自动重发。活动内容指纹变化拒绝继续。

SMTP错误仅输出类别、状态码与固定词表信号，不输出原始错误或配置。明确454 Maximum sending rate/Throttling failure: Rate exceeded且无成功日志的拒绝，下一次send允许一次低速补发；记录rate_retries防止重复循环。daily/quota、普通失败和不确定结果不自动补发。生产曾在71封成功时收到454，按该规则恢复。

## Existing decision audit

- [客户端恢复](../../proposed/architecture/2026-11-02-client-entry-resilience.md)：只通知网页导航，不等于原生客户端自动切换。
- [双域上线](../architecture/2026-11-02-hub-application-domain-split.md)：保留统一账号与独立导航角色。
- [登录加载](../bug-fix/2026-11-03-panel-startup-latency.md)：先部署验收再群发，性能与发信分别核验。

## Alternatives considered

- 直接重复调用后台sendMail：复用最多，但中断后无法判断哪些入队，使用活动账本并复用底层发信服务。
- 导出名单到新平台：便于外部群发但增加数据流转，沿用原SMTP。
- 所有失败自动重试：可提高暂时故障成功率，但有重复投递风险；仅一次补发协议明确拒绝的速率错误，其他保持人工核对。

## Verification

最初邮件及网页相关PHP40项/307断言通过，后续活动专项5项/31断言验证链接、去重、指纹拒绝、中断停止、普通失败停止/跳过、脱敏信号、明确限流恢复及日额度不重试。生产模板/SMTP/revision已校验；最终快照127、sent=127、pending=0、成功日志127，1次历史454拒绝已恢复，无failed/uncertain/changed。最后工作流41496643556与完整证据见[进展](../../../../progress-log.md#2026-11-03登录加载优化与地址通知)。

## Consequences

低速发送需要更久，换取限流余量和可恢复性。SMTP接受不等于逐个收件箱送达，后续退信仍可能发生；未读取客户收件箱。未来不同活动应使用独立活动标识，不复用本次账本。
