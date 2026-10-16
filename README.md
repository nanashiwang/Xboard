# Xboard

<div align="center">

[![Telegram](https://img.shields.io/badge/Telegram-Channel-blue)](https://t.me/XboardOfficial)
![PHP](https://img.shields.io/badge/PHP-8.2+-green.svg)
![MySQL](https://img.shields.io/badge/MySQL-5.7+-blue.svg)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

## 📖 Introduction

Xboard is a modern panel system built on Laravel 12, focusing on providing a clean and efficient user experience.

## ✨ Features

- 🚀 Built with Laravel 12 + Octane for significant performance gains
- 🎨 Redesigned admin interface (React + Shadcn UI)
- 📱 Modern user frontend (Vue3 + TypeScript)
- 🐳 Ready-to-use Docker deployment solution
- 🎯 Optimized system architecture for better maintainability

## 项目能力核对与进展记录

本仓库已接入 **project-decision-kit v1.0.1**。修改前先核对已有入口、权限、接口和数据来源，再记录真实方案取舍与验证结果。

- [能力地图](./docs/FEATURE_MAP.md)：按当前代码定位可复用能力、权限边界和相关检查。
- [进展记录](./progress-log.md)：保存项目反馈、排查结论、方案取舍、后续行动及验证结果。
- [决策笔记说明](./docs/AGENT_NOTES.md)与[本次接入决策](./.agents/notes/implemented/process/2026-10-17-project-decision-kit.md)：说明记录方式、工具来源和维护边界。
- 工具源码：[nanashiwang/new-api · scripts/agent-workflow/](https://github.com/nanashiwang/new-api/tree/project-decision-kit-v1.0.1/scripts/agent-workflow)；[v1.0.1 Release](https://github.com/nanashiwang/new-api/releases/tag/project-decision-kit-v1.0.1)。该版本号属于工具包。

### 当前反馈与结论（2026-10-17）

用户要求让项目反馈和验证证据随 GitHub 仓库保存，并在完成后回读核对。排查确认：已有业务代码和运维文档可复用，原先缺少统一能力索引及笔记校验；`composer.json` 使用 Laravel 12，本文两处 Laravel 11 的旧说明已修正。

采用“README 当前摘要 + progress-log 逐次证据 + 原有笔记树记录决策”的方式，补全能力地图，并使用独立的 `Agent Workflow Notes` CI。选择独立校验是为了让笔记检查不依赖 PHP 服务、数据库或 Docker 镜像构建；具体备选及代价见接入决策。

工具包下载、完整性、笔记结构、6 项校验行为和 105 个文档链接检查均通过；[笔记 CI](https://github.com/nanashiwang/Xboard/actions/runs/38975255703) 与[双架构镜像构建](https://github.com/nanashiwang/Xboard/actions/runs/38975255672)均成功，GHCR 的 amd64/arm64 镜像 revision 与实施提交 `015240b` 一致。首次推送后已从 GitHub 完整回读 README 与 progress-log，内容与提交一致。详细证据和后续事项见[进展记录](./progress-log.md)。后续每次改动需同步相关记录，并执行：

```bash
python3 .agents/workflow.py doctor
python3 .agents/workflow.py verify
```

运行需要 Python 3.9+ 和 Bun（CI 固定 1.3.14）；新电脑克隆仓库即可获得校验器，无需全局 Skill。现有 Docker 工作流会在推送主分支时构建镜像，生产部署需单独手动触发。仓库目前没有 GitHub Release 与安装包发布流程；本次仅接入工具和文档，未执行生产部署。

## 🚀 Quick Start

```bash
git clone -b compose --depth 1 https://github.com/cedar2025/Xboard && \
cd Xboard && \
docker compose run -it --rm \
    -e ENABLE_SQLITE=true \
    -e ENABLE_REDIS=true \
    -e ADMIN_ACCOUNT=admin@demo.com \
    web php artisan xboard:install && \
docker compose up -d
```

> After installation, visit: http://SERVER_IP:7001  
> ⚠️ Make sure to save the admin credentials shown during installation

## 📖 Documentation

### 🔄 Upgrade Notice
> 🚨 **Important:** This version involves significant changes. Please strictly follow the upgrade documentation and backup your database before upgrading. Note that upgrading and migration are different processes, do not confuse them.

### Development Guides
- [Plugin Development Guide](./docs/en/development/plugin-development-guide.md) - Complete guide for developing XBoard plugins

### Deployment Guides
- [服务器快捷管理菜单（中文）](./docs/zh-CN/installation/server-manager.md) - 输入 `xboard` 更新、重启、查看状态或卸载服务
- [Deploy with 1Panel](./docs/en/installation/1panel.md)
- [Deploy with Docker Compose](./docs/en/installation/docker-compose.md)
- [Deploy with aaPanel](./docs/en/installation/aapanel.md)
- [Deploy with aaPanel + Docker](./docs/en/installation/aapanel-docker.md) (Recommended)

### Migration Guides
- [Migrate from v2board dev](./docs/en/migration/v2board-dev.md)
- [Migrate from v2board 1.7.4](./docs/en/migration/v2board-1.7.4.md)
- [Migrate from v2board 1.7.3](./docs/en/migration/v2board-1.7.3.md)

## 🛠️ Tech Stack

- Backend: Laravel 12 + Octane
- Admin Panel: React + Shadcn UI + TailwindCSS
- User Frontend: Vue3 + TypeScript + NaiveUI
- Deployment: Docker + Docker Compose
- Caching: Redis + Octane Cache

## 📷 Preview
![Admin Preview](./docs/images/admin.png)

![User Preview](./docs/images/user.png)

## ⚠️ Disclaimer

This project is for learning and communication purposes only. Users are responsible for any consequences of using this project.

## ❤️ Support The Project

If this project has helped you, donations are appreciated. They help support ongoing maintenance and would make me very happy.

TRC20: `TLypStEWsVrj6Wz9mCxbXffqgt5yz3Y4XB`

## 🌟 Maintenance Notice

This project is currently under light maintenance. We will:
- Fix critical bugs and security issues
- Review and merge important pull requests
- Provide necessary updates for compatibility

However, new feature development may be limited.

## 🔔 Important Notes

1. Restart required after modifying admin path:
```bash
docker compose restart
```

2. For aaPanel installations, restart the Octane daemon process

## 🤝 Contributing

Issues and Pull Requests are welcome to help improve the project.

## 📈 Star History

[![Stargazers over time](https://starchart.cc/cedar2025/Xboard.svg)](https://starchart.cc/cedar2025/Xboard)
