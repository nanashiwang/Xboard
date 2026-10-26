# Windows 连接诊断

适用于卡皮巴拉 0.1.5：同一节点在 v2rayN 可用，而卡皮巴拉显示不可达、超时或连接失败时，采集本机证据。脚本只做诊断，不代表已修复连接问题。

1. 保持卡皮巴拉已登录、节点已显示；保留发生问题时的模式和所选节点。退出其他代理客户端。
2. 下载 [diagnose-windows.ps1](./diagnose-windows.ps1)，在其所在目录打开 PowerShell，运行：

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\diagnose-windows.ps1
   ```

3. 等待约 1–2 分钟，将桌面上的 `Capybara-diagnostic-日期时间.json` 发给维护者。无需管理员权限。命令中的 ExecutionPolicy 只作用于这次 PowerShell 进程，不修改系统策略；若组织策略禁止执行脚本，请停止并联系维护者。

默认检查“美国01”。其他节点可追加 `-NodeMatch '日本01'`；必须唯一匹配，匹配多条时不会擅自选一个。不要提供订阅链接、密码、UUID、`runtime.yaml` 或原始日志。桌面不可写时可用 `-OutputPath` 指定其他报告路径。

检查包括：回环控制器鉴权、内核版本、本地端口、Windows 系统代理是否指向该端口、相关进程数量、当前分流和节点选择、节点入口 TCP/HTTPS、两个国内 DoH 服务的 HTTPS 可达性、Google 5 秒/12 秒及 Cloudflare 12 秒节点 HTTP 检测、当前所选出口的实际代理请求。DoH HTTPS 返回 400 等响应只证明到达服务，不能代替 DNS 解析成功。直接入口 HTTPS 检查使用入口主机名，不带节点凭据或 WebSocket 路径；非标准 SNI 的其他节点需另查。

报告只保存白名单状态及固定错误类别；控制器秘密只在内存中用于 127.0.0.1 请求，禁止重定向。内核警告仅归类计数，不写原文；同时间其他连接也可能产生日志，不把它们全部归因于探针。测速会更新内核临时延迟历史并消耗少量流量，但不改配置、系统代理、选择项、分流模式、证书校验或防火墙。最终“current_selection_proxy”使用当前出口，可能与被测节点不同，请结合“selected_groups”判断。

测试：Windows PowerShell 5.1 运行 `./test-diagnostics.ps1`；本机 PowerShell 7 可运行同一测试。CI 使用 Windows 原生 5.1，不把跨平台脚本测试当成用户 Windows 网络已验收。
