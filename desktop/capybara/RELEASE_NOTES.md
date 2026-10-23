卡皮巴拉 0.1.0-alpha.2 优化桌面页面空间，提供 Windows x64、macOS Apple Silicon / Intel、Ubuntu GNOME x64 安装包。

- 移除首页、线路、账户和帮助页面重复的英文标语、页面标题与顶部连接状态栏，主要内容直接从页面上方开始。
- 深浅主题切换移至侧栏底部，小窗口仍可直接操作；保留辅助阅读器使用的页面标题。
- 连接状态继续在首页连接卡片显示，额度耗尽与到期提示保持可见；登录、流量同步和代理逻辑不变。

这是用于验证的 Alpha 测试版。首版采用系统代理，不含 TUN；Linux 自动代理仅支持 GNOME/gsettings。未配置 Windows 代码签名、macOS Developer ID 公证和签名自动更新；系统可能提示未知发布者。macOS 安装包只做构建签名，不代表公证通过。

真实账号登录、三种系统的代理权限、安装升级、休眠恢复及实际网络环境仍需试用验收。后端 X-Core-Version 支持需部署配套服务端变更；本次发布不部署网站、不替换已有第三方客户端。

使用前先关闭其他代理应用的系统代理。安装、源码与已知边界见 [客户端说明](https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara)。内核对应源码见 [Mihomo v1.19.33](https://github.com/MetaCubeX/mihomo/tree/v1.19.33)。
