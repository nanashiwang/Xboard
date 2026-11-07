# Agent Note: 节点 UDP 快速复制计数方向

Status: implemented

## Problem

落实[仅下载扣量](../../implemented/feature/2026-11-07-download-only-billing.md)前核查固定节点源码 0a29338，发现 UDP UnwrapPacketReader 使用 download、UnwrapPacketWriter 使用 upload，与普通 ReadPacket/WritePacket 相反。此外 sing v0.8.2 在提取写计数器前先解包 replaceable writer，导致 trackedPacketConn 写回调被绕过。入口扩展运行文件哈希与保留的同版本源码构建产物一致；日本节点实查同一旧哈希并 active。其余节点需逐台核验，美国02保存连接在第一跳认证失败，随后经用户提供的既有跳板恢复美国02登录。

## Decision

固定依赖与生产构建标签，叠加小范围补丁：读回调计上传、写回调计下载，UDP WriterReplaceable 返回 false，让 sing 提取计数回调再解包。保留现有首用户启动补丁、原始双向统计、限速与连接生命周期。先逐节点备份、升级、验证，再切换面板下载计费。

## Related decisions

已检索现有活跃笔记。下载计费笔记负责套餐口径；本篇只负责节点字节方向。统计事务修复解决队列部分提交，不覆盖节点计量。没有需合并或拒绝的同类提案。

## Alternatives considered

- 面板直接交换所有 UDP 字段无法区分 TCP 和普通 UDP 路径，且无法恢复被漏记的下载，拒绝。
- 升级整个上游或代理核心会扩大路由与协议变更，采用固定版本补丁。
- 只测试计数回调会漏掉 replaceable writer 被跳过，使用真实 sing bufio.CopyPacket，并与普通路径交叉验证。

## Verification

原版本真实复制回归复现上传进入 download、下载为零；修复后普通/快速复制、上传/下载、有/无限速 8 组合通过，singbox/tracker/service 三包 race 检测通过。固定源码叠加两补丁完整构建成功，产物 SHA256 f002b9f882cc282911e6113c50d8f36a83cf77e2f558bd3104321a4cd104f6eb。GitHub 节点 CI 42363366636 通过，附件下载哈希与本地完全一致。只读安装器在入口扩展实测成功。逐节点生产升级及面板切换待完成。

## Consequences

修正后部分此前漏记的 UDP 下载会按真实字节记录；不能将此 bug 解释为所有流量四倍，也不能凭当前日志回算历史真实下载。节点重启会短暂中断该节点连接，逐台处理并保留回退文件。
