卡皮巴拉 0.1.10 正式版

- 修复切换规则与全局模式时，节点跳回该模式旧选择的问题；切换后继续使用此前选中的节点。
- 切到直连再切回时保留节点选择；多分流组只同步首页当前组，不覆盖其他组的选择。
- 模式和节点一起应用并由内核确认，保存失败时恢复原模式与节点，避免显示成功却使用其他出口。
- 保留点击节点即可连接/切换，以及 Windows 本机代理例外修复。

自动选择组仍按其策略调整出口；若规则组不包含当前全局节点，会明确提示，需先选择该组支持的节点。模式切换影响新连接，已有连接可能继续使用原出口。

不含 TUN。Linux 自动代理覆盖 GNOME，DEB 使用系统安装器升级。更新签名不等同于 Windows 发行者签名或 macOS Developer ID 公证。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
