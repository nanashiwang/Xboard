# 四档普通套餐的第三方拓展线路

2026-10-22 已接入 41 条服务端拓展出站。四档保留 6 条自建，按轻量、标准、进阶、旗舰累计增加 8、16、28、41 条，实际订阅合计 **14 / 22 / 34 / 47**；流量、重置及到期提示不计入节点数。独享组 5、11 个自建固定出口池及已有订阅身份不变。

入口仍为 `node.lumavia.fyi:443`。客户端使用自己的 VLESS/WebSocket/TLS 身份，Nginx 按独立路径转到本机回环端口 37001–37041；机器 21 的独立 `xboard-extension.service` 负责鉴权、计量并通过指定上游出站。它与原自建线路共用第一阶段入口，不能据此宣称入口级双活容灾。41 个名称不是 41 个独立 IP 或 41 份上游额度。

完整公开/后端 ID、套餐起点、倍率和限制见[分配清单](../../../.docker/upstream/allocation.json)，取舍与验证见[决定](../../../.agents/notes/implemented/architecture/2026-10-21-tiered-upstream-route-family.md)。每条有一个公开记录、一个隐藏后端，新增 82 条管理记录均有用途，不能按隐藏状态删除。

## 客户端命名

客户端统一使用 `国家或地区＋两位编号｜倍率×｜可选属性`，例如 `日本01｜1×`、`美国06｜2×｜家宽`。分类、U 编号、供应商、入口和限制说明不再放入名称；线路 ID、后台标签、分档和实际限制继续保留。完整规则见[命名与家宽倍率决定](../../../.agents/notes/implemented/simplification/2026-10-22-node-names-and-residential-rate.md)。

13 个自建美国出口（普通套餐 2 个、固定池 11 个）均按用户定义标为“家宽”，实际倍率统一为 2×；名称不构成独立住宅 IP 认证，也不表示物理独占。U36/U37 分别显示 `香港06｜1×｜原生IP`、`香港07｜1×｜原生IP`，属性沿用上游声明，未独立核实；其他线路不据此扩展原生 IP 标记。

## 身份、倍率和可用边界

- 普通组按最低套餐累计授权，并加入内部监控组 6；公开和后端权限一致。组 5 不加入，后端也拒绝独享 UUID。不得把上游密码、UUID、原订阅地址或令牌放入公开记录、客户端模板及 Git。
- 原有用户总额度继续共享。公开显示与负责上报的后端倍率一致，使用 1x / 2x / 5x。公开记录不重复报告流量。
- 41 条真实 HTTPS 通过；33 条 UDP DNS 通过。美国 U01/U02/U03/U20/U21/U22/U23/U24 对两个公共 DNS 的 UDP 测试未通过。U 编号用于后台定位；新名称移除了“UDP受限”尾缀，限制仍然存在，不保证这些线路的游戏、通话或 QUIC 体验，也不把它们的 TCP 成功当作完整 UDP 支持。
- U36–U39 的香港/台湾低流量线路，每条所有使用者共享双向 2 Mbps 上限；客户端名称不再附带限速提示，限速规则保持。仅对相应回环端口添加 `tc flower police`，不替换主网卡队列。[规则脚本](../../../.docker/upstream/qos.sh)显式使用回环 MTU 65536；默认 2 KB 会误丢 TLS 数据。policing 会重传，2 Mbps 是上限而非保证速度；2 MiB 下载曾出现一次 40 秒未完成，日常短请求最终通过，不作为大流量线路销售。
- 3 条 CDN 出站使用公共 CA 校验。其余 38 条使用初次观测的证书公钥固定，并将非 QUIC 的自签名连接地址与公钥配对，避免 DNS 轮换造成证书错配；28 条 IPv4 TCP 端点在另一台服务器比对相同。其余 IPv6/QUIC 采用首次信任固定，并非取得供应商独立签发证明。没有配置全局 `insecure=true`，换证需重新核验。

## 运行与维护

第一阶段服务器：

- `xboard-extension.service`：非 root，384 MiB Go 软上限 / 640 MiB systemd 上限；验收约 45 MiB，0 次重启。
- `xboard-extension-firewall.service`：37001–37041 仅回环访问；原 Nginx、自建隧道与路由保持。
- `xboard-extension-qos.service`：四条低流量线路的限速，优先级 47000–47007。只删除/重建这些自有规则，不删除整个 clsact 或其他规则。
- 凭据配置在 `/etc/xboard-extension/config.yml`，root 与专用服务组可读；操作备份在 `/root/xboard-upstream-review/deploy-backup/`。

面板服务器：

