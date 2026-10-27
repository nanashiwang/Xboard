卡皮巴拉 0.1.9 正式版

- 修复 Windows 系统代理启用后，本机请求也可能进入全局代理，导致 Codex 调用 YuanHeng 的 127.0.0.1:15721 端口返回 502 Unknown error 的问题。
- 为 localhost、127.0.0.1 和 IPv6 本机地址补齐明确的代理例外；保留用户原有例外，外网请求继续使用所选代理。
- 断开及退出时恢复原代理例外，兼容旧版本恢复记录；运行中被用户修改的例外保持用户的新值。
- 保留 0.1.8 的 Windows 代理地址兼容修复，以及点击节点即可连接/切换的交互。

Windows 更新后请断开再连接，让新代理例外生效，再重试 Codex。此次修复已针对网络库和本地回环链路验证；用户故障电脑仍需安装后复验。应用自行设置的环境代理或NO_PROXY按应用自身规则处理。

不含 TUN。Linux 自动代理覆盖 GNOME，DEB 使用系统安装器升级。更新签名不等同于 Windows 发行者签名或 macOS Developer ID 公证。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
