卡皮巴拉 0.1.11 正式版

- 修复部分办公网站域名解析到内网地址后，仍被送往代理出口而无法访问的问题；客户端自动识别内网地址，无需手工修改 Windows 代理例外。
- 全局模式现在让公网流量走已选节点，内网自动直连；规则模式继续优先遵循用户自定义规则。
- 直连默认使用系统 DNS，保留订阅中显式指定的直连解析与公网 DNS 策略。
- 保留切换规则、全局和直连时的节点选择，以及配置失败时的完整回退。

仅企业 DNS 能解析的私有域名可能仍需添加直连规则。本次已通过隔离内核回归；不同公司网络的实际效果仍需升级后验证。模式作用于新连接，更新后请断开再连接，并重新打开原网页。

不含 TUN。Linux 自动代理覆盖 GNOME，DEB 使用系统安装器升级。更新签名不等同于 Windows 发行者签名或 macOS Developer ID 公证。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
