卡皮巴拉 0.1.0-alpha.11 更新首页与节点选择体验。

- 首页采用蓝色山水、旅行水豚插画和大圆形连接按钮，连接状态更醒目。
- 移除侧栏独立“线路”页面，节点列表直接放在首页右侧，支持搜索、地区筛选和分流组切换。
- 当前节点、剩余流量、同步时间和连接检测集中展示；连接后读取真实节点，不展示未经测量的延迟或速度。
- 适配明暗主题和窄窗口，保留耗尽、到期、登录恢复和连接错误提示。
- 保留浏览器登录与注册、套餐购买、账户、系统代理和签名更新能力。

本次不改变服务端接口与数据库。Alpha 不含 TUN；Linux 自动代理仅覆盖 GNOME；更新签名不等于 Windows 发行者签名或 macOS Developer ID 公证。

客户端说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara
内核源码：https://github.com/MetaCubeX/mihomo/tree/v1.19.33
