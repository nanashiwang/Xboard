# 第三方组件与来源

卡皮巴拉桌面端原创代码以 GPL-3.0-only 发布。版权 © 2026 nanashiwang。

- Mihomo v1.19.33：MetaCubeX 与其贡献者，GPL-3.0。保留 [完整许可证](LICENSE.mihomo)；[对应源代码](https://github.com/MetaCubeX/mihomo/tree/v1.19.33)。本应用使用未经修改的官方发布内核，六种目标的资产名称、下载地址与官方 SHA-256 摘要见 core-assets.json。
- GeoIP 数据：来自 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)，随项目保留 GPL-3.0 许可证。2026-10-23 的 geoip.metadb 发布资产 ID 667543853，SHA-256 `646d077cc2b43a8abf1b853006f0ac29f03263a1656ba8c247aa621ebcf94c66`。数据库随源码保存，以避免首次连接依赖 GitHub 下载；请同时遵循该项目列出的数据来源许可与归属。
- Tauri 与插件：MIT / Apache-2.0；React、Vite、Lucide：各组件的 MIT/ISC 许可，完整版本依赖由 Cargo.lock / package-lock.json 固定。
- 卡皮巴拉吉祥物和图标为本任务通过内置图像生成工具生成的原创品牌图像，无第三方品牌标识。提示词与图片用途见 BRAND.md。

源代码及构建说明：https://github.com/nanashiwang/Xboard/tree/master/desktop/capybara 。测试版不具备自动更新签名、Windows 代码签名或 macOS Developer ID 公证；更新经用户前往 Release 手动安装。