- `xboard-upstream-guard.timer` 每 5 分钟校验原始订阅的额度、有效期和已批准条目指纹。到期前 5 分钟、额度耗尽、条目消失/重复、端点或凭据变化时，只隐藏受影响拓展公开记录并停用对应后端；新增未知条目不自动加入。暂时取订阅失败保留已知配置，超过 24 小时没有有效元数据或到达已知到期窗口则撤下全部拓展。
- 保护脚本为[guard.py](../../../.docker/upstream/guard.py)和[guard-apply.php](../../../.docker/upstream/guard-apply.php)。原始 URL、指纹和状态仅在宿主 `backups/upstream-20261022/` 的私有文件中。不能直接把更新后的原始订阅覆盖到生产；变更项应重新测试、更新受限映射后再公开，保护程序不自动重新启用。
- 原管理 WebSocket 的 8076 地址仍不可达，新服务使用已验证的 REST 轮询，约一个 60 秒周期接收撤销。撤下测试先于该周期的请求仍可用，等待轮询后确实拒绝，恢复后复测成功。停用后端时最后一批未推送流量可能被现有 enabled 鉴权拒绝；常态计量核对通过，不宣称停机结算无损。上游故障不会切到 DIRECT。
- `xboard-extension-probe.service` 使用独立探针 2，从面板服务器穿过真实公开入口检查全部 41 条；每 300 秒轻量 HTTPS，每 86400 秒每条 64 KiB 上/下行完整性检查，不做批量大流量测速。原 NAS 探针 1 的 17 条及固定出口健康策略保持。探针配置 `/etc/xboard-extension-probe/agent.json` 受限读取。

上游共用一份账户额度和有效期，价格与套餐节点数不会增加其容量。运营方需持续维护续费、额度和来源限制；本次短请求与小流量验证不代表长期稳定、并发承载或大陆各运营商速度。

## 运行时 AnyTLS 公钥检查（仓库已实现，未部署）

旧保护器的订阅 JSON 指纹无法发现“字段未变、服务端公钥已变”。新版对已批准 AnyTLS 固定 IP/端口/SNI 做真实 TLS 握手，计算叶证书 SPKI DER 的 SHA-256/Base64，必须与旧 pin 完全一致。`runtime_public_key_mismatch` 对应本次新加坡 `unrecognized remote public key` 的检测条件。检查不发送 AnyTLS 密码或业务请求；证书采集与显式 pin 比较完成前不判通过，不改变业务的 TLS 验证。

输入为三个现有职责的文件，均不从当前握手自动建立信任：

- `approved.private`：沿用 key、backend_id、public_id、source_name、source_sha256。
- 随代码交付的 [allocation.json](../../../.docker/upstream/allocation.json)：核对 key/两层 ID 与 upstream_type，将范围限定为 28 条 AnyTLS；不读取当前订阅来选择探测端点。其余 VLESS/Trojan/Hysteria2 仍沿用元数据保护，不宣称本次已做它们的运行时身份校验。
- 受限 `pinned.private`：沿用历史交叉核验脚本的 JSON 数组，每行 `{ "key": "U04", "ip": "已批准的IP字面量", "port": 443, "sni": "已批准SNI", "pin": "已批准的32字节SHA256的Base64" }`。此处为格式示意，不能直接投入使用。`--identity-map` 显式指定既有文件；省略时读取 `--root` 下同名文件。IP/端口/SNI/pin 与当前批准出站的对应关系必须人工核对；禁止运行历史 `pin_endpoints.py` 重新采信当前公钥。

从仓库运行只读专项检测（路径按实际受限文件位置填写）：

```sh
python3 .docker/upstream/guard.py --check-identity \
  --root /root/Xboard/backups/upstream-20261022 \
  --identity-map /root/xboard-upstream-review/pinned.private \
  --key U04 --key U05
```

该入口不读取订阅 URL/密码、不写 guard-state、不调用撤下事务。退出码 0 表示所检 AnyTLS 全部匹配；1 表示至少一项失败或没有可检查项；2 表示输入/执行错误。`--key` 只能配合只读模式，未知 key 拒绝。输出只有 key、后端/公开 ID、固定 reason，不包含完整端点、SNI、pin 或异常消息。只读失败不会主动撤下生产节点。

默认保护流程在元数据成功、短暂失败、过期失败时均独立检查身份。失败即合并进原 `guard-apply.php` 撤下请求，额度/到期/来源变化理由优先，身份结果另存 `identity_checks`；原事务继续核对批准 manifest、机器、父子关系、标签，只隐藏公开节点和停用后端。运行时超时、TCP/TLS失败、证书解析/工具失败、映射缺失/重复/无效都不能当作通过，范围清单缺失/错配也失败关闭；未知映射不自动接入，检测通过不自动恢复。

**部署前置条件（本轮未执行）**：核验现存私有映射完整且与已批准出站一致，将 guard.py 与 allocation.json 一并交付，确保 Python 3.9+、OpenSSL 可用（默认订阅流程另需既有 PyYAML），先运行只读检查。8 并发、单项 5 秒总预算使 28 条最多约 20 秒握手/转换时间；还需预算订阅读取与撤下事务，部署时需将既有 `TimeoutStartSec=120` 评估为至少 180 秒。本轮没有替换线上脚本、映射、systemd 或数据库配置；缺失映射不能以空文件或跳过检查应付。后续更新信任仍须独立确认来源、人工复验并恢复公开路径。

检查通过仅说明此检测机在该次握手中看到批准的公钥，不证明供应商独立身份、密码有效、目标站点可用或公开 VLESS 路径成功。入口侧与本机网络差异仍需分别验证。

## 验证与回退

