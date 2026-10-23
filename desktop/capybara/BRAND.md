# 卡皮巴拉品牌图像

2026-10-23 根据用户提供的两张参考图更新：第一张戴蓝围巾、背旅行包的完整水豚用于首页，第二张蓝色地球背景的水豚头像用于桌面图标。保留角色面容、背包、围巾和盾牌锁扣，使用浅蓝、暖白与焦糖棕配色，深色主题采用深蓝灰。连接操作与账号异常提示保持优先可见。

- `public/capybara.png`：1254 × 1254，真实透明背景，首页、登录页与空状态共用。移除原图白底，保留完整坐姿与毛发轮廓。
- `public/capybara-icon.png`：1254 × 1254，保留圆角蓝色地球图案，图标外部透明。侧栏、网页图标和桌面图标使用同一源图。
- `src-tauri/icons/`：通过 `npm run tauri -- icon public/capybara-icon.png` 生成 macOS ICNS、Windows ICO 和 Linux PNG；移除本任务未使用的 Android/iOS 输出。

使用内置 image_gen 编辑用户参考图片，不经 API/CLI 回退；输出已复制到工程，应用不依赖聊天临时文件。旧绿叶水豚素材被本次明确指定的新形象替换，历史版本可通过 Git 获取。图像编辑仅提取背景与改善边缘，布局和主题通过应用 CSS 适配。

## 首页图片编辑提示词

> Use case: background-extraction. Asset type: homepage mascot cutout for Capybara desktop app. Edit the supplied image: remove only the pale white background, including opaque ground, to genuine transparent alpha. Preserve this exact adorable golden furry capybara's face, upward gaze, seated pose, full body, blue scarf, shield with white padlock, blue travel backpack with brown straps and rolled sleeping mat. Keep the reference character and high-quality soft 3D render style, no redesign, no extra objects, no text. Refine fine fur and whisker edges so they blend cleanly on both light and dark UI backgrounds, no white fringe. The entire capybara, feet and backpack must fit within a square 1024x1024 canvas with small comfortable transparent margin. Minimal subtle translucent contact shadow only. Optimize silhouette clarity at 340px display size. Output one square transparent PNG.

## 桌面图标编辑提示词

> Use case: background-extraction. Asset type: desktop app icon, Windows macOS Linux. Edit target is the supplied icon. Preserve the exact golden capybara face and expression, blue scarf, shield padlock, blue rounded square tile and blue globe/network orbit illustration INSIDE the tile. Remove ONLY the white exterior background outside the rounded square to genuinely transparent alpha; remove exterior diffuse white/blue shadow so tile edges are crisp and clean. Do not make the inside of the tile transparent. Do not redesign or change the capybara. Keep the blue rounded tile nearly filling the square canvas with uniform ~5 percent transparent margin; centered and not cropped. Simplify no character features. No text, no additional badges, no white rectangular background. Output square 1024x1024 PNG with true alpha outside tile, ready to convert to .icns and .ico.

工具实际保留了参考图的 1254 × 1254 尺寸；Tauri 按平台要求生成各档分辨率。已核对 PNG alpha、32/64/128px 图标、浅色与深色首页、760 × 620 小窗口以及本地 macOS 打包签名。构建签名不代表 Developer ID 公证。
