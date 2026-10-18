# 节点质量探针

Xboard 独立维护的外部探测功能。侧栏「节点质量」在后台主内容区打开完整页面（`#/?page=node-quality`），仪表盘不再重复显示监控卡片；历史明细在页面内查看并可返回列表。独立同源视图路径为 `/<后台安全路径>/node-probes`；仅管理员能读取结果。现有机器心跳和资源监控继续保留。

## 检测范围与指标

- NAS 运行固定版本 sing-box，通过每个指定公开节点执行 Cloudflare trace 和 Google 204 HTTPS 请求，验证 TLS 和 HTTP 响应。只有一个代理出站，没有直连、自动切换或备用节点回退。
- 每轮结束等待 60 秒；同时最多检测 4 个节点。每节点每 30 分钟上传、下载各 256 KiB，检查 HTTP 响应和完整字节数。失败也遵守测速间隔，重启不会立即重复消耗流量。
- 显示 HTTP 成功率、成功请求平均耗时/P95、上传下载完成次数、小样本速率、最近测量时间、出口 IP、故障和恢复历史。速率包含连接和传输耗时，不能作为线路带宽上限；失败显示原因，不伪装成有效的 0 Mbps。
- 连续 3 轮两个目标均失败为故障；连续 2 轮所有检测成功为正常；部分失败或恢复确认期为波动。账号失效、协议不兼容与探针失联单独显示。
- 每位置独立统计。节点或探针过期阈值为 `max(300, interval * 3 + ceil(nodes / 4) * 30)` 秒。缺测不进入 HTTP 成功率分母，也不能当作正常；页面请求失败会把已有状态标记为过期。
- 明细保留 24 小时，概览按最近 24 个小时桶统计，小时数据与事件保留 30 天。`probes:prune` 每小时执行；需确保 Xboard 原有调度器正常。
- 当前不发送 Telegram/邮件，不调整用户节点选择、公开节点 ID、套餐权限或专属出口分配。专属分配账号暂不支持。

出口 IP 用于确认落地点；页面上的入口地址来自节点配置。若要证明客户端或探针使用新入口，还应核对运行连接的目标 IP、入口访问日志。单台家庭 NAS 不能代表所有运营商，目标站异常也会影响测量。

## 创建与安装

先按现有部署流程更新面板并执行数据库迁移。为探针使用独立普通账号，分配能访问目标节点的权限组、用量和有效期；不共用日常用户的订阅凭据。

管理员可在页面输入账号 ID 和节点范围创建探针，得到只展示一次的配置。运维也可在面板容器中执行：

```bash
php artisan probes:create nas --location='家庭网络 / NAS' --group=1 --nodes=314,315
```

以上节点/权限组只是示例，应按实际面板核对。`--group` 创建独立非管理员监控账号：30 GiB 总额度、365 天有效期、100 Mbps 限速、关闭提醒邮件；不会扣用户余额或修改套餐。不会自动续额度，耗尽后显示账号不可用。也可用 `--user=监控账号ID` 绑定现有账号，二者不能同时指定。

配置保存到 `storage/app/private/node-probes/<探针ID>.json`（600 权限），命令不输出令牌。将该文件安全传到探针主机并命名为 `agent.json`，完成后删除面板端配置副本。令牌可获取该探针选定节点的实际代理凭据，应按订阅凭据保护；数据库只存 SHA-256，页面列表不返回令牌或订阅 UUID。

在 NAS 的独立持久目录中放置本仓库 `tools/node-probe/` 文件及配置：

```bash
chmod 700 .
chmod 600 agent.json
mkdir -p state
# 容器使用 UID/GID 1000；配置和 state 目录须由该用户可读/写。
docker compose build
docker compose up -d
docker compose logs --tail=20
```

若 NAS 无法访问镜像仓库，可在可联网机器构建匹配架构的镜像，通过 `docker save/load` 传入；随后使用 `docker compose up -d --no-build`。NAS x86_64 使用 `linux/amd64`，ARM 使用 `linux/arm64`。

容器没有宿主机端口、特权、TUN 或主机网络，根文件系统只读，临时配置在 tmpfs，状态目录仅保存测速间隔。CPU 上限 1 核，内存 384 MiB，日志轮转 2 × 5 MiB。一个 state 目录只能运行一个探针进程。配置中的 `panel_url` 必须为可访问的 HTTPS 根地址；上报直接访问面板，不继承环境代理、不跟随重定向、不关闭证书校验。

17 个节点按默认传输配置的理论载荷约 408 MiB/天，此外有 HTTPS/TLS/隧道开销，实际流量还受节点倍率影响。可在创建 API 中调整检测间隔（60–3600 秒）、传输间隔（1800–86400 秒）、载荷（64 KiB–1 MiB）；生产建议先使用默认小样本。

## 运维与排查

- 探针离线：检查 NAS 容器状态、时间同步、面板 HTTPS 可达性、令牌和面板调度。
- `account_unavailable`：检查监控账号禁用/到期/额度/权限组，以及公开节点可用性；不能通过改成管理员解决。
- `core_config` / `unsupported_protocol`：内核不支持当前节点配置；不会算作节点断线。VLESS xhttp、未校验证书的 TLS 节点不进入正常状态。
- 上传超时而下载正常：结合两种目标连通性、账号限速、NAS 家庭上传带宽及入口/隧道指标判断，不能单凭一轮归因。
- 停用会撤销探针 API 访问；重新启用后继续取配置。轮换令牌立即使旧令牌失效，更新 NAS 的 agent.json 后重启容器。旧采样不重放，不重复累加统计。
- 升级：替换源码、重新构建镜像并 `docker compose up -d`。移除：`docker compose down`，再按需要保留 state 和配置；面板停用对应探针。

