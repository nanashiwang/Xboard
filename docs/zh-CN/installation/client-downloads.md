# 客户端安装包本站托管

生产下载地址为 `https://board.taige.us/downloads/`，由宿主机 Nginx 提供静态文件，不经过 Xboard 容器。当前托管 CMFA 2.11.24 的两个安卓包，以及 Clash Verge Rev 2.4.7 的 Windows x64、macOS Intel/Apple Silicon、Linux AMD64 DEB 包，总计约 295 MiB。

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

当前沿用站点已有的 Cloudflare HTTPS 入口，没有新增域名或 DNS 依赖。用户无需访问 GitHub，但大陆实际速度仍受用户到站点的网络线路影响。下载会产生服务器流量，应结合主机套餐观察用量。
