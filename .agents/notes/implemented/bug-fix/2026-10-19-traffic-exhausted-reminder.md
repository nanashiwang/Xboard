# Agent Note: 每个流量周期发送一次耗尽邮件

Status: implemented

## Problem

用户反馈节点延迟正常但国外网站打不开，核对发现账号已用完流量。现有邮件仅处理 80%–<100% 用量，每日 11:30 扫描；用户要求流量用完后也发送一次通知。耗尽后的重复扫描不能每天重复发信，发送失败也不能被永久标记为已提醒。

## Existing capabilities and impact

复用 [MailService](../../../../app/Services/MailService.php)、`send_email` 队列、SMTP 配置和后台邮件模板接口。提醒仍受站点 `remind_mail_enable` 和用户 `remind_traffic` 控制，排除封禁和无邮箱账号。额度为 0 不定义为耗尽。

[TrafficResetService](../../../../app/Services/TrafficResetService.php) 的手动、周期、订单和礼品卡重置均递增 `reset_count`，作为周期标识；不修改用量、套餐或账号权限。检索活跃笔记中的“邮件/流量提醒/remindTraffic/remind_mail”无既有归属，另建此笔记。[探针决策](../feature/2026-10-18-node-quality-probes.md)讨论账号资格与诊断，范围不同，不吸收其决定。

## Decision

新增独立的每 5 分钟耗尽扫描命令，保留 80% 和到期提醒原有调度。使用独立 `remindTrafficExhausted` 模板，避免复用已定制的 80% 文案。

数据库按 `(user_id, reset_count)` 唯一记录耗尽通知，发送成功后写 `sent_at`。队列任务执行前重新检查当前周期、用量和偏好；通过数据库原子更新领取 15 分钟发送窗口，重复任务不同时发信。失败不记成功，可在 15 分钟后重试；队列唯一性只用于减少堆积，数据库记录承担去重。重置后的旧任务不发信，下一周期重新耗尽可发一次。

## Alternatives considered

- 扩大原 80% 发送区间最简单，但会把“80%”模板发给耗尽用户，且现有 24 小时缓存无法保证每周期一次。
- 只用 Redis 按周期缓存可避免迁移，但缓存清空后会重复发送，且发送前写缓存可能吞掉失败后的提醒。
- 在流量上报或封禁检查中触发延迟低，但耦合节点链路，且无法补发上线前已耗尽用户及失败通知；独立扫描可覆盖这些情况。

## Verification

本地使用 PHP 8.2.33 容器、SQLite 内存数据库和 ArrayTransport，容器禁网，不向真实用户发信。`vendor/bin/phpunit tests/Feature/Mail` 通过 13 项 / 69 断言；完整 `vendor/bin/phpunit` 通过 108 项 / 652 断言。覆盖刚好/超过 100%、80% 缓存独立、重复任务/缓存清空、真实 TrafficResetService 重置、旧任务失效、开关/偏好/封禁/无额度、SMTP 失败与过期领取恢复、发送期间重复领取，以及后台模板权限/定制。`actionlint` 通过新增邮件 CI 工作流。

新增 [邮件提醒 CI](../../../../.github/workflows/mail-reminders.yml)，独立回归该能力；生产调度、SMTP 接收和收件箱投递仍须上线后验证，当前不声称已部署。

## Consequences

耗尽提醒独立于 80% 缓存，成功记录不会随缓存清空丢失，周期重置无需清除历史。扫描需要 scheduler 和邮件 worker 正常工作，五分钟只是扫描间隔。SMTP 已接受但进程在记录成功前崩溃时，重试仍可能重复，无法宣称跨数据库和 SMTP 的严格 exactly-once。增加按周期的少量持久化记录；部署必须先迁移。当前周期已耗尽且开启提醒的用户会被新扫描补发。代码、CI、镜像和生产投递分开验收。若用户规模增长使五分钟全表资格筛选成本过高，再考虑用量事件触发加低频补偿；目前不改节点计费或同步链路。
