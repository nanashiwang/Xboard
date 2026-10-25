# 卡皮巴拉品牌图像

2026-10-23 根据用户提供的两张参考图更新：第一张戴蓝围巾、背旅行包的完整水豚用于首页，第二张地球背景的水豚头像用于桌面图标。2026-10-25 按用户反馈将图标改为蓝绿色满幅底色，保留角色面容、蓝围巾和盾牌锁扣。应用继续使用浅蓝、暖白与焦糖棕配色，深色主题采用深蓝灰。连接操作与账号异常提示保持优先可见。

- `public/capybara.png`：1254 × 1254，真实透明背景，首页、登录页与空状态共用。移除原图白底，保留完整坐姿与毛发轮廓。
- `public/capybara-icon.png`：1254 × 1254，蓝绿色地球背景铺满不透明正方形，不预切圆角、不留透明边距。侧栏、应用网页图标和桌面图标使用同一源图；官网自己的 WebP 副本独立维护。
- `src-tauri/icons/`：通过 `npm run tauri -- icon public/capybara-icon.png` 生成 macOS ICNS、Windows ICO 和 Linux PNG；移除本任务未使用的 Android/iOS 输出。

使用内置 image_gen 编辑用户参考图片，不经 API/CLI 回退；输出已复制到工程，应用不依赖聊天临时文件。旧绿叶水豚素材及旧透明圆角图标可通过 Git 获取。

macOS 26.5 Finder 实测会将旧透明圆角图缩小置于灰色底板。新源图将蓝绿色背景铺满正方形，交由系统处理圆角；Finder 独立预览已确认不再出现灰色外框。此方式遵循 [Apple 图标规范](https://developer.apple.com/design/human-interface-guidelines/app-icons)关于方形、满幅不透明背景的指导，沿用已有 ICNS/ICO/PNG 流程，不引入 Icon Composer 或更改用户系统外观。侧栏不再对新满幅图额外放大。

## 首页图片编辑提示词

> Use case: background-extraction. Asset type: homepage mascot cutout for Capybara desktop app. Edit the supplied image: remove only the pale white background, including opaque ground, to genuine transparent alpha. Preserve this exact adorable golden furry capybara's face, upward gaze, seated pose, full body, blue scarf, shield with white padlock, blue travel backpack with brown straps and rolled sleeping mat. Keep the reference character and high-quality soft 3D render style, no redesign, no extra objects, no text. Refine fine fur and whisker edges so they blend cleanly on both light and dark UI backgrounds, no white fringe. The entire capybara, feet and backpack must fit within a square 1024x1024 canvas with small comfortable transparent margin. Minimal subtle translucent contact shadow only. Optimize silhouette clarity at 340px display size. Output one square transparent PNG.

## 旧版桌面图标编辑提示词（2026-10-23）

> Use case: background-extraction. Asset type: desktop app icon, Windows macOS Linux. Edit target is the supplied icon. Preserve the exact golden capybara face and expression, blue scarf, shield padlock, blue rounded square tile and blue globe/network orbit illustration INSIDE the tile. Remove ONLY the white exterior background outside the rounded square to genuinely transparent alpha; remove exterior diffuse white/blue shadow so tile edges are crisp and clean. Do not make the inside of the tile transparent. Do not redesign or change the capybara. Keep the blue rounded tile nearly filling the square canvas with uniform ~5 percent transparent margin; centered and not cropped. Simplify no character features. No text, no additional badges, no white rectangular background. Output square 1024x1024 PNG with true alpha outside tile, ready to convert to .icns and .ico.

工具实际保留了参考图的 1254 × 1254 尺寸；Tauri 按平台要求生成各档分辨率。已核对 PNG alpha、32/64/128px 图标、浅色与深色首页、760 × 620 小窗口以及本地 macOS 打包签名。构建签名不代表 Developer ID 公证。

## 蓝绿色桌面图标编辑提示词（2026-10-25）

> Use case: precise-object-edit. Edit the provided Capybara app icon. Keep this exact golden furry capybara face, upward gaze, blue scarf, white padlock shield, and subtle globe/network illustration. Replace the rounded blue tile with a FULL-BLEED OPAQUE SQUARE background, edge to edge, in vivid turquoise/teal-blue, a smooth gradient from #23BBD0 at top to #087EA4 at bottom. Extend the globe background to all four canvas edges. No rounded tile, no inset rounded rectangle, no border, no frame, no transparent margins, no external shadow, no gray or white plate behind it. The entire square canvas including corners must be colored and opaque; macOS will apply the rounded corners itself. Preserve character identity and premium 3D rendering. Keep the full face and ears inside a centered safe area, scarf cropped at bottom. Increase character prominence to occupy about 78% of the canvas. Do not add text, badges, objects or watermark. Output one 1024x1024 square opaque PNG desktop application icon.

实际输出保持参考图 1254 × 1254，PNG 无 alpha 通道；Tauri 生成的各尺寸仍可带全不透明 alpha 通道。应用安装包与发布验收见[进展记录](../../progress-log.md#2026-10-25卡皮巴拉蓝绿色桌面图标)。
