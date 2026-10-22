# Xboard 项目进展记录

本文件保存项目反馈、排查结论、方案取舍、后续行动及验证结果。当前摘要见 [README.md](./README.md)，代码索引见[能力地图](./docs/FEATURE_MAP.md)，详细取舍链接到[决策笔记说明](./docs/AGENT_NOTES.md)中的统一笔记树。记录日期使用 Asia/Shanghai。

每次完成后先回读本地文档，再在推送后按提交版本从 GitHub 回读 README.md 与 progress-log.md。未运行的检查、未完成的构建、未发布的版本和未部署的代码须明确区分；不记录密钥或用户凭据。

## 2026-10-22：网站 Cloudflare 路径与访问耗时核对

用户询问 Xboard 的 taige 网站是否走 CF，并反馈访问慢。本轮只读访问线上公开站点、检查浏览器登录页与仓库入口代码；未修改网络或生产配置。面板域名与节点域名的职责见[既有域名决定](./.agents/notes/implemented/architecture/2026-10-22-independent-node-domain.md)，本轮没有新增架构决定。

- 北京时间约 15:54 起，Cloudflare DNS-over-HTTPS 返回 taige.us 与 board.taige.us 的 A 记录为 104.21.13.31、172.67.132.124；两个站点均 HTTP 200，响应包含 server: cloudflare、CF-Ray 的 LAX 后缀及 Via: 1.1 Caddy。此为公开路径证据，没有读取当天 CF 控制台规则。
- 本机系统 DNS 返回 198.18.0.195/196 的代理虚拟地址，因此测速经过当前代理路径，不能用作大陆无代理或其他运营商的结论。curl 使用 Mozilla/5.0、压缩和全新连接，小样本并非持续监控。
- 三次首页 HTTP 200，总耗时 2.140/2.089/2.050 秒；公开配置 HTTP 200，为 2.152/2.080/2.066 秒；这六次 TLS 完成耗时约 1.439–1.531 秒。首页与配置均 no-cache, private / CF-Cache-Status: DYNAMIC，不能把用户私有 API 改成公共缓存。
- 主资源 /theme/Xboard/assets/umi.js 前两次 HTTP 200，2.888/2.799 秒，gzip 传输约 420 KB，CF 缓存由 MISS 转 HIT，Cache-Control: max-age=14400；第三次新连接 25.003 秒超时，没有收到 HTTP 响应。没有证据称缓存或压缩未启用。
- 独立追加一次同连接顺序请求：首页 2.060 秒、TLS 1.441 秒；复用连接后配置 0.524 秒、JS 0.913 秒，后两次新建连接数为 0。这支持当前路径建连开销明显；不能把握手后的等待直接当成后端执行时间，尚未完成源站回环及大陆对照。
- 浏览器到达 taige.us/#/login，登录表单可见，未捕获 warn/error；公开配置 is_captcha=0、is_recaptcha=0。只验收未登录公开页面，不扩展为登录后全部业务性能正常。
- 代码核对：首页同源加载 umi.js，API 同源 /api/v1；本地主包约 1.42 MB，包内存在 Iconify 外部域名，但未证实当次页面发起相关请求，不将其列作已确认瓶颈。

后续先补反馈用户的实际网络、代理开关与慢的环节，再对比用户→CF、CF→源站和应用处理；不直接以关闭 CF 为确定提速方案。本轮仅文档记录，保留既有香港入口未提交工作；不调整版本、不构建应用、不发布 GitHub Release、不部署。本地工作流验证通过（15 篇笔记及相对链接），暂存差异检查通过；本节使用中文 [skip ci] 文档提交推送 master，避免无业务变更时重建镜像。推送后按该精确提交回读 README 与本文件，交付结果随回复报告。

### 大陆无代理补充对照

用户明确回答「大陆网络，未开代理/VPN」。约 16:03 起补测：保持系统配置原样，仅为 curl 绑定物理网卡 en0、使用 --noproxy '*' 和 --resolve 固定当前 DNS 返回的地址，严格校验原域名 TLS。实际 remote_ip 与指定目标一致，CF trace 显示 loc=CN、warp=off；这是本机大陆网络样本，不代表其他地点、运营商或用户当时每一次访问。

| 路径与对象 | 结果 |
| --- | --- |
| CF IPv4 两个 A 地址，首页各两次 | 4/4 完成，0.736–0.937 秒 |
| 同组公开配置 | 3/4 完成，0.764–1.703 秒；另一次 TLS 已完成，等待响应 20.005 秒超时 |
| 同组主 JS | 3/4 完整下载，1.339–1.674 秒；另一次 HTTP 200 但仅收 61,190 字节，20.006 秒超时，不计成功 |
| CF IPv6 两个 AAAA 地址 | 两次 trace、两次首页、两次 JS 均完成；首页 0.914/1.328 秒，JS 1.729/2.083 秒；trace 为 CN / SEA / warp=off |
| 严格 TLS 公网直连源站 | 首页 0.880 秒；JS 2.567 秒，传输 1,420,663 字节且未含 Content-Encoding，即使请求允许压缩；仍包含大陆到源站公网耗时 |

IPv4 trace 的 colo 为 LAX，业务响应 CF-Ray 后缀出现 LAX/SJC/LHR；IPv6 trace 为 SEA，不能把 CF-Ray 后缀单独当作完整网络路由。当前样本支持境外 CF 路径存在间歇卡顿，正常 CF 下载受益于压缩与缓存；不把静态文件 HTTP 200 当作完整传输，也不把源站直连单次成功当作关闭 CF 的性能保证。两个 IPv4 地址仅 12 次样本，未评估全天或全运营商。

源站映射由[既有域名部署文档](./docs/zh-CN/installation/primary-domain.md)复核。现有密钥的只读 SSH 尝试未通过公钥认证，未扩大凭据搜索或修改认证，因而没有源站回环、应用处理时间或当天服务日志证据。后续应保持现网，用同网络重复对照并结合源站耗时再决定入口调整；源站 JS 压缩可作为独立优化候选。本轮未执行配置修改、客户端切换、重启或部署。

本地工作流验证通过（15 篇笔记及相对链接），暂存差异检查通过。补充文档沿用 [skip ci] 中文提交至 master；推送后按精确提交从 GitHub 回读 README 与本文件，无应用版本或 Release 更新。

## 2026-10-22：节点入口迁移至 lumavia.fyi

用户购买独立主域名以分开面板和节点的域名故障范围，并在恢复七云登录后明确继续使用七云。本轮保留 `143.203.200.5` 主入口和 `192.204.56.29` CF 备用，普通套餐的两个美国出口不替换，不从独享池调出服务器。决定见[节点入口独立主域名](./.agents/notes/implemented/architecture/2026-10-22-independent-node-domain.md)。

- 新 DNS 为 `node.lumavia.fyi` DNS-only A 指向主入口、`edge.lumavia.fyi` 代理 A 指向七云，CF 为完全（严格）。没有 CNAME 回旧主域。面板、订阅地址、支付回调及节点管理 API 继续使用原域名。两张源站证书均签发成功，到期 2027-01-19；现有 certbot timer 与部署后 nginx 检查/reload hook 已核验，新证书未单独执行模拟续期。
- 两台新建独立 Nginx vhost 并复用既有路由片段，语法通过后 reload。原域名站点、证书及 DNS 保留，CF-only 来源限制保持；未改 WireGuard、后端协议、端口、上游出站或运行节点项目。原路由片段内发给后端的旧 Host 保留，它不是旧域 DNS 依赖。
- 切换前新主域 57 条、CF 1 条共 58 条线路均首轮通过严格 TLS 的 Cloudflare trace 200 / 实际出口和 Google 204；58 条随机无效 UUID 均拒绝，随后有效身份复核通过。新主入口首次 reload 后立即读取曾命中尚未退出的旧 worker，随后独立请求正确证书并完成全线路验收，未将该瞬时结果当作持续故障。
- 数据库先做一致性备份，事务起始取得 SQLite 写锁后一次更新 **74 条**记录（69 主入口、5 CF，含固定别名与已停用项）的 host / TLS SNI / WebSocket Host，以及原入口监控 #1 的 host；停用项仍停用。全量 **135 条**节点对照备份除这三处域名与正常运行字段外一致，实际倍率、路径、ID、父子关系、权限、机器与来源保护保持。
- 切换后重新按实际数据库生成 58 条出站，双目标 HTTPS 再次全部首轮通过。四档 × Clash Meta/Shadowrocket 共 **8/8** 实际 HTTPS 订阅通过：**14/22/34/47** 条、名称唯一、全部 host/SNI/WS Host 为新域且严格 TLS。旧主域和旧 CF 各抽验一条真实代理通过。用户应更新原订阅；未更新客户端继续走旧域兼容入口。
- 11 个启用固定别名与公开源的父后端、host、port、协议、倍率相等，对应源路径已实测；本轮未额外使用客户身份或触发固定用户订阅。固定绑定在应用和清理事务内保持；期间原健康任务产生两次 exit_failed 自动迁移（一条发生在切换前、一条在切换后），不能把原有健康迁移描述成永久固定或因域名成功而全部可售。25 个既有客户身份/余额/权益、5 个套餐、49 个订单、两套探针与 20 台机器配置保持；用量、在线状态、心跳正常变化不纳入静态配置不变量。
- 两套探针均收到晚于切换的全部节点样本，覆盖自建 17 条及拓展 41 条；拓展 41 条当时均 healthy，NAS 样本仍有 degraded/超时，入口健康样本也有失败。入口切换后前五次为两次成功、两次等待首字节 8 秒超时、再次成功；最新成功样本 1792608215，总耗时 585.73 ms。失败时 DNS/TCP/TLS 已完成，未归因具体超时根因。记录原始波动，不修改阈值或强制标绿，不把服务器侧全通过宣称为大陆运营商或 NAS 长期稳定。上游保护 timer active/enabled，最近拉取成功、撤下数量 0；原入口 ID、监控身份、隧道映射和机器资源采集保留。
- 五个临时 QA 账号及其统计已删除；跨节点同步周期后，在新主入口和新 CF 各验证旧 QA 身份拒绝，同路径有效监控身份仍成功；第二次仅清理这五个 ID 的迟到统计，残留为 0。备份 integrity_check=ok，完整客户端配置和临时登录密码在交付清理，不写入仓库。

面板容器 `storage/app/backups/lumavia-20261022/` 保留一致备份与精确 before/after；宿主同名 backups 目录保留脱敏验收结果；两台入口 `/root/xboard-lumavia-20261022/` 保留站点回退材料。回退只恢复本轮域名字段与相关站点，不整库覆盖后续订单、用量或分配。新域名隔开注册域名风险，仍共享部分 DNS/管理账户和入口资源，未实现面板故障下冷启动独立运行。

本轮为生产配置与文档更新，Nginx/PHP 语法、15 篇笔记门禁、相关文档链接和 diff 检查通过后中文提交推送 master，再按精确 SHA 从 GitHub 回读 README/progress-log。没有应用源码变更、镜像构建、应用部署或 GitHub Release；运行 OCI revision 仍为 `f4f3849045b7d71f1d2dd4b6e42e73480cbc9c68`，容器启动时间保持 2026-10-19 08:11:06 UTC。原香港入口未提交工作保持原归属，不纳入本次提交；最终提交与回读结果见本轮交付。

## 2026-10-22：节点短名称与美国家宽 2 倍率

用户要求名称只保留国家、倍率及家宽/原生 IP 属性，并明确全部自建美国均标家宽。线上改为 `国家两位编号｜倍率×｜可选属性`：普通美国为 `美国01｜2×｜家宽`、`美国02｜2×｜家宽`；编号固定跨套餐一致，避免 Clash 名称和 Sing-box tag 重复。家宽属性采用用户定义；香港 U36/U37 的原生 IP 沿用上游声明，未独立核验。

- 13 个自建美国出口覆盖普通两个、独享池十一个，后端、公开源与固定别名共 39 条倍率记录同步 2×，71 个显示名称统一；隐藏计量后端保留运维名，6 条已停用的重复 CF 记录保持。固定套餐文案同步 2 倍，其他线路 1×/2×/5× 不变。供应商、入口阶段、自建/拓展、U 编号和限制尾缀不再出现在客户端；UDP/共享限速仍按原规则执行并保留运维映射。
- SQLite 先做一致备份。首次事务因 `database is locked` 在第一条更新失败并回滚；调整为有限 busy timeout、事务起始先取得写锁与重试后成功，无需停止业务。最终 135 条节点仅有批准名称/倍率字段变化，25 个既有身份权益、49 个订单及两套探针配置保持，5 个套餐只有专属倍率文案变化；备份 integrity_check=ok。
- 原生后端仅改名称/倍率不会触发 ServerObserver 配置同步或重启。四档 × Clash Meta/Shadowrocket 共 8 项真实 HTTPS 订阅均 200，数量保持 14/22/34/47、名称唯一且不含上游凭据。独享在回滚事务内只读验证为一个 2× 美国别名与 1× 香港备用，没有用订阅读取提交分配变动。
- 13 个美国家宽出口、一个日本自建 1× 对照及一个第三方 2× 对照最终全部实际 HTTP 200。首轮 4 条未完成且未入账，稍后重试全部通过。专用客户端排除 SOCKS 握手，精确统计真实代理应用字节；13 条家宽合计原始 16,474 字节，扣量 32,948 字节；日本对照 1,167 字节按 1×，第三方对照 2,408 字节按 2×。四名有测试流量账号的上传、下载、倍率统计逐项相等；第五名只验证订阅、无流量。测试未使用客户身份，五个 QA 账号验证后删除，旧测试身份实际请求已拒绝。
- 配置过程未写固定分配；既有健康调度期间记录一次 `exit_failed`，原出口 7 自动迁到 8，不能宣称绑定始终未变。原 NAS 观测仍有波动，未手动修改 healthy；拓展探针 41 条健康、来源保护 fetch_ok 且撤下 0 条。名称修改不会修复既有网络波动，也不改健康迁移规则。

[实施决定](./.agents/notes/implemented/simplification/2026-10-22-node-names-and-residential-rate.md)、[公开映射](./.docker/node-presentation.json)与[拓展运维](./docs/zh-CN/installation/upstream-extension.md)已同步。生产容器 `storage/app/backups/naming-20261022/` 保存一致性数据库、字段变更清单和应用结果，宿主同名 backups 目录保留脱敏验收结果；回退只恢复清单中的名称/倍率及套餐文案，不整库覆盖用量、订单或分配。旧 `dedicated:attach-owned` 初始导入命令仍限制 1 倍，维持对 2× 池的拒绝；`dedicated:prepare` 与仓库 plan.json 保留历史 1× SOCKS 初始化契约，未把模板文案单独改 2× 造成扣量不符。两种旧流程均不适用当前池，新增导入需另行适配。

本轮为配置与运维记录更新；相关 5 项保护/分档回归、字段映射/名称唯一性、本地链接、工作流及差异检查后中文提交推送 master，再按 SHA 回读 README/progress-log。应用运行版本仍为 `20261019-f4f3849`，没有重启节点、构建或部署新应用镜像、发布 GitHub Release；此前未提交香港入口工作不纳入。

## 2026-10-22：第三方拓展线路实际接入

用户看到只有六条自建而非规划的十四条，确认后要求实际接入。本轮将全部 41 条第三方线路发布到四档普通套餐，累计拓展 8/16/28/41，加上自建 6 条后真实订阅 **14/22/34/47**。之前的评估与规划记录仍是历史阶段，不能当作当时已上线。

- 承载机为第一阶段服务器，独立机器 21、独立非 root 服务；41 对公开/隐藏记录为后端 359–439 奇数 / 公开 360–440 偶数，回环端口 37001–37041，专用 nft 阻止公网后端访问。共用 TLS 入口，未改原自建隧道/路由。全部原 53 条节点配置、25 个既有身份与权益、5 套餐及 49 个订单对比备份保持，独享启用池仍 11。
- 3 条公共 CA 校验、38 条首次信任公钥固定；非 QUIC 自签名将连接 IP 与公钥配对，解决 DNS 轮换导致的错配。28 条 IPv4 TCP 从另一服务器比对相同；IPv6/QUIC 不声称独立认证。没有全局关闭证书校验，源凭据只留私有服务器配置。
- 承载机全 41 条双目标 HTTPS 成功；完整面板鉴权/入口转发后最终 41 条 HTTPS 成功、33 条 UDP DNS 成功。8 条美国对 1.1.1.1/8.8.8.8 的 UDP 请求均未通过，名称明确限制。四条低流量共享双向 2 Mbps，首次 policing 默认 MTU 2 KB 误丢 TLS 包，修正为 65536 后 HTTPS/UDP 通过。一次 2 MiB 下载未在 40 秒完成，限速为上限，不宣称持续速度。
- 41 后端的十类账号权限矩阵符合；42 次真实越级、到期、耗尽、封禁、未付费、独享与无效 UUID 被拒绝；原自建 6/6 通过。四档最低权限代表线路复测通过。临时账号分别测试 1x/2x/5x，快照中用户计费、后端字节乘倍率和用户统计同为 6,230,856 字节，公开记录零上报，没有重复扣费；九个测试账号随后删除，旧测试身份真实请求被拒绝。
- 四档 × 两格式实际 HTTPS 订阅共 8/8 HTTP 200，条数准确且不含上游身份；测试器最初误用 Shadowrocket URI fragment 读取名称，按实际 remark 参数后正确核对。信息提示不算代理线路；客户原订阅地址不变。
- 上游保护每 5 分钟检查额度、有效期与批准来源指纹，变化/消失/歧义仅撤下对应条目，新增未知源不加入；未实现未经核验的凭据自动替换或自动重新上架。单候选撤下、真实拒绝、恢复与再请求通过；原管理 WebSocket 8076 不可达，REST 轮询约 60 秒，第一次过早拒绝测试失败、跨周期后成功。停用后的最后一批报告可能被现有 enabled 鉴权拒绝，不能称停机计量无损。
- 探针 2 从面板服务器每 300 秒覆盖 41 条，每天每条 64 KiB 上下行完整性检查；连续两轮 41 条均按原规则判为 healthy，82 项 64 KiB 上下行完整性检查全部通过；NAS 探针 1 的 17 条及独享健康判断未改。原生服务验收约 45 MiB 内存、0 次重启；短期观察不替代长期稳定、并发容量或运营商测试。