## 验证命令

```bash
vendor/bin/phpunit tests/Feature/Probes
node --check public/assets/node-probes.js
docker build -t xboard-node-probe:test tools/node-probe
docker run --rm --entrypoint python3 -v "$PWD:/work:ro" -w /work xboard-node-probe:test -m unittest discover -s tests/Probes -v
python3 .agents/workflow.py verify
```

本地 fixture、GitHub 检查、镜像发布、面板上线与 NAS 的真实采样是不同验收步骤；实际状态见仓库 [progress-log](../../../progress-log.md)。

上传或下载失败后，后续仅有轻量 HTTPS 请求成功不能将节点恢复为正常；必须先取得成功的传输复测，再满足连续成功条件。

侧栏「节点质量」通过本仓库维护的扩展脚本挂载到固定版本管理前端的主内容区，仪表盘不再重复展示；不改写编译子模块。升级管理端子模块需复验挂载、路由往返、权限失效、深浅主题、窄屏和页面内历史。

探针 1.0.1 使用 `Xboard-Node-Probe/<版本>` 客户端标识访问面板。若容器仍在线但面板无上报，应区分 CDN 返回的 1010/403 和应用鉴权错误，检查请求是否到达应用；不能把这种接入错误算作节点断线。Compose 的 tmpfs 值包含逗号，必须保留引号；CI 现在使用实际 Compose 启动一次内核检查，配置解析通过不等于 Docker 挂载可用。

探针 1.0.2 对面板网络错误、429、5xx 最多重试一次，保留相同采样 UUID；401/403 不重试，持续失败会记录错误类型和 HTTP 状态，等待下一轮，不回放历史。重试仅用于配置/上报，不额外重复节点上传下载。升级会保留 state 内的传输间隔预算。

## 第一段入口、机器资源与出口隧道

1.1.0 在每轮完整线路检测前，对每个已绑定入口只执行一次直连 HTTPS 健康检查；严格校验证书、HTTP 200 和固定响应，不跟随重定向，最多接收 4 KiB、8 秒超时。它不作为代理检测失败后的直连回退，也不计入节点 HTTP 成功率。DNS/TCP/TLS 为分阶段耗时；首字节和总耗时从请求开始计算。没有登记入口的 CF 等线路显示「未绑定入口」，不会冒用主入口数据。

入口上的独立 Python 采集器读取 `/proc`、物理网卡计数、Nginx/WireGuard 状态和 peer 最近握手，每轮对各个指定隧道 IP 发 3 个 ICMP 包。最多 4 个并发，每轮后等待 60 秒。只读采集不配置代理、路由或防火墙。网卡计数差以 bytes/s 上报，页面换算 Mbps，表示物理网卡当前收发负载；不能把它当作剩余带宽或最大测速结果。CPU、内存和资源时间与 NAS 检测分别显示；资源超过 180 秒未更新时失效，机器轮询 nodes 接口不会刷新资源时效。

先在面板服务器备份数据库、部署迁移，再根据真实 Nginx 到 WireGuard 的映射填写 [example.json](../../../tools/ingress-monitor/example.json)，不要从 `parent_id` 自动推断中转关系：

```bash
php artisan probes:ingress /安全目录/ingress.json
```

命令只允许绑定同一域名下的公开节点，创建独立机器身份、不把公开节点改绑到机器。输出文件 `storage/app/private/node-probes/ingress-<id>.json` 权限为 600，包含机器令牌，只通过已有安全通道传到入口的 `/etc/xboard-ingress-monitor.json`，权限 600。不要提交或输出令牌。重复登记同一域名更新映射并复用机器；如轮换机器令牌，需重新生成并替换配置。

将 [采集器](../../../tools/ingress-monitor/monitor.py) 安装到 `/opt/xboard-ingress-monitor/monitor.py`，将 [systemd 单元](../../../tools/ingress-monitor/xboard-ingress-monitor.service) 安装到 `/etc/systemd/system/`。依赖 Python 3、iputils ping、现有 WireGuard 和 systemd；CPU 配额 10%、内存 96 MiB，仅保留读取 WireGuard 所需 NET_ADMIN 与 ICMP 所需 NET_RAW。先验证配置内物理网卡和隧道名称，再启用：

```bash
systemctl daemon-reload
systemctl enable --now xboard-ingress-monitor
systemctl status xboard-ingress-monitor
journalctl -u xboard-ingress-monitor -n 20 --no-pager
```

NAS 保留原 `agent.json` 和 `state/`，升级到探针 1.1.0；拉取配置后自动检测已绑定入口。页面应同时出现 NAS 的新入口采样、机器资源与 13 条实际映射隧道。入口历史在完整页面内查看；详细检测和资源均保留 24 小时，各表最多显示最近 200 条。隧道状态目前仅保留最新一轮，不提供历史丢包统计。停用或删除采集器不会改变业务代理链路；回退只停止此监控服务、恢复旧 NAS 镜像，不删除业务 WireGuard/Nginx 配置。

排查时按位置和时间对照：多节点同时慢且入口 HTTPS 也变慢，先查本地到入口网络与入口负载；只有一个 peer 丢包，重点查对应隧道和出口；所有小请求正常仍下载慢，仍需检查带宽、目标站、账号限速和客户端。3 包零丢包不是长期稳定证明，ICMP 失败也可能是限速或过滤；不自动给出唯一根因。
