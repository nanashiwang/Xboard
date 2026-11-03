# 卡皮巴拉导航发布源

`build.py` 将已确认的导航布局及当前安装包清单生成独立静态网站。正式产物包含导航、下载页、样式、图标、邀请码传递脚本和 SHA256SUMS，不发布模拟登录或预览脚本。应用按钮指向 `https://capybarago.uk/`；下载提供应用域文件、Hub 分发地址和独立 GitHub Release 地址，导航渲染不依赖应用 API。

```sh
python3 .docker/hub/build.py /absolute/output/dist
```

生产使用既有 Cloudflare 账户下的 Pages 项目 `capybarahub`，通过 Direct Upload 发布构建目录中的全部文件，生产分支为 `main`。重新发布须复用同一项目；可以将 dist 内容压缩为 ZIP 后在项目的「创建部署」中上传，不要把 dist 外层目录或仓库源码一起上传。`hosting.json` 是项目和已验收部署的公开运维记录，不是 Sites 配置，也不含访问令牌。

正式域名 [capybarahub.fyi](https://capybarahub.fyi/) 通过 Pages 自定义域绑定，CNAME `@ → capybarahub.pages.dev`；控制台已显示「活动 / SSL 已启用」。发布后分别验收根页、downloads.html、SHA256SUMS.txt、应用链接和实际安装包来源。上线不发布模拟登录页，也不要求导航用户登录。回退使用 Pages 的已成功生产部署；不要删除项目或域名来回退。

首次尝试 Sites 时归档上传失败，未产生版本或公开部署，已改用 Pages；该私有草稿不是生产依赖。后续不要按旧 Sites 项目身份重复部署。

应用域使用 [独立入口配置](../production/configure-go-domain.py) 和 [手动工作流](../../.github/workflows/configure-go-domain.yml)，生产应用镜像仍走既有 Production Deploy。`promote` 仅在 HTTPS 与接口验证后切换 app_url/subscribe_url，`rollback-settings` 恢复原公开地址；旧域 vhost、支付回调和节点配置保留。导航更新、应用部署和国内直连可达性分别验收；GitHub 下载备用路径也可能受用户网络影响，不构成客户端自动恢复。

邀请链接使用 `https://capybarahub.fyi/?invite=邀请码`，只接收8位字母数字邀请码。导航保持停留，点击应用入口时转到对应应用域的注册页；下载页与返回导航保留邀请码，不向安装包/GitHub链接附加参数。无效参数忽略，目标只允许Go、备用应用域和旧taige，未将订阅token放进导航。旧站入口及兼容索引继续保留；旧客户端设置no_proxy，系统HTTP代理不保证覆盖其更新请求，须确认目标实际经代理可达或从导航覆盖安装。

## 0.1.14 恢复分发

`build.py OUTPUT --release-directory VERIFIED_RELEASE_FILES`核对发布清单摘要后复制`capybara-hub.json`和`capybara-entrypoints.json`，并生成`_worker.js`与`_routes.json`。Cloudflare Pages控制台Direct Upload支持此单文件Worker；恢复JSON走静态存储、no-store，安装包由Worker限制到既有清单中的GitHub固定版本来源，禁止Go依赖、任意代理及用户凭据转发。上传ZIP必须包含所有静态文件、Worker、路由和恢复JSON。

备用官网为`https://app.capybarahub.fyi/`，源站部署由Configure Hub Domain流程管理。更新入口清单时先部署并验收新服务域，修改`desktop/capybara/service-entrypoints.json`的origins、递增sequence、调整签发/到期时间，再通过已有签名流水线发布和同步；客户端拒绝未签名、过期及回退内容。发行私钥不进入Hub或应用服务器。见[恢复决定](../../.agents/notes/implemented/architecture/2026-11-03-client-hub-recovery.md)。
