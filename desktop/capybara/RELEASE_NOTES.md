卡皮巴拉的第一版桌面测试客户端，使用蓝围巾旅行水豚首页与蓝色地球头像图标，提供 Windows x64、macOS Apple Silicon / Intel、Ubuntu GNOME x64 安装包。

- 登录后每 30 秒同步套餐与流量，区分流量耗尽、到期、离线和线路错误；耗尽与到期会暂停连接。
- 一键开启系统代理、按规则分流、手动选择线路和连通检测；连接前核对资格，每小时更新节点配置，失败保留上次可用配置。
- 密码不落盘，续期令牌存放系统凭据库；代理内核由独立进程管理，主应用退出时恢复代理。
- 内置固定版本 Mihomo 和地理规则数据，安装包及源码提供 SHA-256 清单。

这是用于验证的 Alpha 测试版。首版采用系统代理，不含 TUN；Linux 自动代理仅支持 GNOME/gsettings。未配置 Windows 代码签名、macOS Developer ID 公证和签名自动更新；系统可能提示未知发布者。macOS 安装包只做构建签名，不代表公证通过。

真实账号登录、三种系统的代理权限、安装升级、休眠恢复及实际网络环境仍需试用验收。后端 X-Core-Version 支持需部署配套服务端变更；本次发布不部署网站、不替换已有第三方客户端。

使用前先关闭其他代理应用的系统代理。安装、源码与已知边界见 [客户端说明](https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara)。内核对应源码见 [Mihomo v1.19.33](https://github.com/MetaCubeX/mihomo/tree/v1.19.33)。