本地执行 `python3 -m unittest discover -s tests/Upstream -v`、PHP/Python/shell 语法检查和 `python3 .agents/workflow.py verify`。线上应从实际入口验证每档权限、欠费/到期/封禁拒绝、上游失效不直连、倍率与客户端订阅。不能用服务器在线代替可用性；[独享验收脚本](../../../.docker/dedicated/verify-owned.py)仅核对保留的自建子集，拓展权限另按批准清单验证。

生产容器 `storage/app/backups/upstream-20261022/` 保留一致性 SQLite 备份、原字段快照、私有 manifest 和发布结果；宿主同名 backups 目录保留执行/验收结果。回退先隐藏清单中的公开记录、停用对应后端并确认旧链接拒绝，再停用探针 2、保护定时器及拓展服务。Nginx 只移除 `BEGIN/END upstream-extension-20261022` 区段并检查后重载；限速只移除优先级 47000–47007。确认没有监听后可删除专用 nft 表与服务文件。不要整库恢复、替换整个 Nginx 路由文件或修改原 53 条节点、套餐、用户、订单、NAS 探针和独享池。

## 人工恢复工具

候选准备同时覆盖TCP、QUIC与公共CA；宿主固定私有manifest、approved、allocation及当前数据库父子/标签共同限定41条，容器缺失副本不再作为持久存储。缺失宿主映射仍拒绝；只能单独执行audit-scope，交叉核对现存approved、固定allocation、DB归属/状态，再针对具体审计ID/SHA显式restore-scope。不是自动重建，也不批准新pin。`maintain.py`只接受prepare计划ID/SHA与人工选定候选摘要；先在线备份，分步撤下、隐藏应用、验收后公开，漂移/未知结果拒绝重放，回退保持撤下。工作流按显式阶段操作，公开路径验证绑定维护回执；生产执行与尚待验收部分见[进展](../../../progress-log.md#2026-10-27生产外接线路人工恢复)。

保护器新版撤下传输仅使用经验证的宿主持久manifest与PHP stdin，不再依赖容器存储副本；该代码当前尚未部署。缺映射依然拒绝，不能把重建scope当成公钥批准。

`inspect-environment`只读检查固定探针文件的安全形状和运行环境类别；不打印凭据或URL。`accept-source-address`只接受U01的明确新来源SHA，必须证明还原原server后精确等于旧批准指纹；仅更新该source_sha256且使旧计划失效，不修改或批准pin。两者均不是自动恢复线路。`sync-pins`必须在publish后公开路径通过，绑定返回的验证报告ID/文件SHA与维护执行回执，才同步DB中已核准的28条AnyTLS身份；不探测或学习新pin。`inspect-legacy-guard`/`restore-legacy-guard`仅支持字节匹配已审阅metadata-only版本的原容器清单恢复，不升级保护器。目录随容器丢失时，只允许在固定真实storage anchor下创建缺失backups/scope为root0700；现存unsafe目录、symlink或冲突均拒绝，不更改原目录权限。维护工具接受省略insecure的严格默认并保留省略，null/true/非bool拒绝。

`secure-probe-config`只适用于已核验静态root服务，本次非root服务检查已在写入前拒绝，不能用它破坏专用服务读组。公开验收只读允许root拥有0600，或0640且文件组精确匹配固定静态探针服务有效组；拒绝其他权限、符号链接与读取漂移，不改变服务配置。`recipient`为现存有效计划生成绑定公钥；`import-reviewed`接收有限RSA-OAEP身份密文及双网络观察承诺，只创建新私有候选计划，不批准或应用。它保留原计划期限，严格CA线路不添加pin，导入后仍须显式选择与公开路径验收。现面板无IPv6，外部观察标明入口/独立观察位置，不绕过TLS，也不将新runtime保护器直接部署到不具备对应地址族的检测机。

### 两轮修复的合并验收

本次39条首轮修复后，最多仅允许U26/U29/U33/U34/U40追加人工补修。先用新的prepare计划完成子集withdraw与apply_hidden，再以`aggregate-create`的独立`graph`输入引用首轮plan ID/SHA/execution和新plan ID/SHA/repair execution。工具逐项核对两轮真实回执及全41状态，不改旧记录、原缓存或时间，不接收IP/公钥。返回的ledger有效期来自新计划原始两小时期限，不能续改。

后续`aggregate-verify`、`aggregate-publish`、`aggregate-sync`使用plan_id/plan_sha256字段传递ledger ID/SHA，selection/ciphertext均为空对象，execution_id为空。隐藏阶段39条双目标全部通过才以其verification_id/verification_sha256发布；发布后重新验收39条，再以新报告和原pinned文件SHA（或`absent`）同步28条AnyTLS身份。仍复用最初真实公开缓存、严格TLS与全新内核，无DIRECT；健康两条不修改。

`aggregate-rollback`只需ledger ID/SHA，恢复首轮原出站并维持隐藏/停用，允许计划过期或来源网络不可用，但仍要求图、回执和实际状态完全匹配。新账本保留自己的在线备份、request/intent/receipt；未知结果禁止重放，不整库覆盖业务数据，不使用第二轮中间出站充当原始回退配置。
