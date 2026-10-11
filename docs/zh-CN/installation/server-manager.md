# 服务器快捷管理命令

在服务器终端输入 `xboard`，即可选择更新、重启、启动、停止、查看状态、查看日志或卸载服务。

## 安装一次

当前生产项目目录为 `/root/Xboard`，Compose 服务名为 `xboard`。

仓库维护者可以在 GitHub Actions 的 **Production Deploy** 中选择 `master`，将 `operation` 设为 `install-cli` 后运行。此操作只安装命令并验证菜单和状态，不更新或重启应用。之后的 `deploy` 操作也会安装最新的管理脚本。

若服务器已有此版本的脚本，以 root 执行：

```bash
bash /root/Xboard/.docker/production/xboard.sh install
```

安装位置是 `/usr/local/bin/xboard`，重新登录仍然有效；不会覆盖同名的其他程序。脚本需要 Bash、Docker Compose v2（支持 `--wait`）、Python 3 和 `flock`。管理用户需要操作 Docker 及项目目录的权限。

## 日常操作

```text
========== Xboard 服务器管理 ==========
项目：/root/Xboard
  1. 更新 Xboard
  2. 重启 Xboard
  3. 启动 Xboard
  4. 停止 Xboard
  5. 查看状态和版本
  6. 查看最近日志
  7. 卸载服务（保留数据）
  0. 退出
```

更新会先要求确认，再拉取 Compose 配置中的镜像、执行 `xboard:update`、启动服务并检查运行镜像。拉取、迁移或启动失败会停止后续步骤，返回菜单显示错误。更新前请完成数据库备份；此命令本身不执行备份或自动数据库回滚。

请先确认 GitHub 的 **Docker Build and Publish** 已成功。更新不会合并上游源码，也不会改变 Compose 中配置的镜像仓库或标签；固定到旧标签的部署需要先选择新标签。整个 `/www` 挂载为源码目录的部署、使用 `web` 服务名的部署不适用此脚本，脚本会拒绝更新。

启动时会等待容器运行或其已有健康检查通过；没有健康检查的容器仅核验运行状态与镜像，不代表外网访问或支付流程已验收。更新失败后可先查看日志，不要仅凭容器存在判断升级成功。

卸载必须手动输入 `UNINSTALL`，只停止并移除 `xboard` 容器。不会删除挂载目录、命名卷、镜像、下载文件、项目文件或其他服务。容器内未持久化的文件会丢失；存在匿名卷时拒绝卸载，避免恢复服务后无法自动重新挂载原卷。挂载数据保留后，可通过“启动”恢复服务。此操作保留 `xboard` 命令本身。

## 可选的直接命令

```bash
xboard update
xboard restart
xboard status
xboard logs
```

自动化可对 `update`、`restart`、`start`、`stop` 添加 `--yes`；卸载不接受该参数。并发修改由项目目录内的 `.xboard-manager.lock` 互斥保护。GitHub 部署额外通过 `XBOARD_EXPECTED_REVISION` 校验镜像的提交标识。

其他安装目录可这样指定，每次调用时保持一致：

```bash
XBOARD_DIR=/opt/Xboard xboard
```

脚本只从指定项目目录查找 Compose 文件，不接受当前 shell 遗留的 `COMPOSE_FILE` 等覆盖变量，避免在其他目录启动命令时误操作。

管理脚本当前版本：`1.0.0`。使用 `xboard version` 查看已安装版本。
