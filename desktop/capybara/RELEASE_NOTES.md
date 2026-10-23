卡皮巴拉 0.1.0-alpha.3 新增应用更新检查。

- 每 6 小时自动检查新版本，重启保留检查时间，休眠恢复后补查；帮助与设置中可立即检查。
- 发现新版后显示更新说明，可选择稍后。只有确认后才下载更新，不会静默安装。
- Windows、macOS 和 Linux AppImage 支持签名校验后安装；安装前恢复系统代理，完成后重新启动。下载、校验或代理恢复失败会停止更新并提示原因。
- Linux DEB 会检查和提醒新版本，确认后进入官网下载页，通过系统安装器更新。

旧 alpha.1 / alpha.2 还没有更新功能，需要先手动安装本版本一次。

这是 Alpha 测试版。更新包签名用于验证来源，不等于 Windows 发行者签名或 macOS Developer ID 公证；系统仍可能提示未知发布者。当前为系统代理，暂不支持 TUN；Linux 自动代理仅覆盖 GNOME/gsettings。跨系统真实安装升级和长期网络体验仍需试用验收。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
