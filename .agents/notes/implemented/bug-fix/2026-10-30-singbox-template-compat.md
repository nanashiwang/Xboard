# Agent Note: sing-box 默认订阅模板与版本适配一致

Status: implemented

## Problem

香港入口历史验证发现完整订阅不能通过 sing-box 1.13.19 检查。`SingBox::adaptConfigForVersion` 声明模板基准为 1.13，但默认 JSON 仍使用 legacy DNS、入站 sniff/domain_strategy、endpoint_independent_nat 和 block/dns 出站。单节点探针绕过模板，不能证明完整订阅兼容。实际导出从 SubscribeTemplate 数据库读取，首次迁移才导入文件。

## Decision

默认模板改用 typed DNS、路由 sniff/resolve/hijack-dns 和 default_domain_resolver；保留解析服务器、代理组、私网/国内直连、TUN 地址和严格 TLS 节点参数。补齐已有降级器对默认模板新增字段的处理，覆盖 1.9、1.10、1.11、1.12、1.13 以及未知版本请求。只改仓库与本地测试，不覆盖数据库中的自定义模板，不部署生产。

## Existing decision audit

- 未提交的香港入口架构笔记记录完整订阅 legacy 格式失败，本轮读取作为历史线索，保留原文件及运维文档，不将此前生产记录混入本次提交。
- [第一阶段替换](../../implemented/architecture/2026-10-17-stage1-replacement.md)部分重叠：模板待办由本篇承接，节点部署和计费验收不变。
- [Clash Meta DNS](../../implemented/bug-fix/2026-10-18-clashmeta-google-dns.md)部分重叠：沿用已有数据库模板不随代码升级被覆盖的边界，客户端规则独立。
- 检索 proposed、implemented 与现有笔记未发现同主题格式修复；无拒绝记录目录，无需归档或删除旧提案。

## Alternatives considered

- 在导出时通用转换任意旧自定义模板：可立即覆盖旧安装，但自定义 DNS、逻辑规则和出站引用的语义远超默认模板修复范围，可能改变用户策略，因此不做隐式迁移。
- 只删除报错字段或开启内核兼容环境变量：改动更少，但会丢失 DNS 引导与嗅探，或依赖客户端设置，不能作为可移植订阅修复。
- 仅更新 JSON：符合现代内核，但现有降级器不处理 sniff/resolve 和 default_domain_resolver，会破坏旧客户端；必须同步最小降级处理。

## Testing

- 合成香港 VLESS/WS/TLS 节点经 ClientController::doSubscribe → SingBox::handle → 数据库模板完整导出，测试库为 SQLite 内存库，容器禁网，未使用生产账户或配置。
- 旧代码和旧默认模板在 1.13.19 的 check 返回 1：legacy DNS 要求 ENABLE_DEPRECATED_LEGACY_DNS_SERVERS；只替换 DNS 后仍返回 1：legacy inbound fields 已移除。未开启兼容环境变量。
- 修复后真实内核 1.9.7、1.10.7、1.11.0、1.12.0、1.13.19 的完整配置 check 各通过。参考官方[迁移说明](https://sing-box.sagernet.org/migration/#migrate-legacy-inbound-fields-to-rule-actions)，将默认入站解析/嗅探移到路由，而非直接删除行为。
- PHP 8.2.33：订阅模板、名称和探针相关 37 项 / 471 断言通过，其中本轮 9 项覆盖版本边界、未知版本、数据库自定义模板保留、DNS 引导、路由顺序、代理引用及节点 UUID/严格 TLS/WS 参数。
- 扩展执行 Desktop + Probes 共 95 项时，已有下载目录测试出现 2 失败 / 3 错误：HEAD 的 ClientDownloadService 仍查找 0.1.5 文件，而 HEAD 的下载 manifest 已为 0.1.9。此问题与订阅模板无关，不混入本轮修复。
- 现有 Website Home Checks 增加模板/导出器路径触发和完整订阅专项；固定官方 1.13.19 Linux amd64 musl 包并校验 SHA-256，再调用真实 check。核心检查可用 SING_BOX_BINARY 指定其他版本；未提供二进制时仅该项明确跳过。

## Consequences

默认模板与声明的现代基准一致，同时保留 1.9–1.12 的默认配置导出；未来模板新增语义时必须同步相应降级与真实内核回归，不能仅调整 JSON。降级限于现有默认模板用到的无条件 sniff/resolve 和字符串 resolver，不声称支持任意自定义高级动作。

旧安装仍需备份并审阅数据库模板后显式更新；本轮不操作生产、不新增数据库迁移。自定义模板保留意味着旧格式仍可能被现代内核拒绝，这个边界不会因发布代码而消失。配置检查不等于 TUN 权限、真实代理、速度或计费验收。未知版本继续按模板基准输出，不推断任意第三方客户端内核版本。
