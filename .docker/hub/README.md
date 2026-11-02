# 卡皮巴拉导航发布源

`build.py` 将已确认的导航布局及当前安装包清单生成独立静态网站。正式产物仅包含导航、下载页、样式、图标和 SHA256SUMS，不发布模拟登录或预览脚本。应用按钮指向 `https://capybarago.uk/`；下载提供应用域文件和独立 GitHub Release 备用地址，导航渲染不依赖应用 API。

```sh
python3 .docker/hub/build.py /absolute/site-checkout/dist
```

`hosting.json` 记录既有 Sites 项目身份，重新发布必须复用它：复制到独立站点 checkout 的 `.openai/hosting.json`，用 Sites 的 source helper 完成源码提交、归档和版本发布。不要重新创建 Site，不保存仓库令牌。导航按公开、无需登录的用户访问模式发布；正式域名 `capybarahub.fyi` 的验证记录由 Sites 返回。

应用域使用 [独立入口配置](../production/configure-go-domain.py) 和 [手动工作流](../../.github/workflows/configure-go-domain.yml)，生产应用镜像仍走既有 Production Deploy。导航更新和应用部署分开验收；GitHub 下载备用路径也可能受用户网络影响，不构成客户端自动恢复。
