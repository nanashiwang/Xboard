卡皮巴拉 0.1.0-alpha.10 简化账号登录弹窗。

- 移除登录及注册弹窗底部重复的“取消”按钮，界面更简洁。
- 保留右上角关闭按钮和 Esc 取消授权；账号登录、注册与授权返回流程不变。
- 保留套餐购买和支付、自动更新、流量同步及系统代理能力。

本次仅更新客户端界面，无需更新官网授权接口。更换临时签名构建后可能需要重新授权一次。

Alpha 不含 TUN；Linux 自动代理仅覆盖 GNOME；更新签名不等于 Windows 发行者签名或 macOS Developer ID 公证。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