原始一致性 SQLite 备份与映射在容器 `storage/app/backups/upstream-20261022/`（integrity_check=ok）；宿主同名 backups 目录保留受限保护配置与验收结果；第一阶段 `xboard-upstream-review/deploy-backup/` 保留局部回退材料。详情见[实施决定](./.agents/notes/implemented/architecture/2026-10-21-tiered-upstream-route-family.md)、[运维](./docs/zh-CN/installation/upstream-extension.md)、[分配清单](./.docker/upstream/allocation.json)。回退只撤本轮拓展，不整库还原。

本轮是生产配置、运维脚本与记录更新；本地保护/分档 5 项回归、PHP/Python/shell 语法、13 篇笔记工作流和链接检查通过。按项目约定中文提交至 master 后，按提交 SHA 回读远端 README/progress-log；最终提交与回读结果见本轮交付。无应用源码或镜像更新，运行版本仍为 `20261019-f4f3849` / OCI `f4f3849045b7d71f1d2dd4b6e42e73480cbc9c68`；未触发应用构建或 GitHub Release，既有未提交香港工作未纳入。

## 2026-10-21：自建美国出口按套餐拆分

用户要求四档普通套餐只保留两个现有自建美国节点，其余用于独享。本轮已实际应用生产权限，第三方订阅仍未接入；更新后的拓展规划目标为 **14 / 22 / 34 / 47** 条（自建每档 6 + 第三方累计 8/16/28/41），取代上一轮基于全部美国共享出口的总数。

- 按 IP 核对为 13 个美国出口，16 条普通美国订阅记录中四个 CF 条目共用一个 IP。保留 #319 → #332（美国 06，38.244.38.191）和 #148 → #147（CF 基础备用，192.204.56.29），两条有新鲜成功观测、没有固定账号/预留占用，并分属第一阶段与 CF 入口。其余 11 个去重出口继续使用原固定池别名，原公开源记录只给监控组；普通账号不能通过旧地址认证这些后端。
- 两个保留出口的固定池项 #11/#18 停用，对应别名 #345/#352 隐藏；重复 CF #150/#156/#158 与后端 #149/#155/#157 清空权限并停用。全部记录保留以便局部回退，没有整库恢复或删除账号/订单。
- 复用专用监控账号 #33，迁到新内部组 6（非销售组、无套餐关联、仅一个监控身份），不改其 UUID/令牌、额度或有效期。池后端仅组 5/6，两个普通美国后端仅组 1–4/6；香港、日本、荷兰、罗马尼亚保留原客户权限并允许监控。探针移除三个重复 CF 后为 17 条，入口隧道映射不变。
- 应用前六条保留普通线路实际 HTTPS 6/6 成功；保存 SQLite 一致性备份（integrity_check=ok）和字段回退快照。首次事务把分配锁 allocation_version 变化误判为配置漂移，在实际权限修改前回滚；标准输入 PHP 的 STDERR 常量不可用也使异常输出不符合 JSON。修正为业务字段指纹和 php://stderr 后重新预览，确认候选差异一致再应用；未把错误命令退出码 0 当作成功。
- 应用事务中四档可见 ID 均为 `[148,319,325,354,356,358]`，独享启用池为 11；套餐条款与当时的固定绑定未变。前后对比 25 个既有账号的凭据、余额、套餐、额度、限速、设备限制和有效期，仅专用监控组变更；测试产生的真实用量正常累计。原固定订单金额/周期/状态保持。
- 新增监控组隔离回归，相关 **12 项测试 / 99 断言通过**；本地 PHP 8.5.9 有一项现有弃用提示。Python 与嵌入 PHP 语法检查通过。生产 **48/48 项**真实请求符合预期：13 次监控、6 次普通线路、1 次固定出口、1 次香港备用成功；26 次越权和 1 次无效 UUID 拒绝。Clash Meta / Shadowrocket 两种实际订阅输出 × 四档 = **8/8 项**通过；11 个池后端均无普通组账号，17 条探针配置无错误且已收到切换后的真实新样本，机器 2 仅运行 CF 基础后端。
- 审计发现原 `getAvailableServers()` 会按健康状态迁移固定分配，因此运维验收改为健康前置检查与回滚事务，不用读取订阅触发迁移。健康日志显示本轮应用前已有多次 exit_failed 自动迁移，应用后仍按原调度迁移；48 项验收时固定账号为一个美国分配出口与香港备用，实际连接成功。最新健康快照为 3/11，其他等待真实观测恢复；未手改健康或放宽阈值，不能将配置数量解释为同时可售容量。
- 本机默认路由经 utun，旧代理权限撤销后 SSH banner 为空；绑定 en0 的管理连接 1.82 秒取得真实 SSH banner。后续管理和验收通过独立连接执行，没有改系统代理。客户需刷新订阅并选择保留线路。

操作快照位于生产容器 `storage/app/backups/us-split-20261021/`，成功应用数据库备份为 `database-20261021-234438.sqlite`；宿主 `backups/us-split-20261021/` 保留执行与验收脚本。回退只还原本轮节点、池项、监控字段并同步运行态，先核对当前绑定，不覆盖后来订单和用量。方案与具体映射见[拆分决定](./.agents/notes/implemented/architecture/2026-10-21-owned-us-package-split.md)。

已更新固定池生产清单、运维验收脚本、回归测试、第三方规划基数和导航。13 篇笔记工作流门禁、263 个本地链接、差异与 11 出口清单/41 条第三方分档核对通过；随后中文提交推送 master，并按精确提交回读 README/progress-log。本次为生产配置与运维更新，无应用源码变更；实际运行 OCI revision 仍为 `f4f3849045b7d71f1d2dd4b6e42e73480cbc9c68`（`20261019-f4f3849`），没有构建新应用镜像、替换生产程序或创建 GitHub Release。原未提交香港入口工作保持原归属。

## 2026-10-21：四档套餐双线路分配规划

用户后续明确希望把第三方订阅全量分档加入四个普通套餐，价格越高节点越多，并保留自建与第三方两种路线。本轮完成规划；原评估的少量备用建议不再代表本次目标，但其抽测范围和风险记录继续保留。

- 只读生产套餐确认：轻量 ¥9.9/月、25 GB、10 Mbps；标准 ¥20/月、50 GB、30 Mbps；进阶 ¥29.9/月、100 GB、100 Mbps；旗舰 ¥49.9/月、200 GB、未配置套餐限速。设备限制依次 2/4/5/8；普通组 1–4，独享组 5。读取未修改数据库，临时连接密码完成后删除。
- 全部 41 条分为本档新增 8/8/12/13，累计 8/16/28/41；叠加同日已核对自建数 17/18/19/20，目标总数 25/34/47/61。普通基础地区先覆盖，标准扩充欧美，进阶增加日港新与美国 Hy2，旗舰加入 IPv6、台湾及低流量候选。更高套餐表示选择更多，不依据名称宣称速度更高。
- [架构提案与逐条清单](./.agents/notes/implemented/architecture/2026-10-21-tiered-upstream-route-family.md)当时为 proposed，10 月 22 日完成接入后转为 implemented。复用公开/隐藏节点、group_ids、custom_outbounds/custom_routes 与节点倍率计量；单独拓展后端将用户 Xboard 身份转换为服务端上游身份。共同入口仍是共同故障点，独享权限与固定出口池不扩展。
- 拟保留售价、总额度和现有限制，默认自建、拓展手选，明确 1x/2x/5x 及低流量用途。全部用户共享同一上游账户额度，上游容量不能按节点数或用户数放大。38 条证书校验问题、IPv6、上游共享限制、有效期/额度、实际服务器到出站和多用户计量仍待上线前完成。
- 清单校验覆盖 41 个唯一条目，排除 5 条信息项；协议数、地区数和倍率标签数与已读取订阅摘要一致。逐档包含关系、累计计数、权限排除独享、248 个本地文档链接、12 篇笔记工作流门禁与差异检查均通过。结构检查不代替生产转发验证。

本轮为文档方案，未部署中转、修改套餐或订阅模板，未运行应用测试/构建或发布新版；生产版本仍沿用已验收的 `20261019-f4f3849`。本轮文件经中文提交推送 master，再按精确提交从 GitHub 回读 README/progress-log；不创建 GitHub Release。原未提交香港入口工作保持原归属。

## 2026-10-21：第三方订阅转发可行性评估

用户提供一份第三方订阅，询问节点数量以及转发是否合适；本轮范围是评估，没有创建节点、修改套餐、部署转发或扩大独享出口池。

