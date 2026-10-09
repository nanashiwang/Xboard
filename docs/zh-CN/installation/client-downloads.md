# 客户端安装包本站托管

## 用户下载与导入入口

`/clients` 提供独立的中文下载与导入页面。Xboard 默认主题的侧栏增加“客户端下载”，仪表盘增加“下载与导入”入口；不修改压缩后的 `umi.js`。页面会识别操作系统，也允许手动切换，macOS 芯片类型由用户选择，避免浏览器将 Apple 芯片误判为 Intel。

- Windows、macOS、Linux：Clash Verge Rev 2.4.7。
- Android：Clash Meta for Android 2.11.24，提供 ARM64 和通用包。
- iPhone/iPad：sing-box 官方 App Store 入口。当前官方要求 iOS 15+ 和中国大陆以外地区的 Apple 账户；安装由用户在 App Store 完成。

桌面与安卓继续使用下方已托管的固定版本，并保留每个包的官方备用链接、大小和 SHA-256。目录由 `app/Services/ClientDownloadService.php` 组织，安装包校验信息读取 `.docker/downloads/manifest.json`。升级版本时同时更新这两处，回归测试会检查清单一致性；不会自动把未经验证的 latest 推给用户。

下载页面无需登录。个人订阅通过带现有登录态的 `GET /api/v1/user/client/import?client=...` 获取，仅支持 `clash-verge`、`clash-meta`、`sing-box` 三种值。无有效订阅、到期、流量用完或被封禁的账号不能获取导入信息。响应标记 `private, no-store`，页面不使用第三方订阅转换服务，也不将个人订阅写进公开 HTML、安装包或浏览器持久存储。

一键导入使用项目官方支持的 URI Scheme：`clash-verge://`、`clashmeta://`、`sing-box://`。其中 Clash Verge 的 `url` 参数放在最后，兼容其读取余下整段查询串的实现。订阅 URL 不强行指定 `flag`，保留客户端 User-Agent 对格式和内核能力版本的识别。浏览器拉起客户端后，仍需用户在客户端确认保存和开启连接；页面只提示“请确认导入”，不把拉起动作当作连接成功。自动复制不可用时提供可选中的手动地址。

部署应用镜像前先确认原有 `/downloads/` 文件仍在。应用更新需刷新当前主题，才能发布新的侧栏入口脚本；现有 `xboard:update` 已调用 `refreshCurrentTheme()`。`/clients` 使用的静态文件位于 `public/assets/client-downloads.*`，随应用镜像发布。

协议及平台要求核验来源：

- [Clash Verge Rev 2.4.7 导入解析](https://github.com/clash-verge-rev/clash-verge-rev/blob/v2.4.7/src-tauri/src/utils/resolve/scheme.rs)
- [CMFA 2.11.24 URI 注册](https://github.com/MetaCubeX/ClashMetaForAndroid/blob/v2.11.24/app/src/main/AndroidManifest.xml)
- [sing-box Apple 官方安装说明](https://sing-box.sagernet.org/clients/apple/)

本地验证：`vendor/bin/phpunit tests/Feature/Desktop/ClientDownloadTest.php`，并在真实主题壳中检查登录与未登录入口、各平台切换、窄屏、暗色、过期账号、复制失败和网络错误提示。浏览器测试不能替代各操作系统上实际安装客户端、导入、连接节点的验收。

主域名配置完成后，生产下载地址为 `https://taige.us/downloads/`，`https://board.taige.us/downloads/` 继续兼容。文件由宿主机 Nginx 提供，不经过 Xboard 容器。当前托管 CMFA 2.11.24 的两个安卓包，以及 Clash Verge Rev 2.4.7 的 Windows x64、macOS Intel/Apple Silicon、Linux AMD64 DEB 包，总计约 295 MiB。

## 安装和更新

1. 将仓库 `.docker/downloads/` 下的文件复制到服务器 `/opt/xboard-downloads/`。
2. 执行 `python3 /opt/xboard-downloads/sync.py /srv/xboard-downloads`。脚本检查官方发布时的文件大小和 SHA-256，只在校验成功后原子替换文件；重复执行会复用已校验文件。
3. 在站点 HTTPS `server` 块中加入 `include /opt/xboard-downloads/nginx.conf;`。
4. 执行 `nginx -t`，通过后执行 `systemctl reload nginx`。
5. 通过公网 HTTPS 检查每个文件的状态码、文件大小、完整下载校验和 Range 请求，确认后才更新知识库文章。

SHA-256 和文件大小来自对应官方 GitHub Release 的资产元数据，固定保存在 `manifest.json`，不自动跟随 latest。发布新版本时，应核实官方来源、更新清单，并使用带版本号的新文件名；不要覆盖相同 URL 下的已发布版本。

官方来源：

- <https://github.com/MetaCubeX/ClashMetaForAndroid/releases/tag/v2.11.24>
- <https://github.com/clash-verge-rev/clash-verge-rev/releases/tag/v2.4.7>

## 生产目录和回滚

- `/srv/xboard-downloads/`：公开安装包和 `SHA256SUMS.txt`，独立于应用更新。
- `/opt/xboard-downloads/`：同步脚本、清单和 Nginx 配置。
- `/opt/xboard-downloads/backups/`：修改前的网站 Nginx 配置备份。
- `/root/Xboard/.docker/.data/backups/knowledge-5-before-local-downloads-*.json`：知识库文章 5 的修改前快照，位于持久化挂载目录。

知识库主链接使用本站地址，每个主链接旁保留官方备用下载。原有 FastClient 和 Win7 第三方备用地址未迁移。Linux DEB 包只面向相应系统，其他架构和发行版继续引导至官方发布页。

回滚时先恢复备份文章的正文，再移除 Nginx include，检查配置并平滑重载；无需删除安装包。不要回滚文章的其他字段或覆盖备份之后产生的无关编辑。

两个域名均通过 Cloudflare HTTPS 入口访问；主域名解析、证书和续期见 [主域名配置](primary-domain.md)。用户无需访问 GitHub，但大陆实际速度仍受用户到站点的网络线路影响。下载会产生服务器流量，应结合主机套餐观察用量。
