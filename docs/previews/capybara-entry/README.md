# 卡皮巴拉双域入口预览

本目录保留独立静态设计预览，**这些 HTML 不接入真实账号、API 或安装包**。正式站点已通过独立 [Hub 构建](../../../.docker/hub/README.md) 和 Go 应用入口上线，详见[实施记录](../../../.agents/notes/implemented/architecture/2026-11-02-hub-application-domain-split.md)；客户端仍为 0.1.9。

- [导航页](index.html)：对应 `capybarahub.fyi`，进入应用与客户端下载；按用户反馈移除账号说明、帮助问答与页脚。
- [Go 入口页](go.html)：对应 `capybarago.uk/`，按用户截图只显示白底蓝色「点击进入官网」按钮。
- [登录衔接](app.html)：展示点击后的体验，不替换现有用户中心；输入只读，不接受凭据。
- [下载示意](downloads.html)：展示下载页，按钮明确提示预览，不提供安装包。

用浏览器打开 `index.html` 即可交互，不需要安装依赖或启动后端。也可在本目录运行：

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

再访问 `http://127.0.0.1:8765/`；预览结束可停止服务。所有资源都在本目录，Go/Hub 主链路不依赖 JavaScript；脚本仅用于登录/下载的预览提示。图标复用项目已有卡皮巴拉品牌资产。

完整分工、迁移顺序、API 绕过按钮页与旧客户端兼容边界见[双域方案](../../../.agents/notes/implemented/architecture/2026-11-02-hub-application-domain-split.md)。页面拆分与按钮不构成防封保证，两域也不等于两条应用备用线路。

本地验收包括桌面、390 像素导航和四页 320 像素布局，主入口点击、登录/下载预览提示、相对资源、HTML 标识和 JS 语法；不代表生产登录、下载或网络可达性验收。