- 按 Clash Meta 格式读取后共 46 个条目，排除 5 条额度、到期和使用提示，得到 41 条线路：AnyTLS 28、VLESS 3、Trojan 3、Hysteria2 7。名称标注 11 个国家和地区，去重后为 39 组 server/port，不能当作 41 个独立出口 IP；各条真实落地还需逐一验证。
- 38 条配置为 skip-cert-verify=true；8 条名称标注 IPv6，其中 5 条服务器地址为 IPv6 字面值。15 条名称标注 2 倍率，2 条标注 5 倍率。标注和配置均为订阅快照，不代替供应商实际计费、并发、IP 限制与允许共享的条款。
- 使用已存在的 Mihomo 1.19.32 对 41 条线路执行独立配置检查，解析通过。已有原生节点二进制的 Go 模块信息显示 sing-box 1.13.2 和 sing-anytls 0.0.11；[官方 AnyTLS 出站文档](https://sing-box.sagernet.org/configuration/outbound/anytls/)与[Hysteria2 出站文档](https://sing-box.sagernet.org/configuration/outbound/hysteria2/)说明相关协议字段。面板 [buildNodeConfig](./app/Services/ServerService.php)支持下发 custom_outbounds/custom_routes，但本轮未验证新的生产出站配置。
- 仅抽查 3 条原配置保持证书校验的 VLESS CDN 线路：两条日本、一条韩国。独立本地内核绑定 en0、仅监听回环、无直连回退，不修改系统代理。首轮采用 Cloudflare DoH/IPv6 解析的 6 次 HTTPS 均失败；调整测试为 AliDNS DoH/IPv4 解析后，Google 204 与 Cloudflare trace 共 6/6 成功，耗时 1.881–2.932 秒，实际出口国家为 JP/JP/KR。结果说明测试 DNS/解析条件影响连通性，不能把首轮失败直接认定为上游节点故障，也不能把整次 HTTPS 耗时当作网络 RTT。
- 未对剩余 38 条关闭证书校验后测试，未完成全部节点真实出口、UDP、IPv6、服务器到上游、吞吐、并发及长期稳定性验收；没有核实上游是否允许共享/转售。账户额度与短期到期信息已向用户说明，不落入仓库。

当前判断是先作为少量地区补充或备用候选，不能直接据节点数量承诺主线路容量。若后续接入，链路应为用户 → 自有入口及 Xboard 鉴权/计量 → 受限保存的上游出站 → 目标网站；所有下游用户仍消耗同一份上游订阅额度。此处是待实施建议，不是已部署能力，不新增已实施架构笔记。

本轮仅文档更新；门禁、链接和差异检查后中文提交推送 master，并从 GitHub 回读 README/progress-log。生产应用版本保持 `20261019-f4f3849`，无应用构建、部署或 GitHub Release。完整订阅和含凭据测试配置完成后删除，仓库不保存订阅链接、令牌、上游密码或 UUID。

## 2026-10-21：节点显隐与闲置记录核对

用户要求确认节点管理中是否有无用记录，无用则直接删除，并询问 `qy_cdn_be_e88926613859a0b9` / `__自建后端|七云美国-旗舰` 为何显示服务器在线但开关关闭。

- 2026-10-21 22:38:16 UTC+8 只读生产快照共 53 条记录：20 条普通订阅入口、13 条固定出口别名、20 条隐藏后端。每条公开记录均指向现存后端；20 条隐藏后端均为 enabled=true、绑定现存机器，且至少被一个 show=true 的公开节点引用；13 条固定别名均对应已启用的出口池记录，其 shared_server_id 与 parent_id 一致。未发现孤立或无用途的节点，未执行删除或修改生产节点。
- 用户例子为后端 #157，地址 `10.77.0.2:31006`，绑定机器 #2「七云美国｜192.204.56.29」，show=false、enabled=true，权限仅组 4。公开节点 #158「美国自建｜旗舰｜CF备用」以 parent_id=157 引用它，出现在旗舰套餐及探针 #1 范围内。删除 #157 会破坏 #158 的下发和转发，不符合“没有用才删除”的条件。
- 实际后台表头为「显隐」，关闭仅表示隐藏订阅入口；[管理控制器](./app/Http/Controllers/V2/Admin/Server/ManageController.php)分别保存 show 和 enabled。[机器下发](./app/Services/ServerService.php)筛选 machine_id + enabled=true，[订阅筛选](./app/Services/ServerService.php)使用 show=true 和用户权限/出口分配。公开子节点无需重复绑定机器运行服务。
- 后台「服务器在线」表示机器心跳，节点在线数据另由[Server 模型](./app/Models/Server.php)读取自身或父节点缓存；在线、订阅可见和服务启用是不同维度。#157 本轮读取有新鲜检查/流量上报时间，累计流量不等同于当时正在承载终端用户；备用线路即使当前无活跃连接也有用途。 NAS 最近一轮 #158 的 Cloudflare 200 / Google 204 均成功，出口为 `192.204.56.29`，采样时间戳 1792593489。
- 四档普通订阅重新生成后仍为 17/18/19/20 条，现有固定账号仍为 #340 / #325。既有 20 条探针节点和 16 条入口隧道引用均保留；服务器资产表与历史出口池记录不属于本次“节点管理”清理范围。

本次为只读用途审计与说明，没有改变架构、权限或业务代码，不新增决策笔记。验证覆盖生产引用图、机器启用范围、套餐订阅集合和真实后台列名；未将心跳等同于完整连通性，也未重复进行全线路流量验收。文档门禁、链接和差异检查后按项目规则中文提交并推送 master，再从 GitHub 回读 README/progress-log。面板版本仍为 `20261019-f4f3849`，本轮没有应用构建、部署或 GitHub Release；提交和回读结果列于交付报告。

## 2026-10-21：荷兰与罗马尼亚节点接入

用户要求将荷兰服务器加入四个套餐，随后追加 `friendhosting-罗马`。范围沿用轻量、标准、进阶、旗舰（组 1–4），排除独享（组 5）。复用日本接入的协议、权限与运维决定，原地扩充[已有笔记](./.agents/notes/implemented/architecture/2026-10-21-friendhosting-japan-node.md)，不另建同义决策。

- 两台均为 Ubuntu 24.04.5、x86_64、约 458 MB 内存，原先仅 SSH 3333 与本地 DNS。服务器直连及代理 Cloudflare trace 分别确认 `185.198.165.162 / NL`、`94.131.17.12 / RO`；后者按实际国家标为「罗马尼亚」，机器名保留 `friendhosting-罗马`。
- 荷兰机器 #19、隐藏后端 #355、公开 #356，隧道 `10.79.0.19/32`；罗马尼亚机器 #20、隐藏后端 #357、公开 #358，隧道 `10.79.0.20/32`。公开节点仍用 `hk.taige.us:443`，两层权限均仅字符串组 1–4、倍率 1，不创建独享出口池记录。
- 复用已验 SHA256 `28662b4803bf5cbf3db9079b6fe24921f43b1ebb06e64ec187de6a85e548a4f0` 的原生节点二进制，非 root systemd、Go 软内存目标 128 MiB、MemoryMax 256 MiB。两台 SSH 3333 及原登录方式保留；默认路由不变。31443 仅入口隧道/回环可达，UDP 51872 仅入口源 IP；inet 规则同时覆盖 IPv4/IPv6。
- 入口逐项保存旧 WireGuard、专属防火墙、Nginx 路由和监控配置，语法检查后原子加载规则、reload Nginx；没有重启入口业务服务。入口新增两个 peer，质量探针加入预期出口，采集器同步映射。面板使用 SQLite VACUUM INTO 一致备份，未整库覆盖。
- 两台分别在隐藏阶段通过三名有效普通账号的 ipify / gstatic / Cloudflare HTTPS 与 UDP DNS（共 18 次 HTTPS、6 次 UDP）；独享及随机无效 UUID 的 4 次请求均拒绝，下发用户查询不含独享账号。美国、香港、CF、日本线路出口抽查成功，罗马尼亚验收额外检查荷兰出口成功。
- 通过后逐台公开。Clash Meta / Shadowrocket 的五组订阅共 20 项检查确认仅组 1–4 含对应节点；四档最终 17/18/19/20 条，独享账号仍只有 #340 / #325。旧节点关键字段与套餐价格、额度、速率、上架状态逐字段对照备份一致。
- 本机使用真实订阅、独立 Mihomo、绑定 en0、固定入口 IP 并保留正确 SNI，无直连回退：荷兰 4/6 次 HTTPS 成功；罗马尼亚 5/6 次 HTTPS 成功。测试配置随临时目录删除；未以心跳或延迟替代实际流量验证。后台节点管理页回读确认新机器在线、公开开关已开启且仅显示四档普通套餐。
- NAS 真实回报：荷兰 degraded（采样 1792590186），cloudflare 200/3099.63 ms、google 0/5001.33 ms (timeout)，出口 185.198.165.162；256 KiB upload 0.588 Mbps、download 0.301 Mbps；罗马尼亚 degraded（采样 1792590196），cloudflare 0/5001.15 ms (timeout)、google 204/3074.17 ms，出口 本轮 trace 超时未返回；256 KiB upload 0.66 Mbps、download 0.393 Mbps。持续样本与请求耗时保留原值，不放宽阈值或强制标绿。20 条完整线路与 16 条入口隧道均已配置；短期结果不能证明大陆各运营商速度或长期稳定。
- 面板主机直连两台公网 IPv4 的 31443 均被阻断；隧道内真实代理正常。服务 active/enabled、受限文件权限与默认路由已检查，NRestarts=0。未执行整机重启、长时间压测或外部 IPv6 连通性验收。

配置位置、受限备份和仅撤回新增条目的步骤见[欧洲节点运维](./docs/zh-CN/installation/europe-nodes.md)。入口 SSH 直连曾出现 banner 超时，改用已授权的面板 SSH 转发完成操作，没有更改认证或防火墙放宽管理入口。

本轮仅生产节点配置及运维文档，面板应用版本仍为 `20261019-f4f3849`。工作流门禁、文档链接与差异检查通过后，以中文 `[skip ci]` 提交推送 master，并按提交从 GitHub 回读 README/progress-log；提交与回读终态列在交付报告。无新应用版本、GitHub Release 或安装包构建；现有交付为 Docker CI。此前未提交的香港入口文档与笔记保留原归属。

## 2026-10-21：FriendHosting 日本节点接入

用户提供一台日本服务器，要求加入各套餐并排除独享套餐。先核对生产套餐与节点授权：轻量、标准、进阶、旗舰分别为组 1–4，独享为组 5；已有美国共享后端包含组 5，不能直接复制其授权。复用现有第一阶段入口与独立 WireGuard peer，原因和备选见[接入决策](./.agents/notes/implemented/architecture/2026-10-21-friendhosting-japan-node.md)。

- 新机为 Ubuntu 24.04、x86_64、1 核、约 458 MB 内存，初始只有 SSH 3333 和本地 DNS，无既有代理服务。直连 Cloudflare trace 返回 `ip=185.39.31.75`、`loc=JP`。
- 生产新增机器 #18 `friendhosting-日本`、隐藏后端 #353、公开节点 #354「日本｜friendhosting｜第一阶段入口」。两条节点记录均只授权组 1–4，倍率 1；不创建 DedicatedExit、不改套餐价格、额度、带宽限制、上架状态或旧节点配置。
- 节点复用已验证原生二进制，SHA256 `28662b4803bf5cbf3db9079b6fe24921f43b1ebb06e64ec187de6a85e548a4f0`。非 root systemd 运行，Go 软内存目标 128 MiB，服务 MemoryMax 256 MiB；配置 root:xboard-node 0640。
- 入口 `hk.taige.us:443` 严格 TLS / WebSocket → `wg-vpn-stage1` → 日本 `10.79.0.18:31443`。新 peer 仅配置 /32，不改默认路由；后端仅接受入口隧道或回环，UDP 51872 仅放行入口 IP。先检查 nft / Nginx 语法，再原子加载专属防火墙表和 reload Nginx；保留 SSH 3333 原认证方式。
- 发布前使用三名现有有效普通账号检查 ipify、日本 Cloudflare trace、gstatic HTTPS，各三项均成功，三项 SOCKS5 UDP ASSOCIATE / XUDP DNS 成功；独享账号与随机无效 UUID 均不能建立代理请求。原美国主线路、香港备用、CF 基础备用各一项出口 IP 检查通过。客户端配置在测试后自动删除，未关闭证书校验或添加直连回退。
- 验收后才将公开节点设为可见。按真实 ServerService 检查四档节点数 `15/16/17/18`，独享订阅仍为原两条；旧节点关键配置及套餐参数逐字段与备份一致。
- 现有 NAS 探针范围扩为 18 条并增加预期日本出口；入口观测映射及采集器 peer 范围扩为 14 条。入口采集器已实际上报 14 peers。NAS 已收到日本首轮样本：256 KiB 上传完成（约 0.765 Mbps），两目标 HTTPS 和下载达到 5 秒超时，出口字段为空；同期部分旧节点也出现相同超时，第二轮 Cloudflare 成功并识别正确日本出口，Google 仍超时；尚不能单独定位根因，不修改探针阈值或强制标绿。
- 补充从本机读取真实 Clash Meta 订阅的日本出站，以独立 Mihomo 固定该节点、绑定 en0、无直连回退进行两轮测试：6 次 HTTPS 中 5 次成功，1 次 Cloudflare TLS 请求失败；两次出口均匹配日本 IP。请求约 1.57–6 秒，确认本地实际可用且有间歇波动，不写成全部稳定。Clash Meta / Shadowrocket 的五组订阅输出共 10 项检查通过，只有组 1–4 包含日本；正式后台回读两层记录均仅四个普通组、机器在线，并已有流量入账。
- 从面板主机直接连接日本公网 IPv4 的 31443 超时，隧道内代理成功，运行态 inet 防火墙规则匹配预期。面板无 IPv6 路由，未完成外部 IPv6 连通性验证；已检查同时覆盖 IPv4/IPv6 的拒绝规则。节点内存约 12 MB、NRestarts=0；未做整机重启验收。
- 面板通过 SQLite VACUUM INTO 留存一致备份及节点/套餐/探针快照；入口保留 Nginx、WireGuard、防火墙和监控配置备份。运维位置及局部撤回方式见[日本节点运维](./docs/zh-CN/installation/japan-node.md)。只回退新增节点及配置，不整库覆盖新订单或用量。

本轮只更新生产节点配置与运维文档，面板应用镜像未升级。项目笔记门禁、文档链接及 diff 检查通过后，以中文提交推送 master，再按提交从 GitHub 回读 README/progress-log；具体提交与回读终态在交付报告中列出。使用 `[skip ci]`，无新应用版本、GitHub Release 或安装包构建；仓库现有应用交付为 Docker CI，没有 GitHub Release/安装包发布流程。此前未提交的香港入口文档与笔记保留原归属。

## 2026-10-21：复核 10/19 Actions 失败通知

用户反馈“10/19 生产部署失败，另有订单队列检查失败通知”。按北京时间 10 月 19 日（UTC 10 月 18 日 16:00 至 19 日 16:00）检索 `nanashiwang/Xboard` Actions，找到一条 Order Queue Checks 和两条 Production Deploy 失败，回读对应日志及后续成功运行。以下时间均为北京时间。

| 失败时间 / 运行 | 实际操作与根因 | 后续证据 |
| --- | --- | --- |
| 15:58，[Order Queue Checks 39219430285](https://github.com/nanashiwang/Xboard/actions/runs/39219430285) | 提交 `e40909d` 的 CI 回归：83 项测试、9 个错误均来自 `AttachOwnedDedicatedExits.php:86`，向不存在的 `storage/app` 写快照时报 `No such file or directory` | `f4f3849` 创建权限 0700 的备份目录并补充干净环境测试；16:05 的[后续 CI](https://github.com/nanashiwang/Xboard/actions/runs/39220235107)为 `OK (84 tests, 460 assertions)` |
| 16:12，[Production Deploy 39221058963](https://github.com/nanashiwang/Xboard/actions/runs/39221058963) | 日志 `OPERATION=preview-owned-dedicated`，不是 deploy；`file_get_contents(/dev/stdin)` 因容器内路径不存在而退出，未进入应用接入 | `aab063c` 将清单输入改为 `php://stdin`；16:19 的[后续运维运行](https://github.com/nanashiwang/Xboard/actions/runs/39221925218) success，最终生产验收亦通过 |
| 16:24，[Production Deploy 39222472708](https://github.com/nanashiwang/Xboard/actions/runs/39222472708) | 日志 `OPERATION=verify-owned-dedicated`；保留订单仍为 status 1，验收断言 `Retained order is still waiting; do not claim it has opened`，当时只有 3 个出口满足健康条件 | 正常探测与 5 分钟重试后，16:28 的[最终验收 39222948840](https://github.com/nanashiwang/Xboard/actions/runs/39222948840) success：订单 status 3、ready=true，200 GB 半年权益、普通账号 13/13 实际代理、固定账号及隔离/备用检查通过 |

[实际部署 39220827392](https://github.com/nanashiwang/Xboard/actions/runs/39220827392)的 `OPERATION=deploy` 于 16:11 成功，日志同时确认容器 Healthy、运行 revision `f4f3849045b7d71f1d2dd4b6e42e73480cbc9c68`。两条失败是在该部署之后的预览/验收。订单最终日志 `updated_at=1792398391` 对应 10 月 19 日 16:26:31；没有强制改健康状态或手动标记开通的必要。既有修复与取舍见[自建固定出口池笔记](./.agents/notes/implemented/feature/2026-10-19-owned-fixed-exit-pool.md)。

[Order Queue Checks](./.github/workflows/order-queue.yml)由 push / pull_request 触发，执行 PHPUnit，并非生产订单队列定时报警；[Production Deploy](./.github/workflows/deploy-production.yml)同时承载 inspect、preview、attach、verify 和 deploy 等操作，阅读通知时应核对 `OPERATION`。旧失败记录继续保留，后续成功不会把旧运行改成绿色；本轮未重跑部署或清除失败记录。

当前只读核验：已有 XTerminal 生产连接中 `docker ps` 显示应用容器 Up 42 hours；`taige.us/api/v1/guest/comm/config` HTTP 200、站内验证码开关仍为 0。首页另一次请求 TLS 握手超时，不能据此判断源站宕机；终端后续窗口不可用，未取得新的订单状态、Horizon 失败数量或镜像 OCI revision，未声称当前队列完整健康。10 月 19 日的最终业务成功以当次日志为证，不能替代今天所有节点与用户的实时验收。

结论是三条历史失败均已有对应修复或后续成功证据；本轮未发现需要重新部署的依据。只新增 README、能力地图和本段诊断记录，保留原香港入口未提交改动；执行工作流结构、文档链接及差异检查后，以中文 `[skip ci]` 文档提交推送 master，并从 GitHub 按提交版本回读 README/progress-log。无应用源码变更，无新版本、镜像构建、GitHub Release 或生产部署；提交与回读结果随交付报告。

## 2026-10-21：按确认关闭站内 Turnstile

用户要求先关 CF 认证，并进一步明确“确认，关闭站内 Turnstile”，授权范围为取消邮箱验证码发送前的人机校验，Cloudflare 其他防护保持现状。

- 本轮 Cloudflare 控制台可访问，补足前一轮未取得的配置证据：Under Attack 和 Bot Fight 均关闭、自定义安全规则为 0/5、速率限制规则为 0/1；浏览器完整性检查开启。最近可见的三条事件为浏览器完整性检查的“阻止”，时间分别为 23:58:01、23:58:28、00:07:36（GMT+8），未据此认定为反馈用户，也未改这些边缘设置。
- 站点管理后台会话已过期，改用已有 XTerminal 生产连接，在运行容器中复用 [admin_setting](./app/Helpers/Functions.php) 与 [Setting](./app/Support/Setting.php) 保存接口，仅执行 `admin_setting(["captcha_enable" => 0])`，同时按既有机制刷新设置缓存。修改前值为 1，类型为 `turnstile`；类型与密钥不变。恢复时将同一开关设回 1 即可，本次没有安排自动恢复。
- 生产持久化回读 `v2_settings.captcha_enable` 为 `"0"`；在运行容器中用空 token 请求调用 [CaptchaService::verify](./app/Services/CaptchaService.php)，结果为 `[true, null]`。该检查未发送验证码邮件或创建账户。
- 主域 `taige.us` 和旧域 `board.taige.us` 的 `/api/v1/guest/comm/config` 均 HTTP 200，`is_captcha=0`、兼容字段 `is_recaptcha=0`，类型仍为 `turnstile`。Chrome 打开主域注册页显示完整表单；DOM 中 Cloudflare 挑战 iframe 与 `.cf-turnstile` 组件数量均为 0，截图留存在本次任务附件。邮箱验证码“发送”入口仍保留。
- 这次关闭的是站内人机验证，未关闭 Cloudflare 浏览器完整性检查、托管防护或 DNS 代理，也未重启服务或发布应用镜像。对方设备上的原循环是否消失尚待其刷新重试；如仍见整页挑战，应继续按该请求的 Ray ID 定位，不能据本次设置生效宣称所有验证问题已解决。

本轮仅提交 README、能力地图与本段运维记录，已有香港入口改动保留。工作流结构、文档链接和差异检查通过后以中文 `[skip ci]` 提交推送 master，并按提交版本从 GitHub 回读 README/progress-log；具体提交和回读终态随交付报告。未变更应用源码或版本号，没有 GitHub Release 或新的镜像部署；生产配置变更已按上述步骤完成验证。

## 2026-10-21：Cloudflare 人机验证循环排查

用户最初描述“网站闪退”，随后明确为“卡在 CF 人机认证不断刷新”，发生于刚才、使用浏览器。检查覆盖北京时间 2026-10-20 深夜至 21 日凌晨；对方未提供完整网址、Ray ID、浏览器版本或网络出口信息，因此本轮无法匹配其具体请求。

- 公共请求：`https://taige.us/`、`https://board.taige.us/` 和主域名 `/api/v1/guest/comm/config` 在带 `Mozilla/5.0` User-Agent 的请求中返回 200；Chrome 能打开主域名登录、注册页面，检查到的站点控制台日志为空，未复现反馈中的循环。这仅是当前检查环境的成功样本。
- 同一公开配置接口使用默认 `Python-urllib/3.9` 时返回 Cloudflare 403，正文 `error code: 1010`；对照 Ray ID 为 `a4d946c2aebd3ccc-LAX`，属于本次检查而非反馈用户。Cloudflare [1010 文档](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)说明其含义为按浏览器特征拒绝；尚未读取站点安全事件，不能据此指定某条规则或认定对方同样命中 1010。
- 生产主机通过已有 XTerminal 连接只读核验：`/root/Xboard` 的应用容器为 Up 32 hours，主页显示 `20261019-f4f3849`；本轮未独立核验镜像 OCI revision、OOM 或完整重启历史。当前 `/var/log/nginx/error.log` 为 0 字节，访问日志抽查时约 11.4 万行，按 HTTP 状态位置统计 5xx 为 3 条；未关联到反馈用户，不能将这些请求视为其失败证据。
- 生产 `storage/logs/laravel-2026-10-20.log` 中 ERROR/CRITICAL 匹配 89 条，89 条均匹配 SQLite `database is locked`。唯一包含 `cloudflare` 的日志在 14:20:31，内容是向 `v2_node_probe_sample` 写入探针结果失败；这里的 Cloudflare 是探测目标，结果中记录 HTTP 200，不是验证码报错。该日志的时间字段未另行核验应用时区；数据库锁的影响范围与成因列为独立待办，不据此解释当前验证循环。
- 公开配置确认 `is_captcha=1`、`captcha_type=turnstile`。现有 [CaptchaService](./app/Services/CaptchaService.php)调用 `siteverify`，失败时返回通用验证码错误，未专门记录失败的 `error-codes`；日志未匹配到 Turnstile/siteverify 不等于验证成功。完整站点挑战页与表单内 Turnstile 组件需依据用户截图区分。
- Cloudflare 控制台本身停在验证页，未读取到站点安全事件；未完成或绕过验证码。源站日志无法代替边缘挑战日志，缺少用户 Ray ID/截图时具体根因仍未定。

后续先取得卡住页面的截图（含地址栏及底部 Ray ID，如有）和浏览器版本，按发生时间匹配 Cloudflare 安全事件；若是表单组件，补看组件错误码与 Turnstile 分析。可让同一浏览器切换手机热点做一次对照，若使用 VPN/代理可临时关闭再试，依据[官方挑战排查说明](https://developers.cloudflare.com/cloudflare-challenges/troubleshooting/challenge-solve-issues/)缩小网络与浏览器范围。本轮未关闭任何站点防护、调整挑战规则、重启服务或修改数据库，未宣称用户已经恢复。

本轮交付仅含 README、能力地图和本段记录，保留原有香港入口文档改动。执行工作流结构检查、Markdown 链接与差异检查后，以中文 `[skip ci]` 文档提交推送 master，并按提交版本回读 GitHub 的 README/progress-log；提交与回读终态随交付报告。本轮没有应用代码变更，不构建业务镜像、不创建新版本或 GitHub Release，也不部署生产。

## 2026-10-19：流量耗尽邮件提醒

用户要求流量用完后也发送一次邮件，并在代码、CI 和镜像完成后明确同意“现在部署并验证”。复用现有 SMTP、用户提醒偏好、邮件日志和 `send_email` 队列，新增独立 `send:traffic-exhausted` 每 5 分钟扫描，保留原每日 11:30 的 80%/到期提醒。默认文案明确“套餐流量已用完”，后台模板接口支持独立读取和定制；不复用已定制的 80% 模板。

- 用量 `u+d >= transfer_enable` 且额度大于 0，站点和个人流量提醒开启、未封禁且有邮箱时纳入；提醒逻辑不修改用户用量、套餐、节点资格或提醒偏好。
- `v2_traffic_exhausted_reminders` 按 `(user_id, reset_count)` 唯一记录；发送成功后标记，缓存清空和次日扫描不会重复发信。数据库原子领取避免重复 worker 同时发送；失败后 15 分钟重试，队列三次失败后扫描仍可补偿。
- Worker 重新检查用量、开关和周期，旧周期任务在重置后作废。现有手动/周期/订单/礼品卡重置递增 `reset_count`，下一周期耗尽可再次提醒。SMTP 与数据库之间崩溃窗口仍可能造成重复，不承诺严格 exactly-once。
- 本地 PHP 8.2.33 容器禁网、SQLite 内存数据库、ArrayTransport：邮件专项 **13 项 / 69 断言**、全套 **108 项 / 652 断言**通过；验证 100% 边界、独立预警、失败重试、重复领取、缓存清空、真实重置、旧任务、偏好和模板权限/定制。`actionlint`、新增只读脚本 PHP 语法、18 项运维测试及项目笔记门禁通过。没有向真实用户发送测试邮件。
- 功能提交 `c00e75355a32a207fbbcfae24002172be08a910f` 已推送 master。[邮件 CI](https://github.com/nanashiwang/Xboard/actions/runs/39194627822)（PHP 8.2.34，13 项 / 69 断言）、[节点探针 CI](https://github.com/nanashiwang/Xboard/actions/runs/39194627823)、[笔记 CI](https://github.com/nanashiwang/Xboard/actions/runs/39194627797)和[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39194627796)全部成功。镜像 `ghcr.io/nanashiwang/xboard:c00e753`，应用显示版本 `20261019-c00e753`；注册表的 linux/amd64 与 linux/arm64 镜像 revision 均为该功能提交，索引 digest `sha256:db737d4257b23b4d8f61e1c4e53c4fb05aa5e965e02efa36e0824f66dd17f55e`。
- [生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39195201349)于北京时间 11:34 完成：新表迁移显示 DONE、容器 Healthy、运行 revision 与功能提交一致。正式后台重新加载显示新版本，邮件模板管理中出现“流量耗尽提醒”，主题和实际预览正确，查看用量链接指向本站。部署沿用原 `xboard:update`，其中 `reset:traffic --force` 只重新计算重置时间，不是清空用户用量。
- 增加 `inspect-mail` 只读运维选项，提交 `b5db215`、`cc48fc1`，均使用 `[skip ci]`，没有重复构建或替换生产镜像。输出只含数量、时间、布尔开关及运行 revision，不包含邮箱、SMTP 配置或原始错误，不调用发送。11:43 的[实际核验](https://github.com/nanashiwang/Xboard/actions/runs/39195993433)成功：运行镜像仍为 `c00e753`，总开关为 true，调度时间新鲜；耗尽账号、符合条件人数、当前周期已发送/待重试及最近 24 小时耗尽邮件成功/失败记录均为 0。配置中的静态 `app.version=1.0.0` 不作为部署版本证据，版本以运行镜像标签和正式后台为准。
- 正式用户管理再次查询原诊断账号，已用 **513.5 MB / 25 GB（约 2%）**，所以当前不触发耗尽提醒；本轮没有为测试而修改额度或个人偏好，未核对这次用量恢复的操作来源。调度和无符合条件用户的结果已验证，真实耗尽邮件的 SMTP 接收/收件箱投递尚未触发，不写作已送达。后台队列运行正常，最近失败明细是部署前已有的专属订单任务，不据此归因为新邮件任务。

取舍与限制见[耗尽提醒决策](./.agents/notes/implemented/bug-fix/2026-10-19-traffic-exhausted-reminder.md)。功能及运维变更只提交本轮文件，其他任务的订单修复与原香港入口改动保留。已按功能提交从 GitHub 回读 README/progress-log 并逐字核对；最终证据以文档提交回填，再按该提交回读。项目没有 GitHub Release/安装包发布流程，本次发布双架构镜像，无 GitHub Release。

## 2026-10-19：流量邮件提醒能力核对

用户提出应在流量耗尽前向用户发邮件，并询问线上是否已有邮件功能。复用已有能力进行只读核对，没有新建邮件服务、发送测试邮件或触发批量提醒。

- 正式后台当前显示版本 `20261019-2b8c615`；系统配置 → 邮件设置已保存 SMTP 主机、端口、发件人及 SSL/TLS，邮件提醒总开关为开启。等待页面异步载入后核验，未把加载中的默认空值/关闭状态当作实际配置；不记录 SMTP 用户名或密码。
- 当前检出与该部署提交的 MailService、SendRemindMail、SendEmailJob、Console Kernel 无差异。`send:remindMail --force` 每天 11:30（应用时区 Asia/Shanghai）运行，先检查 `remind_mail_enable`；用户还必须有 `remind_traffic=true`、未封禁且有邮箱。
- `shouldSendTrafficRemind()` 的候选条件是已用比例至少 80%，但 `remindTrafficIsWarnValue()` 实际只允许 80% ≤ 已用比例 < 100%。一天一次的扫描可能错过整个窗口；已耗尽用户会被实际发送方法跳过。这是从现有实现确认的漏提醒风险，尚无该账号跨过阈值和当日任务运行的时间证据，不能断言这就是唯一漏信原因。
- `remindTraffic()` 在入队前写入 24 小时缓存，`SendEmailJob` 经 `send_email` 队列调用 SMTP、最多三次尝试；`MailService::sendEmail()` 写入 `v2_mail_log`。入队前的缓存会在发送失败后继续抑制当天提醒；命令统计会在方法提前返回后仍增加“邮件数”，因此该统计不是实际发送或送达凭证。
- 现有流量入账作业只更新用量和超额检查集合，没有在跨过 80% 时实时触发 `remindTraffic()`。默认新用户提醒开关来源于 `default_remind_traffic`（代码默认开启），但默认值不等于这个既有账号的实际偏好。
- 本轮未取得该账号提醒字段、生产邮件日志、SMTP 接受回执或收件箱结果，也未验证本次提醒任务实际运行。OS 插件只返回对应 Xboard 主机索引，凭据状态为待安全录入；不据资产索引声称服务器检查完成。没有新增权限、修改用户设置或触发发送。

后续建议复用现有 SMTP/队列，将流量检查改为短周期或用量更新后触发，保留用户退出提醒的选择和去重，并明确处理“直接跨过 80% 到耗尽”及发送失败的重试。不能简单提高当前合并任务的频率，因为到期提醒没有同等去重，可能重复发送。实施前应覆盖阈值边界、并发去重、失败重试、到期提醒和发送日志；恢复额度和邮件机制修复是独立事项。本次只交付能力与缺口核对，没有实施这些改动。

文档变更经过项目笔记门禁、相对链接及 diff 检查，按项目约定提交推送 master，随后按提交从 GitHub 回读 README/progress-log。文档提交使用 `[skip ci]`；没有应用构建、新版本、GitHub Release 或生产部署，提交与回读终态在本轮交付报告中列明。

## 2026-10-19：本机订阅流量耗尽诊断

用户反馈本机已有自有 VPN 订阅，延迟检测正常，但国外网站打不开或一直加载。核对本机 Shadowrocket、实际套接字、即时订阅、正式后台账户和现有用户下发代码；本轮不更改套餐、额度、用户身份、客户端规则或服务器网络。

- 本机运行 Shadowrocket，规则模式、系统 HTTP/HTTPS 代理 `127.0.0.1:1082` 和 TUN 均启用。检查时首页选择的是第三方「美国洛杉矶-2」，同时仍有到自有入口的既存连接；因此没有把当前代理的成功当作自有节点恢复。
- 自有订阅即时显示上传 12.81 GB、下载 12.29 GB、总额度 25 GB、剩余流量 0；正式后台筛选对应账号显示已用 25.1 GB / 25 GB、100.4%，套餐有效至 2027-09-17。页面“正常”状态不表示仍有流量；订阅提示距离下次重置 29 天。记录值按产品原单位和舍入保留，不将其当作精确字节审计。
- 使用已有 Mihomo 内核，在回环 18980–18983 开独立 HTTP 监听，每个监听固定同账号的美国 01、02、香港、CN2；入口固定 `143.203.200.5`，保留正确 SNI、WebSocket 参数、Chrome 指纹与证书校验，绑定 en0，不改变系统代理或 TUN，没有直连回退。
- 2026-10-19 10:43（Asia/Shanghai），Google、gstatic、GitHub、Cloudflare 四个目标各三轮：四条自有线路各 0/12，共 0/48；40 次 TLS 连接断开、8 次 5 秒建连阶段超时。当前 Shadowrocket 第三方节点同组对照 12/12 成功；另一次国内百度与站点请求也成功。每请求总上限 12 秒，未进行大流量测速。
- 新入口 Nginx、WireGuard 均 active，严格 TLS 的 `/healthz` 返回固定健康正文；入口到美国 02 的隧道八包零丢包，平均约 1.69 ms。另一次独立 SSH 补充检查连接失败，没有将未完成的检查列为通过。
- 同账号从入口服务器回环 TLS/WebSocket 经过原美国 02 后端访问 gstatic、Cloudflare，分别约 0.098/0.049 秒 EOF，说明这轮拒绝在绕过本机、DNS 和公网第一段后仍能复现。现有 [ServerService::getAvailableUsers](./app/Services/ServerService.php) 的 `u + d < transfer_enable` 条件会排除该已耗尽账户；[订阅信息](./app/Http/Controllers/V1/Client/ClientController.php)仍能显示节点和剩余提示，所以入口延迟数字与业务失败可以并存。未取得后端逐请求鉴权日志，不把 EOF 本身当作精确拒绝码。

本次结论为账户额度耗尽造成当前不可用；没有证据要求变更 DNS、关闭 TLS 校验或重启服务器。固定入口、小样本 HTTPS、账户资格的分层口径补充到既有[探针决策](./.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)，不新建重复架构方案。流量为何消耗至 25.1 GB、是否存在计费异常未独立对账；先前链路波动也仍需在有效账号下复测。

恢复须按用户决定补充或重置额度、确认节点重新获得有效用户，再刷新订阅并验证真实网站。本轮未改变额度或生产配置，未声称恢复。诊断结束已停止独立内核并删除含凭据的临时配置，保留原 Shadowrocket 选择与网络状态。

交付仅包含本轮 README、能力地图、既有笔记和本段证据；原有未提交香港入口改动继续保留。执行笔记门禁、Markdown 链接和差异检查后使用中文文档提交推送 master，并按该提交从 GitHub 回读 README/progress-log；具体提交与回读终态随交付报告。使用 `[skip ci]` 不构建同一业务镜像；本轮无应用版本、GitHub Release 或生产部署。

## 2026-10-19：第一段入口分层监控

用户要求区分共享第一段导致的慢速与个别出口问题。核对现有 ServerMachine、NAS 探针、实际 Nginx/WireGuard 拓扑后，复用机器资源接口，新增独立入口健康采样与显式节点到隧道映射；保留完整页面展示，不恢复仪表盘卡片或大弹窗。取舍见[入口观测决策](./.agents/notes/implemented/feature/2026-10-19-ingress-observability.md)。

- 入口 HTTPS 验证固定健康响应、TLS 和 HTTP，提供 DNS/TCP/TLS/首字节/总耗时；每共享入口每轮一次，单独统计 24 小时成功率与明细，不影响节点原统计。
- 只读入口采集器复用独立 machine 身份，上报 CPU、内存、物理网卡 bytes/s、Nginx/WireGuard 及每 peer 三包 ICMP / 握手。资源超过 180 秒失效；缺工具与 100% 丢包区分，不把 HTTP 健康或低负载当作带宽上限。
- 本地 PHP 18 项测试 / 106 断言、真实 sing-box 容器 Python 12 项测试通过；页面验证卡片、逐节点对应、内联历史、资源过期及主题/窄屏布局。标准 Docker 本地构建受 Docker Hub metadata 连接超时影响；基于已有相同依赖的 NAS 1.0.2 镜像仅替换脚本构建 1.1.0，通过真实内核回归，完整 Dockerfile 构建及实际 Compose 启动已由 CI 通过。
- 第一段只读实测：Nginx 和 WireGuard 运行，13 条隧道各 3 包无丢包；12 个美国 peer RTT 约 1.1–2.8 ms，香港约 153 ms。仅当前样本，不能代替持续稳定性与容量验证。
- 实施提交 `3f12a1ad071c3f1fa40840f9a440a32b6dce7833` 已推送 `master`；[双架构 Docker 发布](https://github.com/nanashiwang/Xboard/actions/runs/39153500598)、[探针回归](https://github.com/nanashiwang/Xboard/actions/runs/39153500610)、[笔记门禁](https://github.com/nanashiwang/Xboard/actions/runs/39153500591) 均 success。GHCR `3f12a1a` 含 amd64 / arm64，manifest digest 为 `sha256:0644c4dcceede2709df2866d79e05bb217e2ea12d8aa480a7a84bbac5fb0d2e8`。沿用 Docker 发布，无 GitHub Release/安装包流程。
- [生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39154293635) success；Docker OCI revision 已与上述提交精确对齐，后台显示 `20261019-3f12a1a`。操作前在面板 `backups/ingress-monitor-20261019/` 留存受限 SQLite 备份并通过 integrity_check。入口配置创建独立 machine #17，不重绑原节点机器；13 条映射逐条对照真实 Nginx 代理路径与后端地址。
- NAS 已升级 `xboard-node-probe:1.1.0` 并保留 agent/state 与原测速预算；安装脚本 SHA 与本地一致。NAS Compose 2.26.1 不支持 `run --pull never`，首次运行检查退出后改用已载入镜像执行 `docker run` 内核检查，再 `compose up -d --no-build` 成功。旧版本 Compose 的这次失败不影响最终持续上报。
- 入口只读服务 `xboard-ingress-monitor` 已 active/enabled；配置 root:600，服务限制 96 MiB / 10% CPU，五次连续日志 `reported: true`，每轮 13 peer。入口脚本 SHA 与本地一致；未变更业务路由、防火墙、Nginx 或 WireGuard 配置。
- 02:50 现场回读：NAS 1.1.0、17 条检测范围、入口累计 8 次 / 成功 6 次，近 10 分钟机器资源 10 条且新鲜。02:41:48 的入口 HTTPS 记录 8.003 秒超时，而同期 CPU 10.14%、内存 30.8%；成功样本约 585–610 ms。后续异常会继续保留；这些小样本不能证明带宽容量或单独确定慢速根因。
- 正式完整后台已打开入口卡片、13 条隧道映射、4 条未绑定备用及页面内入口历史，历史同时展示真实超时与资源记录；本地补充验证 390px、暗色、数据过期和接口失败保留旧数据并标失效。用户随后确认正式页存在空白；独立文档和接口可用，嵌入文档停在 about:blank。只改 src 赋值与挂载顺序的对照未解决，已撤回。改为父页显式读取同源 HTML、srcdoc 就绪确认及 15 秒失败重试，并从受控 base URL 取 origin 保持主题、配置地址和鉴权兼容；正式候选页面两次刷新、切页及本地停服后重试恢复已通过。最终加载修复提交 `2b8c615c49b81b7d244ae4cf722c3f8650a7176a` 已推送 master。
- 加载修复的[镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39157522746)、[探针测试](https://github.com/nanashiwang/Xboard/actions/runs/39157522778)、[笔记门禁](https://github.com/nanashiwang/Xboard/actions/runs/39157522782) 均 success；GHCR `2b8c615` 已回读 amd64 / arm64，manifest digest `sha256:a4849f4aa7d45631fda025b98604ec0730b4939bf031266d9582c93432653097`。[最终生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39157985712) success，容器实际 revision 为 `2b8c615c49b81b7d244ae4cf722c3f8650a7176a` 且 running；浏览器显示 `20261019-2b8c615`，刷新后完整页面与真实监控恢复。
- 部署后回读 NAS 1.1.0、17 条完整线路、13 条映射隧道；入口累计 17 次 / 成功 11 次，近 10 分钟资源 9 条且新鲜。正式入口历史可打开并返回，用户原标签页已恢复完整监控概览。短期入口样本确有间歇超时，未把当前低 CPU/内存或 ICMP 无丢包写成整条线路稳定。
- 隔离验收容器与临时诊断页面已删除；本机临时 NAS/面板登录凭据、入口配置导出以及传输镜像包已删除。服务器实际采集配置按 root:600 保留，生产备份保留；未清理用户原有 PEM。
- 实施及加载修复提交的 README 与 progress-log 已从 GitHub 按精确 revision 回读一致；最终运维记录以 [skip ci] 单独提交并再次回读，不混入既有香港迁移文档改动。

## 2026-10-17：替换 VPN 第一阶段并加固 SSH

用户指定 `143.203.200.5`、root / 22、既有 `flawless_la_02` 密钥替代第一阶段；另明确允许在原香港入口和面板临时添加运维公钥，并要求结束后删除。执行前核对了既有节点、套餐、父子后端和隧道，保持现有 UUID、公开 ID、权限组与订阅地址。方案取舍见[架构笔记](./.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)，日常维护和回退见[第一阶段运维](./docs/zh-CN/installation/vpn-stage1.md)。

### 已实施与生产证据

- 新机独立密钥登录成功；有效 SSH 配置仅接受 publickey，密码与键盘交互认证关闭，MaxAuthTries=3、LoginGraceTime=30、MaxStartups=10:30:40、X11 关闭。新连接强制密码方式得到 `Permission denied (publickey)`。
- 持久化防火墙默认拒绝输入和转发，放行管理、TLS、ACME、必要 ICMP 和已建立连接；UDP 51872 仅允许 13 个出口。Fail2ban sshd jail 使用 systemd 日志与 nftables；TEST-NET 地址实际封禁、集合存在、解封均通过。SSH、Nginx、防火墙、Fail2ban、WireGuard 服务状态及开机启用通过，限时安全回退已取消。
- 13 个出口通过新的 `wg-vpn-stage1` / `10.79.0.x` 加密路径接入，精确 `/32` 路由不替换默认路由；旧 `wg-xboard` 保留。所有出口节点、防火墙、新隧道正常，原 11 台美国机上的 CPA 与独立 sing-box 服务保持 active。
- 新 IP 切换前和原域名切换后，各完整通过 13 条严格 TLS 的 HTTPS 请求（出口 IP 逐一匹配）、13 条 SOCKS5 UDP ASSOCIATE / XUDP DNS；第二个付费用户首末两条通过，随机无效 UUID 被拒绝。
- 独立面板主机确认 13 台后端的公网 TCP 31443/24443 均不可连接；CF 基础备用线完整 HTTPS 请求返回原自有出口。第三方 outbound 数量为零，Windows 与独享家宽套餐仍维持停用。
- Cloudflare 的 `hk.taige.us` A 记录已从原香港 IP 改为新 IP，保持 DNS only。1.1.1.1 和 8.8.8.8 的 A 查询、面板系统解析及 HTTPS 健康检查均命中新入口；8.8.8.8 TCP 查询确认没有 AAAA 记录。13 条公开名称改为「第一阶段入口」，其他关键字段前后相同。
- 权限组 1–4 可用数为 14/15/16/17；两名现有付费用户各 14 条，14 台启用机器心跳新鲜。
- 安装检查曾发现 nftables 文件缺少换行、Ubuntu 默认 Nginx 的 server_tokens 与新增配置重复，均在 DNS 切换前修正。首次香港代理请求遭遇出口 DNS 瞬时超时，日志定位后重测通过，随后两轮完整验收通过；未据单次失败改变所有节点的 DNS 配置。

- 新入口的 Certbot 模拟续期通过（独立 systemd 任务 Result=success / ExecMainStatus=0），证书有效至 2027-01-09，自动续期定时器 active/enabled；原香港机仅有此证书，旧续期定时器停用，原 Nginx/节点/双隧道继续 active。首次 SSH 承载的 dry-run 因随机等待超过连接超时后出现 Broken pipe，改为服务器独立任务并禁用测试随机等待后通过。

- 原香港入口与面板的临时公钥均已删除，新独立连接确认该钥匙被拒绝；香港临时 SSH 配置已移除，恢复原有认证方式。本机本次临时私钥与三份临时密码文件已删除，用户原有密钥保留。

### 维护和交付边界

原香港机器继续作为香港出口及迁移回退点，旧入口与旧隧道未清退。此前 sing-box 订阅模板的 legacy 格式兼容问题仍为独立待办，本次未改模板，也未声称全部客户端可用；未进行大陆运营商测速、长期观察、整机重启演练或计费对账。

本次仅提交第一阶段迁移的新增运维记录，保留开始时已有的香港入口文档改动及笔记，不混入本次提交。应用源码与版本号未改；仓库没有 GitHub Release/安装包发布流程，本次不创建版本或 Release。文档提交使用 `[skip ci]`，不触发相同业务代码的镜像构建；本地结构/链接检查、提交、推送和 GitHub 回读终态在任务交付时报告。

## 2026-10-17：接入 project-decision-kit v1.0.1

### 项目反馈

用户提供 `nanashiwang/new-api` 的项目能力核对与决策记录工具包，要求修改前复用已有能力，保存方案取舍和验证结果，并要求将反馈、排查、后续行动及验证写入 README.md 和本文件，完成后回读。

### 排查结论

- 业务代码核对基线为 `61919aa`，工作分支是 `master`，远程为 `nanashiwang/Xboard`。已有 Laravel 业务接口、客户端认证/下载、专属出口、支付插件及运维说明，新增需求应先沿[能力地图](./docs/FEATURE_MAP.md)检索。
- 原先无 `docs/FEATURE_MAP.md`、统一笔记校验或本进展文件；已有一篇本地未提交网络方案提案，属于其他任务，原文保留且不纳入本次提交。
- `composer.json` 声明 Laravel ^12.0，README 两处 Laravel 11 旧说明已改为 12。管理前端子模块未在当前检出中展开，本次未进行界面或线上业务验收。
- GitHub API 核实工具包最新版本为 `project-decision-kit-v1.0.1`；Release 提供 ZIP 和 SHA256SUMS.txt，实际下载校验一致。来源及摘要见[安装说明](./docs/AGENT_NOTES.md)。
- Xboard 现有 `Docker Build and Publish` 会在 master 推送时构建 amd64/arm64 镜像；`Production Deploy` 仅手动触发。查询 Xboard Releases 列表为空，仓库没有 GitHub Release/安装包发布工作流。

### 方案取舍与已完成改动

采用工具包原装安装器和独立笔记 CI，保留原有 master 提交、镜像构建、部署规则和未提交提案。README 维护当前摘要，本文件保存逐次证据，能力地图提供检索入口，原有笔记树保存设计约束。

相比仅手工写 README，自动校验可发现结构与链接问题；相比将校验放进 Docker CI，独立流程无需镜像发布权限或业务运行时。代价是新增 Python/Bun 校验环境与文档维护工作。完整备选和边界见[本次接入决策](./.agents/notes/implemented/process/2026-10-17-project-decision-kit.md)。

### 验证结果

- Release ZIP 的 SHA256 与发布校验文件一致。
- 安装前预览无冲突；安装后 `python3 .agents/workflow.py doctor` 和 `python3 .agents/workflow.py verify` 通过：本地共 2 篇笔记，目录、格式、相对链接和归档校验通过。其中本次接入笔记已转为 implemented；另一篇原有提案保持原文与未提交状态。
- 临时目录中的 6 项校验行为检查通过：合法笔记和合法归档被接受；缺少备选方案、失效相对链接、归档内容篡改、托管文件修改均被拒绝。临时样例不写入项目。
- 再次运行安装器 `install --apply --ci` 没有写入，相关文件哈希全部不变；原有提案 SHA256 也与接入前一致。
- 本次文档中的 105 个本地链接目标存在；`git diff --check` 通过。README 与本文件已在本地回读，核对工具版本、能力边界、待办和验证记录一致。
- 暂存快照单独校验通过：只包含本次 1 篇接入笔记，105 个文档链接有效；原有未提交提案未混入。该临时快照不含 Git 元数据，归档历史对比由实际仓库与下述 CI 使用 Git 基线验证。
- 本次没有业务代码变更，不运行 PHP 业务测试或生产请求；管理界面、真实支付和节点连通性没有在本次验收。
- 实施提交 [`015240b`](https://github.com/nanashiwang/Xboard/commit/015240b7849cc19e21d24c6abbcf5d064da79ef8) 已推送至 `origin/master`。
- [Agent Workflow Notes #38975255703](https://github.com/nanashiwang/Xboard/actions/runs/38975255703) 成功：验证 1 篇已提交笔记，使用前一提交 `61919aa` 作为归档比较基线。运行日志提示来源包的 checkout/setup-python Action 使用已弃用的 Node.js 20 声明，runner 强制以 Node.js 24 执行并成功；本次保留来源包版本，后续升级时复核兼容性。
- GitHub Contents API 按实施提交完整回读 `README.md` 和 `progress-log.md`，逐字节与本地文件比对一致；远程 master 当时指向同一提交。结果补记后继续执行最终回读。
- [Docker Build and Publish #38975255672](https://github.com/nanashiwang/Xboard/actions/runs/38975255672) 已成功。GHCR 实际读取确认 `ghcr.io/nanashiwang/xboard:015240b` 包含 linux/amd64 与 linux/arm64，两者 OCI revision 均为 `015240b7849cc19e21d24c6abbcf5d064da79ef8`；清单摘要 `sha256:1e7ae3bc16db8001917f2e32bf06f9a6c254697f350bf25bdca58eb6a0144e57` 与 CI 一致。第一次读取遇到 TLS 握手超时，重试成功。
- 流水线版本步骤输出 `20261016-015240b`，日期来自 runner 的 UTC 时间；本记录日期为北京时间 2026-10-17。该输出不替代镜像内应用版本或生产运行版本验收，镜像交付以已核对的 revision 与摘要识别。

### 后续行动与交付状态

- 本地检查、实施提交、推送、笔记 CI、镜像发布及首次 GitHub 回读已完成。结果补记仅修改 README 与本文件，使用中文文档提交并带 `[skip ci]`，避免重复构建同一业务代码；最终推送后再次按远程 master 回读比对，终态在本次交付回复中报告。
- 后续业务改动按能力地图定位，更新对应记录并执行相关测试；结构检查不能代替支付结算、节点连通、权限或浏览器验收。
- 如需强制合并门禁，应另行配置分支保护；如需 GitHub Release，应先补齐版本来源、标签规范、中文说明和附件发布流程。
- 工具包版本：**v1.0.1**；Xboard 源码版本：本次不手动调整，镜像沿用既有流水线自动生成版本；GitHub Release：本次不创建；生产部署：本次未执行。

## 2026-10-17（晚间）：当前节点上传异常只读排查

### 用户反馈与结论

用户使用本项目节点时发现上传速度似乎为零，要求定位当前网络瓶颈。现场选中 Shadowrocket「美国自建｜01｜香港入口」，VLESS / WebSocket / TLS，系统代理为 127.0.0.1:1082，TUN 为 utun8。主要异常是仍被客户端使用的旧入口链路存在明显丢包、握手延迟及超时；DNS 切换期间缓存和既有长连接使新旧路径并存。

### 现场证据

- 本机 Wi-Fi 网关 20 包全部收到，平均 3.799 ms、最大 15.586 ms；绑定物理网卡并固定真实解析的国内 HTTPS 返回 200，用时 0.045 s。该短测未发现本地链路是主要瓶颈，不代表完整宽带上行容量已验收。
- 初始 Shadowrocket 活跃连接仍指向旧入口 103.24.217.171。当前代理的 1 MiB 下载与 256 KiB 上传在 CONNECT / TLS 阶段超时，上传字节数为零，说明测试没有进入有效上传阶段。
- 旧入口的 Nginx、xboard-node、WireGuard 均 active，负载约 0.27，约 1.4 GiB 内存可用；网卡错误、丢弃计数和当前队列积压均为零，未看到 CPU、内存或本机队列耗尽证据。
- 旧香港入口经 wg-xboard 到美国 01（10.78.0.4）：30 包发送、24 包收到，丢包 20%，平均 223.122 ms。新入口 143.203.200.5 经 wg-vpn-stage1 到同一出口（10.79.0.4）：30 包全部收到，平均 1.664 ms。ICMP 小样本不能单独证明应用吞吐，故另做下述相同身份的完整代理对比。
- 从本机绑定 en0，复用当前节点身份、路径、严格 TLS 校验，通过临时诊断进程分别固定新旧入口；目标均为 Cloudflare 测速端点。256 KiB 随机数据上传：旧入口 0.294 Mbps、传输及应答 7.125 s；新入口 1.695 Mbps、1.237 s，均收到 HTTP 200。256 KiB 下载：旧入口 0.149 Mbps、14.194 s；新入口 0.973 Mbps、2.165 s。该指标包含小请求及返回开销，握手另计，不是满带宽测量，也不能保证长期速度；诊断进程的 TLS 指纹与 Shadowrocket 不同。
- 服务器本地 1 MiB 上传至同一测速端点：旧入口 HTTP 200、约 3.63 Mbps，新入口 HTTP 200、约 55.49 Mbps。它们是服务器到测速站的短测，不能替代用户全链路速度。
- DNS 检查存在分歧：服务器侧 Google / Cloudflare DNS、客户端直连 Google DNS 及本地路由器已返回新地址 143.203.200.5，客户端绑定 en0 查询 223.5.5.5 仍得到旧地址。初期客户端查询结果及连接为旧入口；后期观察到 Shadowrocket 91 条旧入口连接与 17 条新入口连接并存。不能把所有旧连接都归因于某一个 DNS 缓存层。
- 最后通过真实 Shadowrocket 代理连续两次上传 256 KiB：第一次 CONNECT 12 秒超时、上传 0 字节；第二次 HTTP 200、262144 字节，整体耗时 2.935 s，curl 报告约 0.715 Mbps。上传并非始终为零，但恢复仍不稳定。

### 处理范围与后续行动

本次仅诊断及保存项目记录，没有修改 DNS、节点、隧道、防火墙、代理选择或重启生产服务；随机测速数据不含用户文件。已存在的入口迁移文件与其他未提交改动保持原样，不纳入本次记录提交。

下一步先让客户端重新解析入口并重建连接，再确认新请求实际连接 143.203.200.5，复测多次真实上传和下载。若新入口仍不稳定，继续区分用户到新入口的运营商路径与入口到出口的隧道；不能只因健康检查 200 或一次测速成功即报告修复。旧入口退役或切换属于独立运维操作。

### 检查与交付边界

本次只改 README 与本文件，不改业务代码或架构决策。文档回读、相对链接和 `git diff --check` 通过；`python3 .agents/workflow.py verify` 在当前工作区通过，提交快照另行核对。使用中文文档提交并带 `[skip ci]`，不重复构建业务镜像；提交、推送与 GitHub 两文件逐字节回读结果由本次交付回复报告。未运行 PHP 业务测试、未构建或发布新镜像、未部署、未创建新版本。仓库没有 GitHub Release / 安装包发布流程，本次诊断文档不创建 Release。

## 2026-10-17（晚间）：新入口上传下载复测与账号限速核对

### 用户反馈与当前路径

用户要求在重新连接后复测实际上传、下载，并定位速度受限环节。检查窗口为北京时间约 22:09–22:21。Shadowrocket 当前选择「美国自建｜02｜第一阶段入口」，实际出口请求返回 192.220.36.213；初次观察旧入口连接 0、新入口连接 88，末次旧入口仍为 0、新入口 68。因此本轮不能继续用前次旧香港入口丢包解释全部当前问题。

### 实测速率

所有本机吞吐测试均经过正在使用的 Shadowrocket HTTP 代理 127.0.0.1:1082，使用随机上传载荷和 Cloudflare 测速端点；有效样本均收到 HTTP 200 并核对完整字节数。Mbps 按十进制 bit/s 计算，MB/s 为十进制 byte/s；小样本、瞬时波动及连接建立时间会影响结果。

| 测试 | 上传 | 下载 | 口径 |
| --- | --- | --- | --- |
| 本机单连接 | 1.33 / 5.49 Mbps | 4.80 / 5.27 / 5.56 Mbps | 上传每轮 3 MiB、下载每轮 8 MiB，包含握手及请求开销；分别约 0.17–0.69 / 0.60–0.70 MB/s |
| 本机四连接合计 | 3.27 Mbps | 7.43 Mbps | 每连接 2 MiB，按合计字节除整组墙钟时间计算，分别约 0.41 / 0.93 MB/s；此轮与一组服务器侧测试存在重叠，不用于独立推断容量上限 |
| 同账号服务器侧单连接 | 9.92 Mbps | 9.89 Mbps | 在新入口本机经严格 TLS、Nginx、WireGuard、相同美国 02 后端及账号访问同一目标；上传 16 MiB，下载 8 MiB，避开本机到入口公网段，串行独立复测 |

前两轮本机单连接上传的 TLS 建立耗时分别约 7.87 / 1.67 s；仅扣除 TLS 建立时间后约 2.29 / 8.64 Mbps，说明端到端小文件上传还明显受建连延迟影响。该扣除估计不等于持续满带宽。

另一次入口本机直接上传 8 MiB，HTTP 200、约 312.90 Mbps，证明该时刻入口到测速站上行不只 10 Mbps，但不能视为入口套餐带宽或整条代理链路容量。两次请求 16 MiB 下载被测速站返回 HTTP 403，均排除，不把错误响应字节数计为下载速度。首次服务器侧 4/8 MiB 对比与本机多连接测试重叠，最终结论使用上述独立复测和 16 MiB 上传结果。

### 瓶颈证据与限制

- **账号上限已确认。** 管理后台当前订阅对应的用户 1 编辑窗口显示限速 10 Mbps、25 GB 流量及 2027-09-17 到期；与客户端订阅及用量相符。仅查看后取消，未提交设置。`ServerService::getAvailableUsers()` 会把用户 `speed_limit` 下发节点；同账号服务器侧较大样本上传 9.92 Mbps、下载 9.89 Mbps 与该限制吻合。4 MiB 短样本上传一度高于 10 Mbps，不能据短时平均否定账号限速。
- **到新入口公网段仍有重传。** 真实下载期间，在入口采样客户端方向 TCP 443 连接；最大活跃流发送字节增量 10989676、重传字节增量 2512018，比例约 22.86%，最小 RTT 191.301 ms。该比例是重传字节相对发送字节增量，不是 ICMP 丢包率，也不定位到某一家运营商或具体路由跳点；其他后台连接可能同时存在。
- **入口到出口隧道短测健康。** 新入口到美国 02 的 WireGuard 地址 10.79.0.5，30 包全部收到，平均 2.401 ms；本机网关 25 包全部收到，平均 4.206 ms。它们不替代持续大流量、MTU 或裸宽带容量验证。
- **未发现入口资源耗尽。** 入口 CPU 负载约 0.23、可用内存约 1.3 GiB；Nginx 与 WireGuard active，网卡无错误或丢弃、队列无积压。已读 Nginx 主配置、站点及入口路由片段未发现 limit_rate / limit_conn / limit_req 指令；没有据此推断整台机器不存在其他限制。

因此当前存在两层约束：用户级 10 Mbps 是明确的速度上限；本机到入口的延迟、重传及连接开销让实际速度进一步降低。上传为零的故障在本轮有效样本中未再出现，但测试窗口内的成功不能保证长期稳定。没有单独测出运营商宽带上行和美国出口裸带宽的最大容量。

### 后续行动与交付边界

本次未调整账号或套餐限速、未切换节点、未修改 DNS / 隧道 / 防火墙 / Nginx、未重启服务。若用户要求继续提速，先明确是否调整该账号的 10 Mbps 上限，再用同样的分段方法复测；即使提高上限，到新入口的公网重传仍需处理，不能承诺提速倍数。

本次仅更新 README 与本进展记录；原有迁移任务未提交内容保持原样。文档回读、链接、`git diff --check`、工作区和暂存快照的 `python3 .agents/workflow.py verify` 通过后，使用中文文档提交并推送 master，再从 GitHub 按提交版本回读两文件。未运行 PHP 业务测试；使用 `[skip ci]`，不构建新镜像、不部署、不调整版本。仓库没有 GitHub Release / 安装包发布流程，本轮诊断文档不创建 Release；具体提交及回读终态由本次交付回复报告。

## 2026-10-17（晚间）：美国 02 节点稳定性复测

### 用户反馈与采样范围

用户要求实测当前节点稳定性。现场仍选中 Shadowrocket「美国自建｜02｜第一阶段入口」；本轮没有改节点、账号限速、代理规则、DNS、隧道或服务配置。沿用[第一阶段架构](./.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)进行只读对照，没有新的架构取舍。

预采样为北京时间 23:05:48–23:06:42，完成 5 轮；首个超时返回 HTTP 000，记录程序对该格式处理有误而中止。保留这次真实 TLS 超时及其余样本，修正记录程序后于 23:09:13–23:14:20 重新完成 30 轮连续主测（约 307 秒）。两段之间有间隔，不把整段约 9 分钟称为持续采样。下表默认只报告完整主测；前置样本另列，不通过丢弃失败样本提高成功率。

每轮通过当前 HTTP 代理 127.0.0.1:1082 并行请求 Cloudflare trace 与 Google generate_204，并绑定物理接口 en0、固定新入口 IP 直接访问 hk.taige.us/healthz。计划间隔 10 秒，慢请求和穿插的文件传输会延后下一轮；连接超时阈值 8 秒、总请求超时阈值 15 秒。完整主测另穿插 5 组串行 1 MiB 随机上传及下载，核对 HTTP 状态和完整字节数。

### 主测结果

| 探测 | 成功 / 总数 | 成功请求耗时中位数 / P95 / 最大值 | 观察 |
| --- | --- | --- | --- |
| 当前代理 → Cloudflare | 24 / 30 | 2.91 / 6.58 / 7.41 s | 6 次连接阶段超时 |
| 当前代理 → Google | 22 / 30 | 3.59 / 7.08 / 9.00 s | 8 次连接阶段超时 |
| 物理接口 → 新入口健康检查 | 30 / 30 | 1.26 / 3.40 / 8.81 s | 全成功但建连存在明显波动 |
| 当前代理上传 1 MiB | 5 / 5 | 5.01 / 5.37 / 5.37 s | 1.56–2.15 Mbps，约 0.20–0.27 MB/s |
| 当前代理下载 1 MiB | 4 / 5 | 6.24 / 13.35 / 13.35 s | 成功样本 0.63–1.52 Mbps，约 0.08–0.19 MB/s；另一次 TLS 超时、未收到数据 |

海外小请求主测合计 **46/60 成功（76.7%），14/60 超时（23.3%）**，其中 9 次 Proxy CONNECT 超时、5 次 TLS 超时。它们是 8 秒连接阈值下的请求失败率，不是网络丢包率。两类目标各自最多连续 2 轮失败；成功请求仍出现数秒延迟。P95 使用成功样本的 nearest-rank 分位数，超时不混入延迟统计，已单独计入失败率。文件速率包括建连和响应开销，用于短传输稳定性观察，不能当作带宽上限或与前次大文件测速直接等量比较。

加上预采样，Cloudflare 28/35、Google 27/35，海外小请求累计 **55/70 成功、15 次超时**；入口健康检查 35/35，上传 6/6、下载 5/6。另有 3 次独立出口身份核对：首末均返回 192.220.36.213（LAX），中间一次超时，未计入上述小请求分母。9 次连接快照中旧入口连接均为 0，新入口连接为 63–110 条，MacPacketTunnel PID 保持 54493；这些快照不能排除快照之间发生短暂断连。

### 分段对照与归因边界

- **同账号服务器侧对照：36/36 成功。** 在新入口本机建立严格 TLS / WebSocket / VLESS 连接，经相同账号、同一 WireGuard 隧道与美国 02 后端请求相同目标，绕过用户到入口的公网段。Cloudflare 18/18，耗时中位数 0.149 s、最大 1.150 s；Google 18/18，中位数 0.142 s、最大 0.158 s。对照使用临时 Python 诊断客户端，不等同于 Shadowrocket 实现；它支持后半段当时可用，不能单独排除本地客户端问题。仅传输小响应，与本机测试部分重叠，不用于推断吞吐上限。
- **入口到出口隧道：300/300，0% 丢包。** 入口 ping 10.79.0.5 约 5 分钟，RTT 最小 / 平均 / 最大为 0.732 / 1.631 / 25.694 ms。结束时 Nginx、wg-quick@wg-vpn-stage1 均 active，负载 0.06 / 0.10 / 0.09。
- **本地网关：300/300，0% 丢包，但有抖动。** 网关 192.168.5.1 的 RTT 平均 19.785 ms、中位数 3.754 ms、P95 86.095 ms、最大 344.522 ms；39 个样本超过 50 ms、10 个超过 100 ms。因此本地 Wi-Fi / 网关侧也需对照，不能把全部慢请求直接归因跨境线路。该 ICMP 测试与主测只有部分时间重叠。
- **入口 TCP 重传仍存在。** 13 秒采样中，一个活跃 TCP 443 流发送字节增量 390398、重传字节增量 70521，比例 18.06%，最小 RTT 191 ms。该采样未按本机公网源 IP 过滤，可能包含其他后台流量，只作为辅助证据；后续尝试增加源 IP 过滤时 SSH 会话建立失败，没有有效补充样本。重传字节比例不等于包丢失率。

当前连接可用但不稳定，不能称为修复完成。证据将重点收窄到用户本地网络、Shadowrocket 处理以及本机到新入口的公网段；美国 02 后端与入口到出口隧道在这些短测中表现正常，尚未精确区分客户端、Wi-Fi 或运营商路径。前次确认的 10 Mbps 账号上限解释吞吐上限，本次没有重查或修改该设置，不能用它单独解释上述连接阶段超时。

### 后续与交付边界

下一步优先在保持同一节点和测试端点的条件下，用有线连接或手机热点做本机对照；若本地网关变稳而代理仍超时，再比较不同入口或用独立诊断客户端区分 Shadowrocket 与公网路径。当前没有执行网络切换、生产修改、客户端重连或长期监控，也不根据短测承诺全天稳定。

本轮只更新 README 和本记录，保留其他任务的未提交内容。回读、相对链接、`git diff --check`、当前工作区及暂存快照的 `python3 .agents/workflow.py verify` 通过后，中文提交并推送 master，再按该提交从 GitHub 回读两文件核对。未运行业务测试、未构建或部署新镜像；文档提交使用 `[skip ci]`，不更新应用版本或创建 GitHub Release。具体提交、推送与回读终态由交付回复报告。

## 2026-10-18：节点稳定性监控覆盖核对

用户询问用户使用这些节点时如何测量稳定性，以及是否已经存在相关监控。本次核对仓库实现、管理后台实时页面、新入口的运行服务与定时任务，并查看已存在的独立监控页面；未执行配置修改或故障告警发送。现有拓扑继续见[第一阶段运维](./docs/zh-CN/installation/vpn-stage1.md)和[架构笔记](./.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)。

### 已有能力和实际覆盖

- **Xboard 服务器监控正在上报。** 现场后台显示 15 条服务器记录、14 台在线、1 台 Windows 已禁用，承载 17 个后端节点；两页列表均已检查，新入口 143.203.200.5 不在其中。美国 02 服务器详情显示最新心跳、CPU、内存、磁盘、实时收发速率，以及 1h / 6h / 12h / 24h 负载趋势入口。资源数值是当时快照，不代表长期水平。
- **资源历史不是用户访问成功率。** [机器上报控制器](./app/Http/Controllers/V2/Server/MachineController.php)保存 CPU / 内存 / 磁盘 / 可选网络速率历史，并按概率触发清理 24 小时以前的数据；[管理控制器](./app/Http/Controllers/V2/Admin/Server/MachineController.php)提供 1–24 小时查询。未发现这些接口采集每条公开节点的端到端请求失败率、TLS 耗时或文件传输完成率。网络速率是当前使用量，不是用户可获得的最大上下行速度。
- **在线标志存在入口盲区。** [Server 模型](./app/Models/Server.php)以 300 秒内的心跳 / 流量推送判断状态；公开子节点的 last_check_at、last_push_at、在线人数和指标读取 parent_id 对应后端。现场节点管理也显示美国 02 公开节点经 hk.taige.us:443 关联 192.220.36.213:31443 的隐藏后端。因此后端在线不能证明用户到公共入口正常，也不能覆盖 TLS / WebSocket / WireGuard 全路径。
- **掉线通知代码存在，但运行闭环未证实。** [CheckServer](./app/Console/Commands/CheckServer.php)检查非子节点，最后心跳超过 1800 秒时尝试发送管理员 Telegram 通知并清理该缓存；当前仓库 [Kernel](./app/Console/Kernel.php)没有注册 check:server，仓库其他插件、路由及部署文件的定向搜索也未发现调度调用。本轮未检查面板服务器额外 cron 或所有线上插件，未测试 Telegram 送达，不能报告自动告警已启用。
- **专属出口检查不能覆盖当前普通节点。** Kernel 注册了每分钟 dedicated:check；[DedicatedExitHealthService](./app/Services/DedicatedExitHealthService.php)通过专属出口的 SOCKS 服务访问两个出口 IP 查询端点，连续 3 次失败标为异常、连续 2 次成功恢复。其范围是 DedicatedExit 关联节点与 SOCKS 出口，不经过普通用户连接的 VLESS / WebSocket 公共入口，不能作为当前 13 条第一阶段线路的全链路监控。本轮没有调用该可能触发故障迁移的命令，也未验证专属出口线上数据与执行记录。
- **新入口未发现独立 VPN 监控任务。** 143.203.200.5 的运行服务中有 Nginx、Fail2ban、系统日志等；定时器包含 sysstat 系统采样和 certbot 续期。root crontab 无任务，/etc/cron.d 为系统维护和证书项目；对服务、常见程序目录、/opt 与 /etc/cron.d 的监控文件名检查未发现节点探针。没有因这一台机器的检查断言外部平台绝无监控；未核对所有出口机或面板额外定时任务。/healthz 仍仅是入口健康端点，不是持续监控或完整出口验证。
- **已有独立页面属于另一条业务链路。** [Flawless 流量与链路监控](https://meta-api.vip/relay-monitor/)现场显示源机器 155.103.118.155，目标业务服务器 104.168.114.150；每分钟采集资源与流量、每分钟 5 次 ICMP，保留 24 小时细粒度趋势与月流量预估。它不是 143.203.200.5 → 各 VPN 出口的监控，不能用于证明本项目节点稳定。

### 面向用户体验的建议测量方法（尚未部署）

1. 保留现有机器监控，并补齐公共入口、Nginx / TLS 证书、WireGuard 对端的资源与连通状态。它们帮助定位故障，不单独作为“节点可用”依据。
2. 在与用户接近的网络放置探针，至少从当前主要运营商开始，后续按用户分布覆盖电信、联通、移动；另保留一个服务器侧对照。使用专用监控账号逐条连接真实订阅节点，核对实际入口和预期出口，防止备用 / 自动切换掩盖坏节点。不同运营商分别统计，不能以一台海外探针代表全部用户。
3. 可先每 60 秒对每条线路访问两个独立 HTTPS 目标，记录 DNS / 连接 / TLS / 首字节 / 总耗时、超时阶段和 HTTP 状态，核对预期响应；需要 UDP 的线路增加真实 UDP DNS 验证。端点自身异常需交叉核对；按探针所在地和节点统计成功率、P50 / P95、连续失败及恢复时间，并记录“没有采样”，避免将探针失联显示为正常。
4. 每 15–30 分钟轮换少量上下行传输，校验完整字节数；独立记录账号限速、样本大小、握手耗时和流量预算，避免频繁满速测速抢占用户带宽。例：17 条线路、每条每 15 分钟各上传和下载 1 MiB，一台探针仅载荷就约 3.19 GiB/天，不能占用普通用户 25 GB 套餐后再误报节点故障。容量测速与日常存活探测分别运行。
5. 可将连续 3 轮失败作为初始故障触发、连续 2 轮成功作为恢复触发，并另报持续高延迟和低成功率；阈值应按基线、端点超时和误报情况校准。先验证故障、恢复、去重与告警送达，再称为监控上线。保存 24 小时细粒度记录和 7 / 30 天汇总，报告每个节点在不同网络上的可用性。

上述是供后续实施的测量建议，没有创建探针、购买机器、开通通知或修改生产配置。此前美国 02 本机 60 次请求中 14 次超时，而服务器侧 36 次全成功，正说明仅查看后端在线和服务器内探测会遗漏用户到入口这一段；该数字是 2026-10-17 晚间的历史测试，不作为本轮即时测速。

### 记录与交付

本次仅同步 README、能力地图和本记录，保留已有未提交工作。提交前回读新增内容、验证相对链接与锚点、执行 git diff --check，并在工作区和暂存快照运行 python3 .agents/workflow.py verify；中文提交推送 master 后按提交版本从 GitHub 回读 README 和 progress-log。未运行业务测试、未部署或修改版本，文档提交使用 [skip ci]，不创建 GitHub Release；最终提交与回读状态由交付回复报告。

## 2026-10-18：Xboard 节点质量探针实施

### 用户反馈与方案

用户要求本项目增加检测探针，并明确与此前其他监控项目无关；首个位置指定家庭 NAS。保留公开节点、权限组和原机器心跳，新建属于 Xboard 的管理页面、外部探针 API 与独立容器。既有能力核对与取舍见[决策笔记](./.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)。

探针沿指定节点执行两个严格 TLS HTTPS 请求，上传/下载需收到正确 HTTP 响应并完成指定字节。每轮结束等待 60 秒、每 30 分钟每节点各传输 256 KiB，最多并发 4 节点；重启保留测速间隔。单节点出站无 direct/selector 回退。面板显示成功率、平均/P95 耗时、上下行完成率及小样本速率、出口 IP、状态事件。入口字段是配置值，不能替代实际连接目标 IP 的证据。

API 使用独立令牌，数据库仅存哈希；禁用和轮换撤销旧访问，越界节点拒绝，重复/旧采样不改变统计。缺测、账号失效和内核不兼容独立标识；页面刷新失败时旧数据标为过期。24 小时明细、30 天小时统计通过原调度器清理。提供私有配置文件的 CLI，可创建独立非管理员监控账号（30 GiB 总量、365 天、100 Mbps），不修改日常账号、余额或套餐。告警目前是面板内事件，没有发送邮件/Telegram。

### 验证与安装阶段

- 本地 PHP 完整回归 87 项、464 条断言通过，其中探针 12 项、64 条断言；Python 探针 6 项通过，含实际 sing-box 启动、坏代理不回退直连、上传响应和字节校验、下载实际长度、跨重启测速预算。
- 本地浏览器通过原后台登录并进入新页面，核对匿名边界、空态、接口断开时保留旧数据并标记过期、明细 P95、失败/恢复记录和 390px 宽度；暗色使用同一组 CSS 变量单独验收。浏览器验收使用隔离 SQLite 与明确标记的测试数据，不是生产采样。
- NAS 使用 `/home/nanashiwang/xboard-node-probe` 独立目录；Docker 可由现有用户执行。直接拉取 GHCR 返回 EOF 后，在本机构建 linux/amd64 镜像、传到 NAS 导入，并实际运行 sing-box 1.14.3 版本检查。没有改动其他容器、系统代理、TUN 或主机路由。
- 容器根目录只读、无主机端口、去除 capabilities，设置资源上限和日志轮转。NAS 目录/镜像准备完成不等于接入成功；正式面板 API、独立账号配置及持续真实样本尚待上线验收。

### 提交与后续

本轮新增 `Node Probe Checks` CI 并沿用现有双架构镜像发布；保留原有香港入口任务脏改动，按本轮文件/文档段落单独暂存。提交前执行业务测试、语法检查、笔记验证、文档链接和 diff 检查；推送后按提交从 GitHub 回读 README 与本文件，并核对 CI 和镜像 revision。该仓库没有 GitHub Release/安装包发布流程，不新造版本发布。

本记录是实施提交时的状态：提交、CI、镜像发布和生产部署分别核验。后续持续运行需关注监控账号剩余额度、NAS 供电和网络；单点结果不能代表所有用户，短期全部成功不等于长期稳定。

### 后台看板集成与复核

用户进一步明确监控应直接放进 Xboard 管理员后台看板。首页现有看板中增加节点质量卡片，按探针位置显示通信状态、异常及待确认数量、HTTP 成功率、账号限速与剩余额度、各节点最近上下行速率。侧栏增加节点质量入口，节点历史、探针管理在后台内部对话框打开，NAS 只运行采集容器。

前端子模块为固定版本的编译产物；本仓库维护的扩展卡片挂载到该版本已有看板容器，不改写上游编译文件或 React 管理的子元素。更新管理端子模块时必须复验首页挂载、路由切换、深浅主题和明细对话框。管理 API 拒绝访问时停止重新挂载，避免循环请求。

复核补充：上传/下载失败状态必须等待传输复测成功，轻量请求成功不清除传输故障；新增回归后本地完整测试为 88 项 / 471 条断言，探针专项为 13 项 / 71 条断言。后台首页已在原管理端内验收：侧栏入口、节点直达历史、深色主题、390px 宽度以及切页返回后单一卡片均通过。首次实施提交 fdfa528 的探针 CI、笔记 CI 和双架构镜像发布已成功，后续看板集成仍以新提交构建结果为准。

### 看板交付与上线边界

- 功能提交 `fdfa528`、后台首页集成提交 `6e8d35d` 均已推送 `master`；README 与本记录已经按后者完整 SHA 从 GitHub 回读核对。
- `6e8d35d` 的 [Node Probe Checks](https://github.com/nanashiwang/Xboard/actions/runs/39057540278)、[Agent Workflow Notes](https://github.com/nanashiwang/Xboard/actions/runs/39057540263)、[双架构镜像构建发布](https://github.com/nanashiwang/Xboard/actions/runs/39057540268) 均成功。构建版本 `20261017-6e8d35d`（CI 使用 UTC 日期）；GHCR manifest `sha256:ff6228380caaa0904c57197ccec37c0a86b08c30f8b4dc361053dce1944853df` 已回读确认 linux/amd64 与 linux/arm64。未创建 GitHub Release，仓库当前以镜像发布。
- 补充浏览器验收：撤销本地测试账号管理员资格后，看板移除、监控请求被拒绝，观察期间仅发起一次请求，没有重新挂载循环；测试资格随后恢复。
- NAS 源码、Compose 与 linux/amd64 镜像已经同步；镜像内非 root 用户和 sing-box 1.14.3 实际运行通过，NAS 直连正式面板 HTTPS 返回 200。尚未放入正式探针令牌，也未启动常驻采集。
- [生产只读检查](https://github.com/nanashiwang/Xboard/actions/runs/39057851426) 成功，原面板容器运行正常；未触发 deploy。生产上线与通过浏览器创建持续访问凭据的确认已提交给用户，仍待回复。因此当前截图、上下行数值和状态事件属于隔离验收数据，不能作为生产监控已上线的证据。

## 2026-10-18：正式后台上线与 NAS 接入

用户确认上线并接入 NAS 后，创建独立监控账号 #33，非管理员/非员工、零余额、100 Mbps、30 GiB 总额度、到期 2027-10-18，保留旗舰权限组覆盖 17 个公开节点，但不绑定计费套餐。后台注册探针 #1 `nas`，位置为家庭网络 / NAS；没有修改现有用户、公开节点或路由。

[镜像构建 39058542973](https://github.com/nanashiwang/Xboard/actions/runs/39058542973) 与 [生产部署 39058983706](https://github.com/nanashiwang/Xboard/actions/runs/39058983706) 均成功。生产运行 revision 为 `12d17288e853735ae6d5b27651a6d438ecb60517`，与获确认的 `6e8d35d` 相比仅追加交付文档，应用代码相同。新增探针迁移执行 DONE，原面板容器启动 Healthy，正式浏览器已显示首页监控卡片、侧栏入口及同源明细。

NAS 接入实测发现两个安装问题：Compose 的 tmpfs 流式数组未引用含逗号的值，Docker 将 `mode=1777` 误当成另一个挂载路径；默认 Python User-Agent 又被站点 Cloudflare 返回 1010，未到达应用。探针 1.0.1 修正挂载字符串，并明确使用 `Xboard-Node-Probe/1.0.1` 客户端标识；同一 API 随即返回全部 17 条配置，无须修改站点防护、代理、TLS 或节点。新增客户端标识回归及实际 Compose 启动 CI，容器内 7 项测试通过。关联取舍与运维边界见[原决策笔记](./.agents/notes/implemented/feature/2026-10-18-node-quality-probes.md)。

NAS 当前使用 `/home/nanashiwang/xboard-node-probe`，镜像 1.0.1、重启策略 unless-stopped、私有配置 0600、非 root 运行。首批真实结果已进入正式后台，具体多轮成功率、传输样本与 CI 结果在验收完成后补记。单个位置、小载荷及短时数据不能代表全体用户或带宽容量。

连续实测中出现部分上报失败，探针 1.0.2 对网络错误、429 和 5xx 最多重试一次，保持同一采样 UUID，依靠服务端幂等避免重复统计；401/403 不重试。日志只补充错误类型和 HTTP 状态，不输出凭据或远端响应。容器内 8 项回归通过，NAS 已升级并保留原测速间隔状态。

### 生产验收结果（北京时间 2026-10-18 02:53–03:00）

- 探针 1.0.2 前三个完整轮次（02:53:46–02:57:00）覆盖 17 条线路、51 次节点采样，102 次 HTTPS 请求中 92 次成功（90.20%），上报未报错；短时样本仍有波动，不能据此承诺长期稳定或代表其他运营商。
- 后台回读全部 17 条线路的最近传输样本：上传完成 16/17，下载完成 14/17。美国 01 上下行超时，美国 02 与进阶 CF 备用下载超时；记录保留原测量时间，轻量检查成功未清除这些传输故障。标准 CF 备用因首轮上报未确认，现场补测一组 256 KiB 上下行并成功入库，额外载荷仅 512 KiB。
- 已在正式管理首页核对在线状态、异常节点及上下行结果，并从美国 01 打开真实超时、P95 和小时统计。界面显示探针 1.0.2，账号剩余约 29.99 GiB；账号额度与有效期需持续维护，系统不自动续额。
- NAS 运行代码 SHA-256 `4f92e0959d5dcc92d9e092d128445dee5df9d83f673cbf3b9a4c8ab3653187eb` 与本次源码一致，UID/GID 1000、只读根目录、无发布端口、capabilities 全部移除、unless-stopped，配置 0600。检查时无重启/无 OOM、空闲内存约 15.32 MiB；升级后保留测速间隔，前三轮未重复传输。
- NAS 发起的无凭据 agent 请求返回 401、无管理员凭据的管理请求返回 403。未关闭 Cloudflare、防火墙或 TLS 校验，未调整原有节点、套餐或客户路由。
- 修复提交 `07b5a42`、`b3915dc` 已推送 master。`b3915dc` 的 [探针检查](https://github.com/nanashiwang/Xboard/actions/runs/39060125709)（含实际 Compose 启动）、[决策笔记检查](https://github.com/nanashiwang/Xboard/actions/runs/39060125677)、[双架构镜像发布](https://github.com/nanashiwang/Xboard/actions/runs/39060125711) 均成功；GHCR manifest `sha256:32674d341a42825590138afa78ebdf038139e8916fbe83af108450dcfa7360c2` 已确认 amd64/arm64。生产面板仍为 `12d1728`，后续提交只涉及 NAS 探针、检查及文档，面板应用代码一致，未为此再次重启。
- 原有香港入口任务的未提交内容继续保留；本轮只暂存自身文件与记录段落。README 和 progress-log 按提交完整 SHA 从 GitHub 回读核对；当前仓库采用 Docker 镜像发布，无 GitHub Release/安装包流程。

## 2026-10-18：安卓 Clash Meta 下载等待日志排查

### 用户反馈与确认事实

用户使用 Android Clash Meta，Google Play 下载一直等待且速度为零；Google / YouTube 页面能打开，视频不能播放。用户反馈规则和全局模式均失败，按建议尝试 CN2 也未恢复。本次分析用户提供的约 31 秒日志（03:31:25–03:31:56），不提交原始设备日志、订阅或身份凭据。

- 136 行日志共有 41 条 Warning：38 条针对 `services.googleapis.cn:443`，匹配 `DomainSuffix/cn` 后使用 `DIRECT`，错误为 `no ip address` 或 `dns resolve failed: couldn't find ip`。
- 默认 [Clash 模板](./resources/rules/default.clash.yaml) 中 `DOMAIN-SUFFIX,cn,DIRECT` 位于 `DOMAIN-KEYWORD,google,$app_name` 前，Google 的 `.cn` 域名被通用直连规则提前匹配；模板虽配置 `+.googleapis.cn` 的 DNS 策略，但 DNS 策略不等于连接分流规则，也不能据配置文本认定手机能访问该解析器。
- 新入口服务器的系统解析、Google DoH 和 Cloudflare DoH 对 `services.googleapis.cn` 均返回有效 A 记录，两个 DoH 状态均为 0；支持手机所用解析路径存在异常，不支持该域名全球无记录的判断。尚未取得手机完整生效 DNS 配置，不能精确归因某个解析器。
- 其余 3 条 Warning：访问 `connectivitycheck.gstatic.com` 时连接 `hk.taige.us:443` 超时 1 次；访问 NTP 时建立 VLESS UDP 客户端超时 2 次。UDP 错误发生于客户端建立阶段，不能直接认定 QUIC 或 UDP 转发不支持。
- 日志中的代理成功建连记录均显示「美国自建｜01｜第一阶段入口」，并有多条实际规则匹配；没有 GLOBAL / CN2 记录。本文件不能验证用户此前另一轮全局 / CN2 测试的执行状态，也不否定其反馈。
- 本片段没有 `googlevideo`、`gvt1` 或 `gvt2` 请求，无法确认视频和应用包下载连接具体卡在哪一环。广告域名的 REJECT 命中不单独作为下载失败证据。

### 同期独立对照

新入口 Nginx、防火墙、WireGuard 为 active，13 个对端最近握手均在约 126 秒内；服务状态不代替客户端验收。正式 NAS 看板 03:24 左右显示最近统计 664/734 次 HTTP 成功（约 90.5%），部分节点波动；该位置与手机网络不等同。

本机绑定 en0、固定新入口 IP、严格 TLS，通过临时 VLESS / WebSocket 诊断客户端分别走美国 02 与 CN2：两条线路各从 `dl.google.com` 返回 HTTP 206 和完整 262144 字节，用时约 2.16 / 2.18 秒；美国 02 的 Cloudflare 256 KiB 下载返回 HTTP 200 且完整，约 2.29 秒；CN2 同一 Cloudflare 测试建连约 12.20 秒超时。临时诊断不改变系统代理或节点配置，测试数据只在内存中接收。以上支持下载链路并非全断，但不等于手机、Google Play 应用包或视频 CDN 已恢复，也不证明持续带宽容量。

### 修复方向与交付边界

先修正 Google `.cn` 域名相对于通用 `.cn` 直连的优先级，并核对实际下发模板和手机 DNS 解析器的可达性；规则修正本身不能替代 DNS 及入口稳定性验证。随后重新导入 / 更新订阅，核对实际模式与节点，采集一次真正的视频播放 / Play 下载请求，以域名、命中策略、节点及错误阶段验收。沿用[入口架构](./.agents/notes/implemented/architecture/2026-10-17-stage1-replacement.md)，本次没有新的架构决策。

本轮仅保存诊断摘要，不修改业务代码、线上订阅模板、DNS、节点或防火墙，不声称已修复。README 与本记录进行本地回读、相对链接和工作区 / 暂存快照校验；仅提交本轮记录并推送 master，原有迁移文档改动保留，推送后从 GitHub 按提交回读两文件。文档提交使用 `[skip ci]`，不运行业务构建、部署或版本发布；仓库无 GitHub Release / 安装包流程，本次不创建版本。最终检查、commit、push 和回读结果由交付回复报告。

## 2026-10-18：Clash Meta Google 分流与代理 DNS 修复

用户授权修改正式订阅模板。线上后台回读确认原 Clash Meta 内容与仓库共享默认模板一致，备份后只更新 Clash Meta；未改变节点身份、权限、TLS 校验或服务端路由。决策见[修复笔记](./.agents/notes/implemented/bug-fix/2026-10-18-clashmeta-google-dns.md)。

### 变更与取舍

- 新增独立 [default.clashmeta.yaml](./resources/rules/default.clashmeta.yaml)，新安装的种子数据使用该文件；保留 custom.clashmeta / custom.clash 优先级，已有数据库模板不自动覆盖，原 Clash / Stash 默认文件不改。
- Google API、视频与下载域名置于宽泛中国直连规则前；境外 nameserver-policy 与 fallback 使用 Cloudflare / Google 两个 HTTPS DNS，通过 `$app_name` 策略组查询。节点域名使用独立国内 DoH，避免依赖尚未建立的代理。
- 已有站点通过后台订阅模板编辑器保存，刷新回读内容与候选一致（编辑器省略末尾换行）；重新下载订阅确认 DNS 占位符已替换为真实组名，规则优先级生效。前后 17 个代理定义及全部策略组内容一致。

### 验证结果与限制

- PHP 8.2 容器执行 ClashMetaTemplateTest 与 SubscriptionNamesTest：10 测试、129 断言通过；覆盖新安装模板、实际协议序列化、国内直连、Google 规则以及自定义模板与其他客户端保留。
- 官方 Mihomo 1.18.10 / 1.19.32 检查候选和实际下发订阅均通过。首次测试因本地缺少 GeoIP 数据库且自动下载超时，补齐官方数据库后重验；保留 GEOIP 规则。
- 真实内核绑定本机 en0、严格 TLS：services.googleapis.cn 与 redirector.gvt1.com 解析状态 0 并返回 A 记录；内核日志明确境外 DoH 经代理组，services.googleapis.cn 命中 googleapis.cn 代理规则。
- 实际订阅首次完整请求发生一次 hk.taige.us 建连超时；后续独立查询确认入口域名返回当前 IP。以每请求新建 HTTP 会话的方式再测美国 02 / CN2：Google 根路径均取得 HTTP 404（只验证 TLS/HTTP 可达），dl.google.com 均返回 HTTP 206 与完整 262144 字节，约 1.92 / 1.96 秒；YouTube generate_204 均返回 204，约 1.21 / 1.22 秒。测试只调整本地监听端口和网络接口，未更改系统代理。
- 用户在安卓手机更新订阅并重连后明确反馈「下载和视频都恢复」，手机 Play 下载与 YouTube 播放验收通过；间歇入口超时未据此宣称永久消失。未测速持续带宽，未重启或升级面板/节点。

### 交付状态

本地回读、差异、工作区及暂存快照决策流程检查通过；代码提交 `db666f5` 已推送 `master`，只包含本轮修改，既有香港迁移工作区改动保留。GitHub [Docker 构建](https://github.com/nanashiwang/Xboard/actions/runs/39066084418)、[探针检查](https://github.com/nanashiwang/Xboard/actions/runs/39066084422)、[笔记检查](https://github.com/nanashiwang/Xboard/actions/runs/39066084478) 均为 success。发布镜像 `ghcr.io/nanashiwang/xboard:db666f5` 已核实含 linux/amd64 与 linux/arm64；工作流按 UTC 生成应用版本 `20261017-db666f5`。

线上模板独立保存生效并经手机验收，面板程序仍为 `20261018-12d1728`，未因镜像构建完成而部署程序或重启节点。README / progress-log 已按代码提交从 GitHub 回读，字节一致；本次手机验收和构建交付记录以 `[skip ci]` 文档提交同步，推送后再次按提交回读。仓库没有 GitHub Release / 安装包发布流程，本次无 Release 链接。

## 2026-10-18：节点质量改为后台完整页面

用户反馈仪表盘监控与侧栏节点质量重复，并要求取消大弹窗，采用与其他后台页面一致的展示。移除首页监控卡片与其轮询入口，保留侧栏「节点质量」，在现有后台主内容区展示探针和节点表；节点历史也改为页面内查看并提供返回列表。探针 API、权限、统计口径、采样与 NAS 运行配置不变。取舍见[页面简化决策](./.agents/notes/implemented/simplification/2026-10-18-node-quality-page.md)。

- 兼容固定版本管理前端的首页查询路由 `#/?page=node-quality`；旧 `#node-quality` 自动转向新入口。未改编译子模块，保留侧栏、主题、登录和其他菜单。
- 本地使用现有后台编译资源、隔离 SQLite 测试数据与 Docker PHP 环境验收：无重复卡片；完整页面及侧栏高亮；刷新、前进后退、系统配置往返、旧入口、历史返回、深浅主题、390px 窄屏通过；窄屏选择后菜单自动收起。退出测试账号后监控视图与入口均清除。测试数据不作为生产节点质量结论。
- 相关 PHP 回归通过：13 项测试、71 个断言；两份 JavaScript 语法检查、差异空白检查通过。笔记校验与 145 个本地文档链接检查通过，只暂存本次改动，保留原有香港迁移工作区文件。
- 本地精简测试库的原仪表盘统计接口出现错误提示；本次监控接口和页面加载成功。正式环境随后实际验证收入、流量、队列与节点数据正常读取，未复现本地统计提示。
- 代码提交 `586bcb0` 与长列表修正 `f09a440` 均已推送 `origin/master`；沿用双架构镜像和 Production Deploy 流程。仓库没有 GitHub Release / 安装包发布流程，本次不创建 GitHub Release。

- 首次正式部署 `586bcb0` 成功，线上收入和队列统计正常，17 条节点可读取；长列表验收发现页面根滚动问题，补充视口高度和内容区滚动边界，并在本地扩展为 17 条样本验证。历史返回改为等待 iframe 高度恢复后还原列表位置，窄屏复验通过；修正后的镜像及终态另行回读。

### 最终构建、部署与浏览器验收

- `f09a44031e6ace0c413717efa1d53917ea5515ec` 的[镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39068604903)、[探针检查](https://github.com/nanashiwang/Xboard/actions/runs/39068604928)、[笔记检查](https://github.com/nanashiwang/Xboard/actions/runs/39068604936)全部 success；实际镜像 `ghcr.io/nanashiwang/xboard:f09a440` 含 linux/amd64 和 linux/arm64。
- [生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39068922642) success；日志显示无待执行迁移、容器 Healthy，运行 revision 与上述提交一致。部署切换期间一次浏览器刷新遇到 502，部署后再次刷新恢复；最终页面和数据验证通过。构建版本按 runner UTC 为 `20261017-f09a440`，实际后台显示缓存版本 `20261018-f09a440`，以完整 revision 对齐。
- 正式浏览器确认仪表盘只显示原有收入、流量和队列统计；侧栏「节点质量」在后台主内容区展示，无外层或历史弹窗。NAS 探针在线，17 个节点明细入口均存在，保留真实成功率、延迟和分开的上下行检测结果；不是重新判定线路稳定性。
- 完整列表只在内容区滚动，页面标题与侧栏保持稳定；进入美国 07 历史读取 P95、状态变化和采样记录成功，返回恢复列表位置。390px 窄屏、深浅主题、登录边界、刷新和导航往返在本地真实后台壳验证；正式环境核验桌面真实数据与历史。
- README 与 progress-log 已按两个代码提交从 GitHub 回读且逐字节一致。最终验收记录使用中文 `[skip ci]` 文档提交，推送后再次回读；不重复构建同一业务代码，不将文档提交号当作生产 revision。

## 2026-10-19：自建线路接入固定出口池

用户明确选择保留固定出口分配，将现有自建节点接入出口池；每出口最多五个固定套餐账号。专属套餐与权限组均为 ID 5，原关联节点为 0；200 GB、10 Mbps、价格和总销售上限 15 保持不变。

[生产只读检查](https://github.com/nanashiwang/Xboard/actions/runs/39218295435)成功：旧五出口均停用、无分配，1 笔订单处理中；13 个去重的美国自建出口可作为池来源，香港保留公共备用。数据库显示套餐 show=false、sell=0，后续以数据库实值为准，不沿用页面开关的旧解释。NAS 探针存在，原 expected_exits 为空；接入时补齐匹配的预期 IP，不伪造健康。

实现新增共享后端引用及专属订阅别名，不改变原公共节点专属标记；全量和增量同步都按分配限制专属账号，普通用户权限保留。健康只计不同时间的监控观测，过期、错 IP、停用或路径漂移失败；现有预留、五名额和保留订单重试继续复用。配置预览/应用核对运行镜像提交，写入前备份。

PHP 8.2.33 下专属、订单支付、队列分页及探针共 84 项测试、460 个断言通过；actionlint 与运维验收脚本语法检查通过。构建、生产配置及真实代理验收待执行；尚未宣称出口恢复或订单完成。方案取舍见[接入决策](./.agents/notes/implemented/feature/2026-10-19-owned-fixed-exit-pool.md)。

首次专项 CI 在干净 checkout 中发现 storage/app 不存在，已修正为创建 0700 备份目录后再写 0600 快照，并新增干净安装回归；首个失败构建对应代码不部署。代码初版 e40909d 已推送，README / progress-log 已从 GitHub 按该提交回读一致；修正版 CI 与镜像仍待验证。

修正版 `f4f3849` 的专项 CI 和[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39220235334)成功，[生产部署](https://github.com/nanashiwang/Xboard/actions/runs/39220827392)成功。镜像 manifest 为 `sha256:ae7d006c5abd864beb7f07ac18f5423e3482974ed2357396483635603f787eb2`，README / progress-log 已按该提交从 GitHub 回读一致。[接入前基线](https://github.com/nanashiwang/Xboard/actions/runs/39219450300)确认普通账号对 13 个后端均获授权，13 次实际 HTTPS 请求均返回预期 IP。首次配置预览因容器缺少 /dev/stdin 失败，未写入配置；部署流程改用 PHP 原生 php://stdin，仍需重新预览后应用。

输入流修复 `aab063c` 经容器实读清单和 actionlint 通过；两份记录已从 GitHub 按提交回读。[重新预览](https://github.com/nanashiwang/Xboard/actions/runs/39221925218)与[正式接入](https://github.com/nanashiwang/Xboard/actions/runs/39221991414)成功，私有权限快照已保存。应用前后对比：原 34 条记录均保留原权限，新增 13 条固定订阅别名，13 个去重美国出口写入池，套餐配置完全一致；后台权限组显示 28 条关联记录（13 对前后端及香港前后端）。第一轮验收时普通账号 13/13 实际代理成功，已有 3 个出口通过健康检查，订单仍等待自动重试，因此验收如实失败；未人工改健康或订单状态。验收脚本补充香港备用实际请求及订单更新时间，等待自动开通后复验。

最终[生产验收](https://github.com/nanashiwang/Xboard/actions/runs/39222948840) success，执行脚本提交为 `377d959`，运行应用仍为已验收的 `f4f3849`。保留订单于北京时间 16:26:31 自动完成，金额仍为零，200 GB 权益到期为 2027-04-19 16:26:31；前后读取及页面均确认开通，不曾手改状态或重放完成订单。订阅恰有一个固定美国出口和香港备用；实际固定出口 IP 匹配分配，其他 12 个池内后端均拒绝该固定账号；香港备用实际请求成功。普通账号仍获 13/13 原后端授权，13/13 真实 HTTPS 请求成功。验收快照中 8/13 出口健康、一个出口占用一个名额，另五个等待连续监测；不强制放行，不能把瞬时连通视为持续健康。长期稳定性与全国各运营商体验不在本次验收范围。

生产权限快照保留在容器持久目录 `storage/app/owned-fixed-20261019-162002-3603358e.json`（0600）；若需回退旧镜像，先恢复本次增加的专属组权限并停用别名，避免旧授权逻辑扩大固定账号访问范围。最终业务实现、能力地图、运维说明及决策笔记均已更新；沿用 GHCR 发布，无独立 GitHub Release 流程。

## 2026-10-19：线上作业失败与专属订单排查

用户明确指出正式仪表盘的「作业详情 → 7日报错数量」。页面异步加载前短暂显示 0，不是最终结果；等待数据返回后，本轮观察到计数 798，且持续增加。最近可见任务为 `order_handle / OrderHandleJob`，每分钟重复报 `DedicatedExitService::activate` 的“专属出口暂不可用，订单已保留，恢复后自动开通”。

抽查任务数据追到同一笔人工分配订单：2026-10-18 22:07 创建，专属套餐半年付，现金、余额、优惠、折抵和退回金额均为零，回调来源为人工操作，一直处于开通中。用户当前订阅已过期。专属套餐页面仍存在；未据普通节点在线状态推断专属出口可交付。具体订单和用户标识不写入公共仓库。

### 原因与修复

- `check:order` 每分钟重投待支付/开通中订单，单个作业又尝试三次；出口不可用时开通事务回滚，因此会反复累计失败记录，报错数量不等于失败用户数或独立订单数。
- 用户端购单已在事务内预留专属出口；后台 `order/assign` 原先绕过预留。现复用同一服务，无容量或无健康出口时回滚订单，零元人工分配也不能跳过；管理员自定义金额、周期与原续费绑定仍保留。
- 失败详情原先仅获取 Horizon 前 50 条再切片，导致后续页面为空。改为按索引读取目标页，每页最多 100 条、至多两块，不清空历史错误。
- 用户明确选择“保留订单，等专属出口恢复”。针对已识别的出口不可用，保留开通中状态，记录原因与下次尝试时间，按 5 分钟间隔自动重试；其他异常仍失败。缓存只控制频率，持久化订单保留恢复依据；不取消、不换套餐、不退款，不清空历史失败。
- 实现边界、替代方案与剩余风险见[决策笔记](./.agents/notes/implemented/bug-fix/2026-10-19-dedicated-admin-order-failures.md)。

### 验证与交付边界

PHP 8.2.33 下专属并发、订单/支付和失败分页共 **55 项测试、276 个断言通过**，含等待期间不发权益、恢复自动开通及重复执行幂等、调度冷却、其他异常保留和待支付取消；新增 Order Queue Checks 自动执行这些检查，笔记结构和差异空白检查通过。生产后台读取验证了真实失败明细、订单来源/金额及当前用户状态；初始服务器直连 SSH 超时，未据终端提交命令声称原始文件日志已取得。

本地 testing 日志另有 Redis/临时 SQLite 环境报错，与本次线上订单异常分开处理；未把最初的本地统计服务修改混入本次提交。最初排查时生产版本为 `20261019-2b8c615`；构建期间刷新已显示其他任务部署的 `20261019-c00e753`，失败计数 814，仍未包含本次订单修复。本轮未部署、重启、删除失败记录或改变用户权益。仓库沿用 GHCR 双架构镜像，无 GitHub Release / 安装包发布流程。

代码提交 `5d656886f6a95d8e3b3638b7c0716e231e006ec9` 已推送 `origin/master`。[订单检查](https://github.com/nanashiwang/Xboard/actions/runs/39196263271)再次确认 55 项 / 276 断言通过，[邮件检查](https://github.com/nanashiwang/Xboard/actions/runs/39196263247)、[节点探针检查](https://github.com/nanashiwang/Xboard/actions/runs/39196263257)与[笔记门禁](https://github.com/nanashiwang/Xboard/actions/runs/39196263303)均 success；[镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39196263267) success。GHCR `5d65688` 的 amd64 / arm64 manifest 已回读，digest 为 `sha256:596d18b6a55802a1a34f966ca1107842fd57a76069ebfce821c29c8ae724ebea`。README 与 progress-log 已从 GitHub 按该代码提交回读并逐字节一致；交付记录使用独立 `[skip ci]` 文档提交，生产部署和出口恢复后的真实开通验收仍待执行。

用户随后明确授权“现在部署并核验”。首次用完整代码 SHA 触发工作流被 GitHub 以 HTTP 422 拒绝，未执行远端操作。部署流程补充可选完整 image_revision，以便从 master 启动并核验已发布的指定镜像；SSH 前校验格式，原有迁移前镜像一致性检查继续保留。无需创建部署分支/标签，也不为文档提交重建应用镜像。actionlint、18 项运维测试、6 个目标提交号格式用例、笔记与差异检查通过；该流程改动使用 `[skip ci]` 提交，不改变已验收应用镜像。

部署流程提交 `4bd3fa1` 后，[首次部署](https://github.com/nanashiwang/Xboard/actions/runs/39207057769)成功，运行 OCI revision 为 `5d65688`。启动阶段短暂 502，随后后台恢复；部署前失败计数为 943。页面却显示 `20261019-058fd4c`，追踪到原 Dockerfile 构建时另行 clone master，058fd4c 相较 5d65688 仅增加文档。为避免未来混入未验收业务代码，构建新增 SOURCE_COMMIT，由 CI 传入完整 SHA，checkout 后强制核对 HEAD，再处理子模块。最终镜像、页面版本及跨重试间隔的订单验证待补记。

构建修复通过 actionlint（同时将原先在使用后才生成的版本元数据提前）、真实临时 Git 仓库的分支前进/提交锁定测试及非法 SHA 拒绝测试、笔记与差异检查。订单业务代码保持已通过的 55 项测试版本；新版应用镜像由主线 CI 重新构建发布。

### 最终生产验收（北京时间 2026-10-19 14:06 起）

- 部署参数提交 `4bd3fa1` 的[运维 CI](https://github.com/nanashiwang/Xboard/actions/runs/39207123893) success；构建修复提交 `9d6cf40331793bf1eaef3a5f53df4c4deef5aefb` 已推送 master，[镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/39207429478)及[笔记检查](https://github.com/nanashiwang/Xboard/actions/runs/39207429644)均 success。amd64/arm64 构建日志都确认 HEAD 为 9d6cf40；manifest digest `sha256:60449496b7da710c3a32b74cfe2cc3fc29cba9da04557793f8b92e15e663cb97` 已回读。
- [最终部署](https://github.com/nanashiwang/Xboard/actions/runs/39207867717) success。14:05:53 容器 Healthy，运行镜像 revision 为 9d6cf40，14:06 正式后台显示 `20261019-9d6cf40`，与镜像一致。
- 首次修复部署于 13:56:36 完成；14:03、14:06 的刷新均显示失败计数 944，超过 10 分钟未新增，跨过 5 分钟等待间隔。最新失败仍是更新前的 13:56:20；队列正常、等待 0 秒、活跃进程 11/11。部署前 943 到最终 944 的一条发生在旧容器退出前，历史记录未清理。
- 保留的零元人工半年订单仍为开通中，套餐、金额和更新时间保持原值；失败明细第 7 页读取到 12:56 至 12:47 的 10 条记录，翻页问题已在生产验证。未伪造出口恢复、修改用户权益或主动完成订单；出口真正恢复后的开通需由正常调度处理，当前只确认等待期间不再制造重复失败。
- README/progress-log 已按代码与部署流程提交从 GitHub 回读一致。最终验收记录用独立 `[skip ci]` 提交，不再重建镜像；推送后再次回读。应用无 GitHub Release/安装包流程，最终交付为已部署的 GHCR 双架构镜像。
