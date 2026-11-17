/* Local-only interaction prototype. Addresses use documentation ranges; credentials are fictitious. */
(() => {
    "use strict";
    const paths = {
        grid: "M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z",
        globe: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M3 12h18 M12 3c-5 5-5 13 0 18 5-5 5-13 0-18",
        arrow: "M5 12h14 M14 7l5 5-5 5",
        back: "M19 12H5 M10 7l-5 5 5 5",
        copy: "M9 9h12v12H9z M15 5V3H3v12h2",
        plus: "M12 5v14 M5 12h14",
        refresh: "M20 7a9 9 0 1 0 1 8 M20 3v5h-5",
        search: "M17 17l5 5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
        clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M12 6v6l4 2",
        shield: "M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z M8 12l3 3 5-6",
        chart: "M4 3v18h18 M8 15l4-5 4 3 5-8",
        download: "M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4",
        settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
        help: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0 M9 9a3 3 0 0 1 6 0c0 2-3 2-3 4 M12 17h.01",
        bell: "M5 17h14l-2-3V9a5 5 0 0 0-10 0v5z M10 21h4",
        monitor: "M3 4h18v13H3z M8 21h8 M12 17v4",
        power: "M12 2v10 M6 5a9 9 0 1 0 12 0",
        eye: "M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12 M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0",
        x: "M6 6l12 12 M18 6L6 18",
        check: "M4 12l5 5L20 6",
        key: "M14 10l7 7 M17 13l-3 3 M19 15l-3 3 M14 7a5 5 0 1 1-10 0 5 5 0 0 1 10 0",
    };
    const icon = (n) =>
        `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[n] || paths.globe}"/></svg>`;
    const esc = (s) =>
        String(s).replace(
            /[&<>"']/g,
            (c) =>
                ({
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;",
                })[c],
        );
    const epoch = Date.parse("2026-11-18T00:00:00+08:00");
    const proxies = [
        {
            id: "p01",
            name: "美国 · 工作专用",
            number: "PX-10001",
            ip: "203.0.113.10",
            port: 20001,
            user: "demo_user_01",
            password: "Demo-only-01!",
            expires: epoch + 19 * 86400000,
            used: 19.47,
            status: "active",
            protocol: "SOCKS5",
        },
        {
            id: "p02",
            name: "美国 · 浏览器环境",
            number: "PX-10002",
            ip: "203.0.113.10",
            port: 20002,
            user: "demo_user_02",
            password: "Demo-only-02!",
            expires: epoch + 3 * 86400000,
            used: 8.26,
            status: "active",
            protocol: "HTTP",
        },
        {
            id: "p03",
            name: "美国 · 新代理",
            number: "PX-10003",
            ip: "",
            port: null,
            user: "",
            password: "",
            expires: null,
            used: null,
            status: "pending",
            protocol: "SOCKS5",
        },
        {
            id: "p04",
            name: "美国 · 备用环境",
            number: "PX-10004",
            ip: "203.0.113.10",
            port: 20004,
            user: "demo_user_04",
            password: "Demo-only-04!",
            expires: epoch - 4 * 86400000,
            used: 32.81,
            status: "expired",
            protocol: "SOCKS5",
        },
    ];
    const state = {
        filter: "all",
        query: "",
        sort: "default",
        selected: new Set(),
        reveal: false,
        clientId: "p01",
        clientQuery: "",
        connection: "off",
        scenario: "normal",
        chart: "30",
        toastTimer: null,
        connectionTimer: null,
    };
    const app = document.querySelector("#app"),
        dialog = document.querySelector("#dialog");
    let returnFocus = null;
    const days = (p) => Math.ceil((p.expires - epoch) / 86400000);
    const due = (p) => p.status === "active" && days(p) <= 7;
    const date = (p) =>
        p.expires
            ? new Intl.DateTimeFormat("zh-CN", {
                  year: "numeric",
                  month: "2-digit",
                  day: "2-digit",
                  timeZone: "Asia/Shanghai",
              })
                  .format(p.expires)
                  .replaceAll("/", "-")
            : "开通后开始计时";
    const status = (p) =>
        p.status === "pending"
            ? ["待开通", "blue"]
            : p.status === "expired"
              ? ["已到期", "gray"]
              : due(p)
                ? ["即将到期", "amber"]
                : ["可用", "green"];
    const badge = (p) =>
        `<span class="badge ${status(p)[1]}"><i></i>${status(p)[0]}</span>`;
    const current = () =>
        proxies.find((p) => p.id === (location.hash.split("/")[1] || "p01")) ||
        proxies[0];
    const page = () =>
        location.hash.startsWith("#client")
            ? "client"
            : location.hash.startsWith("#detail")
              ? "detail"
              : "overview";
    const button = (label, action, ic = "", cls = "", extra = "") =>
        `<button class="btn ${cls}" data-action="${action}" ${extra}>${ic ? icon(ic) : ""}${label}</button>`;
    const tiny = (label, action, ic, extra = "") =>
        `<button class="icon-btn" aria-label="${label}" title="${label}" data-action="${action}" ${extra}>${icon(ic)}</button>`;
    const protocol = (p) =>
        `<div class="protocol" role="group" aria-label="连接协议">${["SOCKS5", "HTTP"].map((v) => `<button class="${p.protocol === v ? "selected" : ""}" aria-pressed="${p.protocol === v}" data-action="protocol" data-id="${p.id}" data-value="${v}">${v}</button>`).join("")}</div>`;
    const sidebar = (client) =>
        `<aside class="sidebar"><a class="brand" href="#overview"><img src="assets/icon.webp" alt=""><span>卡皮巴拉<small>CAPYBARA</small></span></a><div><p class="nav-label">${client ? "我的空间" : "工作空间"}</p><nav class="sidenav" aria-label="主导航">${client ? `<button data-action="vpn">${icon("globe")}VPN 连接</button><a class="active" href="#client">${icon("grid")}我的代理<span class="count">${proxies.length}</span></a>` : `<button data-action="dashboard">${icon("grid")}总览</button><a class="active" href="#overview">${icon("globe")}我的代理<span class="count">${proxies.length}</span></a>`}<button data-action="buy">${icon("plus")}购买代理</button><button data-action="orders">${icon("clock")}订单记录</button></nav></div><div><p class="nav-label">更多</p><nav class="sidenav">${client ? "" : `<a href="#client">${icon("monitor")}桌面客户端</a>`}<button data-action="guide">${icon("help")}连接指南</button><button data-action="settings">${icon("settings")}账户设置</button></nav></div><div class="sidebar-bottom"><span class="avatar">C</span><div>预览账号<small style="display:block;margin-top:5px">仅用于设计演示</small></div></div></aside>`;
    function shell(content) {
        return `<div class="shell">${sidebar(false)}<div class="workspace"><header class="topbar"><span>工作空间 <span style="margin:0 10px">/</span><b>${page() === "detail" ? "代理详情" : "我的代理"}</b></span><div><button data-action="guide">使用帮助</button><button data-action="notice" aria-label="通知">${icon("bell")}</button><span class="avatar">C</span></div></header><main class="main">${content}</main></div></div>`;
    }
    function filtered() {
        return proxies
            .filter(
                (p) =>
                    (state.filter === "all" ||
                        (state.filter === "due" && due(p)) ||
                        state.filter === p.status) &&
                    `${p.name} ${p.number} ${p.ip}`
                        .toLowerCase()
                        .includes(state.query.toLowerCase()),
            )
            .sort((a, b) =>
                state.sort === "expiry"
                    ? (a.expires || Infinity) - (b.expires || Infinity)
                    : a.number.localeCompare(b.number),
            );
    }
    function rows() {
        return (
            filtered()
                .map(
                    (p) =>
                        `<tr><td><input type="checkbox" aria-label="选择 ${esc(p.name)}" data-select="${p.id}" ${state.selected.has(p.id) ? "checked" : ""} ${p.status === "pending" ? "disabled" : ""}></td><td><a class="proxy-name" href="#detail/${p.id}"><span class="flag">🇺🇸</span><span><b>${esc(p.name)}</b><small>${p.number} · 家宽固定 IP</small></span></a></td><td><span class="mono">${p.ip || "等待分配"}</span><span class="cell-sub">${p.port ? "端口 " + p.port : "付款成功 · 开通中"}</span></td><td><span class="badge">${p.protocol}</span></td><td>100 <small>Mbps</small><span class="cell-sub">不限流量</span></td><td>${date(p)}<span class="cell-sub">${p.status === "active" ? `剩余 ${days(p)} 天` : p.status === "pending" ? "开通成功后生效" : "续费后恢复使用"}</span></td><td>${badge(p)}</td><td><a class="text-btn" href="#detail/${p.id}">管理 ${icon("arrow")}</a></td></tr>`,
                )
                .join("") ||
            `<tr><td colspan="8"><div class="empty">${icon("search")}<p>没有找到符合条件的代理</p><button class="text-btn" data-action="clear">清除筛选</button></div></td></tr>`
        );
    }
    function overview() {
        const active = proxies.filter((p) => p.status === "active").length;
        return shell(
            `<div class="heading"><div><h1>我的代理</h1><p>固定出口，随时连接。管理你的每一条家宽代理。</p></div><div class="actions">${button("刷新", "refresh", "refresh")}${button("购买代理", "buy", "plus", "primary")}</div></div><div class="stats">${[
                [
                    "全部代理",
                    proxies.length,
                    "个",
                    "包含待开通与已到期代理",
                    "globe",
                ],
                ["可用代理", active, "个", "支持 SOCKS5 / HTTP", "shield"],
                [
                    "即将到期",
                    proxies.filter(due).length,
                    "个",
                    "未来 7 天内到期",
                    "clock",
                ],
                [
                    "本月累计用量",
                    proxies
                        .reduce((sum, p) => sum + (p.used || 0), 0)
                        .toFixed(2),
                    "GB",
                    "不限流量 · 示例统计",
                    "chart",
                ],
            ]
                .map(
                    (s, i) =>
                        `<section class="stat ${i === 2 ? "warning" : ""}"><div class="stat-top">${s[0]}${icon(s[4])}</div><strong>${s[1]}<span>${s[2]}</span></strong><small>${s[3]}</small></section>`,
                )
                .join(
                    "",
                )}</div><section class="card"><div class="toolbar"><div class="tabs" role="group" aria-label="状态筛选">${[
                ["all", "全部", proxies.length],
                ["active", "可用", active],
                ["due", "即将到期", proxies.filter(due).length],
                [
                    "pending",
                    "待开通",
                    proxies.filter((p) => p.status === "pending").length,
                ],
                [
                    "expired",
                    "已到期",
                    proxies.filter((p) => p.status === "expired").length,
                ],
            ]
                .map(
                    ([v, t, n]) =>
                        `<button class="${state.filter === v ? "selected" : ""}" aria-pressed="${state.filter === v}" data-action="filter" data-value="${v}">${t}<span>${n}</span></button>`,
                )
                .join(
                    "",
                )}</div><div class="actions"><label class="search">${icon("search")}<input id="query" aria-label="搜索代理名称、IP 或编号" placeholder="搜索名称、IP 或编号" value="${esc(state.query)}"></label><select class="sort" id="sort" aria-label="排序"><option value="default">默认排序</option><option value="expiry" ${state.sort === "expiry" ? "selected" : ""}>到期时间优先</option></select></div></div><div class="table-scroll"><table><thead><tr><th><input id="select-all" type="checkbox" aria-label="选择当前可导出的代理"></th><th>代理名称</th><th>连接地址</th><th>协议</th><th>带宽 / 流量</th><th>到期时间</th><th>状态</th><th>操作</th></tr></thead><tbody id="rows">${rows()}</tbody></table></div><div class="table-footer"><span id="row-count">共 ${filtered().length} 条代理</span><div class="actions"><span id="selected-count">已选 ${state.selected.size} 条</span>${button("导出连接信息", "export", "download", "", 'id="export" ' + (!state.selected.size ? "disabled" : ""))}</div></div></section><div class="below-grid"><section class="card offer"><div class="offer-mark">${icon("globe")}</div><div><h2>美国 · 家宽固定 IP</h2><p>最高 100 Mbps · 不限流量<br>SOCKS5 / HTTP 自由选择</p></div><div class="price">¥39<small> / 月</small></div>${button("添加代理", "buy", "plus", "soft")}</section><section class="card help-card"><h2>从一条代理开始</h2><p>复制连接信息用于浏览器或第三方工具，<br>也可以在卡皮巴拉客户端中一键连接。</p><a class="text-btn" href="#client">看看客户端 ${icon("arrow")}</a></section></div><p class="hint">${icon("shield")}独立认证 · 到期提醒 · 固定出口。此处为设计预览，地址、用量和状态均为示例。</p>`,
        );
    }
    function credential(label, value, key, p) {
        return `<div class="credential"><dt>${label}</dt><dd class="mono">${esc(value)}</dd><div class="actions">${key === "password" ? tiny(state.reveal ? "隐藏密码" : "显示密码", "reveal", "eye") : ""}${tiny("复制" + label, "copy", "copy", `data-id="${p.id}" data-key="${key}" ${p.status === "pending" ? "disabled" : ""}`)}</div></div>`;
    }
    function chart() {
        const points =
            state.chart === "30"
                ? "35,110 56,105 77,115 98,82 119,96 140,70 161,90 182,79 203,92 224,52 245,69 266,45 287,60 308,38 329,64 350,50 371,70 392,45 413,60 434,23 455,47 476,41 497,64 518,36 539,48 560,30"
                : "35,96 122,66 209,82 296,33 383,57 470,45 560,22";
        return `<svg class="chart" viewBox="0 0 580 145" role="img" aria-label="最近 ${state.chart} 天示例流量趋势，非实测数据"><defs><linearGradient id="area" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#6699ff" stop-opacity=".18"/><stop offset="1" stop-color="#6699ff" stop-opacity=".01"/></linearGradient></defs>${[20, 60, 100, 135].map((y, i) => `<path class="grid" d="M35 ${y}H575"/><text x="0" y="${y + 3}">${["3GB", "2GB", "1GB", "0"][i]}</text>`).join("")}<polygon class="area" points="35,135 ${points} 560,135"/><polyline class="line" points="${points}"/></svg><div class="chart-foot"><span>${state.chart === "30" ? "10月20日" : "11月12日"}</span><span>11月18日</span></div>`;
    }
    function detail() {
        const p = current();
        const pending = p.status === "pending";
        return shell(
            `<a class="back" href="#overview">${icon("back")}返回我的代理</a><div class="heading"><div class="detail-title"><span class="flag">🇺🇸</span><div><h1>${esc(p.name)}</h1><p>${p.number} <span style="margin:0 8px">·</span> 家宽固定 IP <span style="margin:0 8px">·</span> ${badge(p)}</p></div></div><div class="actions">${button("重命名", "rename", "", "", `data-id="${p.id}"`)}${button("在客户端使用", "use-client", "monitor", "primary", `data-id="${p.id}" ${p.status !== "active" ? "disabled" : ""}`)}</div></div><section class="card identity"><div><small>代理类型</small><b>家宽固定 IP · IPv4</b></div><div><small>出口 IP</small><b class="mono">${p.ip || "等待分配"}</b></div><div><small>国家 / 地区</small><b>🇺🇸 美国</b></div><div><small>支持的协议</small><b>SOCKS5 / HTTP</b></div></section><div class="detail-grid"><div class="column"><section class="card card-pad"><div class="section-head"><div><h2>连接信息</h2><p>选择工具支持的协议，复制后即可填写。</p></div>${protocol(p)}</div>${pending ? `<div class="empty">${icon("clock")}<p>正在为你开通代理</p><small>地址、端口和认证信息将在开通后显示。</small></div>` : `<dl class="credentials">${credential("服务器地址", p.ip, "ip", p)}${credential("端口", p.port, "port", p)}${credential("用户名", p.user, "user", p)}${credential("密码", state.reveal ? p.password : "••••••••••••••", "password", p)}</dl><div class="credentials-bottom"><div class="actions">${button("复制连接串", "copy-string", "copy", "soft", `data-id="${p.id}"`)}${button("更多格式", "formats", "", "", `data-id="${p.id}"`)}</div><button class="text-btn" data-action="reset" data-id="${p.id}">重置密码</button></div>`}<p class="hint">${icon("key")}${p.protocol === "HTTP" ? "HTTP 代理支持通过 CONNECT 访问 HTTPS 网站。" : "在支持 SOCKS5 的工具中填写服务器地址、端口和用户名密码。"} 两种协议共用本端点的认证信息。</p></section><section class="card card-pad"><div class="section-head"><h2>代理资源</h2><span class="badge blue">不限累计流量</span></div><div class="resource-grid"><div class="resource"><small>本月累计使用</small><strong>${p.used === null ? "—" : p.used}<span>GB</span></strong><p>流量统计用于了解使用情况</p></div><div class="resource"><small>带宽上限</small><strong>100<span>Mbps</span></strong><p>实际速度受线路和目标网站影响</p></div></div></section><section class="card card-pad"><div class="section-head"><div><h2>使用趋势</h2><p>上传 + 下载 · 示例数据</p></div><select id="chart-period" class="sort" aria-label="流量统计周期"><option value="30">最近 30 天</option><option value="7" ${state.chart === "7" ? "selected" : ""}>最近 7 天</option></select></div>${p.used === null ? '<div class="empty">暂无用量数据</div>' : chart()}</section></div><aside class="column"><section class="card card-pad"><div class="section-head"><h2>订阅状态</h2>${badge(p)}</div><div class="billing-price">¥39<small> / 月</small></div><div class="kv"><span>计费方式</span><b>按月付费</b></div><div class="kv"><span>到期时间</span><b>${date(p)}</b></div><div class="kv"><span>续费方式</span><b>手动续费</b></div>${button(p.status === "expired" ? "续费并恢复" : "续费代理", "renew", "", "primary full", `data-id="${p.id}" ${pending ? "disabled" : ""}`)}<p class="billing-note">${due(p) ? "还有 " + days(p) + " 天到期，建议提前续费。" : "续费沿用当前代理，不重复购买。"}</p></section><section class="card card-pad"><div class="section-head"><h2>连接检测</h2><button class="text-btn" data-action="test" data-id="${p.id}" ${p.status !== "active" ? "disabled" : ""}>测试代理</button></div><p class="muted" style="font-size:11px" id="test-result">${pending ? "开通后可检测" : "最近 30 天 · 状态示意"}</p><div class="health-bars" aria-label="示例历史状态，不代表真实可用率">${Array.from({ length: 30 }, (_, i) => `<i class="${pending || i < 3 ? "unknown" : i === 17 ? "warn" : ""}" title="${pending || i < 3 ? "暂无数据" : i === 17 ? "检测异常（示例）" : "检测成功（示例）"}"></i>`).join("")}</div><div class="health-caption"><span>30 天前</span><span>今天</span></div><p class="hint">灰色表示缺少检测数据，不计为正常。</p></section><section class="card card-pad"><h2>如何连接</h2>${[
                ["monitor", "卡皮巴拉客户端", "一键使用这条代理", "use-client"],
                ["globe", "浏览器与第三方工具", "选择 SOCKS5 或 HTTP", "guide"],
                ["help", "连接排查", "认证、端口与网络检查", "guide"],
            ]
                .map(
                    ([ic, t, s, a]) =>
                        `<button class="guide" data-action="${a}" data-id="${p.id}" ${a === "use-client" && p.status !== "active" ? "disabled" : ""}><span>${icon(ic)}<span>${t}<small>${s}</small></span></span>${icon("arrow")}</button>`,
                )
                .join("")}</section></aside></div>`,
        );
    }
    function client() {
        const p = proxies.find((p) => p.id === state.clientId) || proxies[0];
        const connected = state.connection === "on";
        const busy = state.connection === "busy";
        const list =
            state.scenario === "empty"
                ? []
                : proxies.filter(
                      (p) =>
                          p.name.includes(state.clientQuery) ||
                          p.ip.includes(state.clientQuery),
                  );
        const title = connected
            ? "已连接"
            : busy
              ? "正在连接"
              : state.connection === "error"
                ? "连接失败"
                : "准备好，随时出发";
        return `<div class="client-wrap"><div class="client-controls"><span>客户端交互预览</span><label for="scenario">演示场景</label><select class="sort" id="scenario"><option value="normal">正常连接</option><option value="failure" ${state.scenario === "failure" ? "selected" : ""}>连接失败</option><option value="empty" ${state.scenario === "empty" ? "selected" : ""}>尚未购买</option></select><a class="text-btn" href="#overview">返回官网概览</a></div><div class="client-frame"><div class="windowbar"><div class="window-dots"><i></i><i></i><i></i></div><span>卡皮巴拉 · 我的代理</span><span>设计预览</span></div><div class="client-shell">${sidebar(true)}<main class="client-main"><div class="client-heading"><div><h1>我的代理</h1><p>选择一条固定出口，让你的工作保持连贯。</p></div>${button("同步代理", "refresh", "refresh")}</div><div class="client-grid"><div class="column"><section class="connection"><small>YOUR PERSONAL CONNECTION</small><button class="power ${connected ? "on" : ""}" data-action="connect" aria-label="${connected ? "断开连接" : "连接所选代理"}" ${busy || p.status !== "active" || state.scenario === "empty" ? "disabled" : ""}>${icon("power")}</button><h2>${state.scenario === "empty" ? "添加你的第一条代理" : title}</h2><p>${state.scenario === "empty" ? "购买后将在这里同步你的代理。" : `${esc(p.name)} · ${p.protocol}<br><span class="mono">${p.ip || "等待分配"}${p.port ? ":" + p.port : ""}</span>`}</p>${button(connected ? "断开连接" : busy ? "正在建立连接…" : p.status === "expired" ? "代理已到期" : p.status === "pending" ? "等待开通" : "一键连接", "connect", "", "primary", busy || p.status !== "active" || state.scenario === "empty" ? "disabled" : "")}${state.connection === "error" ? '<div class="error-note">未能连接此代理，请检查认证信息或重试。<br>失败场景为交互演示，系统代理未被修改。</div>' : ""}<div class="connection-footer">${icon("shield")}固定出口 · 独立认证 · 随时断开</div></section><div class="client-resources"><section class="stat"><div class="stat-top">本月使用 ${icon("chart")}</div><strong>${state.scenario === "empty" || p.used === null ? "—" : p.used}<span>GB</span></strong><small>不限累计流量</small></section><section class="stat"><div class="stat-top">带宽上限 ${icon("globe")}</div><strong>100<span>Mbps</span></strong><small>非实时测速结果</small></section></div><p class="client-note">客户端会使用所选代理建立连接。连接失败时显示原因，切换端点或协议前先断开当前连接。</p></div><div class="client-right"><section class="card client-list"><div class="section-head"><h2>选择代理</h2><span class="muted" style="font-size:11px">${state.scenario === "empty" ? 0 : proxies.length} 条</span></div><label class="search">${icon("search")}<input id="client-query" value="${esc(state.clientQuery)}" placeholder="搜索代理名称或 IP" aria-label="搜索客户端代理"></label><div id="client-endpoints">${list.map((e) => `<button class="endpoint ${e.id === p.id ? "selected" : ""}" data-action="select-client" data-id="${e.id}" aria-pressed="${e.id === p.id}"><span class="endpoint-top"><span class="flag">🇺🇸</span><b>${esc(e.name.replace("美国 · ", ""))}</b>${badge(e)}</span><div class="mono">${e.ip ? e.ip + ":" + e.port : "等待分配连接信息"}</div><span class="endpoint-foot"><span>${e.protocol} · 100 Mbps</span><span>${e.status === "active" ? days(e) + " 天后到期" : e.status === "pending" ? "开通中" : "已到期"}</span></span></button>`).join("") || `<div class="empty"><p>${state.scenario === "empty" ? "还没有代理" : "未找到匹配代理"}</p>${state.scenario === "empty" ? button("购买代理", "buy", "plus", "soft") : ""}</div>`}</div></section>${state.scenario === "empty" ? "" : `<section class="card client-selected"><div class="section-head"><h3>连接协议</h3>${protocol(p)}</div><div class="kv"><span>当前代理</span><b>${p.number}</b></div><div class="kv"><span>到期时间</span><b>${date(p)}</b></div><div class="actions">${button("复制配置", "copy-string", "copy", "", `data-id="${p.id}" ${p.status === "pending" ? "disabled" : ""}`)}<a class="btn soft" href="#detail/${p.id}">管理 / 续费</a></div></section>`}</div></div></main></div></div><p class="hint">${icon("monitor")}本预览不连接真实代理，不修改系统网络。官网与客户端共用同一组示例端点。</p></div>`;
    }
    function render() {
        app.innerHTML =
            page() === "client"
                ? client()
                : page() === "detail"
                  ? detail()
                  : overview();
        document
            .querySelectorAll(".preview-bar a")
            .forEach((a) =>
                a.setAttribute(
                    "aria-current",
                    a.hash.startsWith("#" + page()) ? "page" : "false",
                ),
            );
        syncSelection();
    }
    function toast(message) {
        const t = document.querySelector("#toast");
        clearTimeout(state.toastTimer);
        t.textContent = message;
        t.classList.add("visible");
        state.toastTimer = setTimeout(
            () => t.classList.remove("visible"),
            3600,
        );
    }
    function modal(title, body, footer = "") {
        returnFocus = document.activeElement;
        dialog.innerHTML = `<div class="dialog-head"><h2>${title}</h2>${tiny("关闭弹窗", "close", "x")}</div>${body}<div class="dialog-actions">${button("取消", "close")}${footer}</div>`;
        if (!dialog.open) dialog.showModal();
    }
    async function copy(value) {
        try {
            await navigator.clipboard.writeText(value);
            toast("已复制示例连接信息");
        } catch {
            modal(
                "手动复制",
                `<p>浏览器未授予剪贴板权限，请选择下面的内容复制。</p><input class="dialog-input mono" readonly value="${esc(value)}" aria-label="待复制内容">`,
            );
            dialog.querySelector("input").select();
        }
    }
    function connectionString(p, format = "url") {
        return format === "colon"
            ? `${p.ip}:${p.port}:${p.user}:${p.password}`
            : `${p.protocol === "HTTP" ? "http" : "socks5"}://${encodeURIComponent(p.user)}:${encodeURIComponent(p.password)}@${p.ip}:${p.port}`;
    }
    function syncSelection() {
        const n = document.querySelector("#selected-count"),
            e = document.querySelector("#export"),
            all = document.querySelector("#select-all");
        if (n) n.textContent = `已选 ${state.selected.size} 条`;
        if (e) e.disabled = !state.selected.size;
        if (all) {
            const eligible = filtered().filter((p) => p.status !== "pending");
            all.checked =
                eligible.length > 0 &&
                eligible.every((p) => state.selected.has(p.id));
            all.indeterminate =
                eligible.some((p) => state.selected.has(p.id)) && !all.checked;
        }
    }
    document.addEventListener("click", async (event) => {
        const el = event.target.closest("[data-action]");
        if (!el || el.disabled) return;
        const action = el.dataset.action,
            p =
                proxies.find((p) => p.id === el.dataset.id) ||
                (page() === "client"
                    ? proxies.find((p) => p.id === state.clientId)
                    : current());
        if (action === "close") {
            dialog.close();
            return;
        }
        if (action === "filter") {
            state.filter = el.dataset.value;
            render();
            return;
        }
        if (action === "clear") {
            state.filter = "all";
            state.query = "";
            render();
            return;
        }
        if (action === "refresh") {
            toast("示例代理已同步；本预览不请求线上账号");
            return;
        }
        if (action === "protocol") {
            if (
                page() === "client" &&
                state.connection !== "off" &&
                state.connection !== "error"
            ) {
                toast("请先断开当前连接，再切换协议");
                return;
            }
            p.protocol = el.dataset.value;
            render();
            toast(`已切换为 ${p.protocol}，地址、端口和认证不变`);
            return;
        }
        if (action === "reveal") {
            state.reveal = !state.reveal;
            render();
            return;
        }
        if (action === "copy") {
            await copy(String(p[el.dataset.key]));
            return;
        }
        if (action === "copy-string") {
            await copy(connectionString(p));
            return;
        }
        if (action === "formats") {
            modal(
                "复制连接信息",
                `<p>选择目标工具支持的格式。以下信息含示例密码。</p><label for="copy-format">连接格式</label><select id="copy-format" class="dialog-input"><option value="url">${p.protocol} URL</option><option value="colon">IP:端口:用户名:密码</option></select>`,
                button(
                    "复制",
                    "copy-format",
                    "copy",
                    "primary",
                    `data-id="${p.id}"`,
                ),
            );
            return;
        }
        if (action === "copy-format") {
            const format = document.querySelector("#copy-format").value;
            dialog.close();
            await copy(connectionString(p, format));
            return;
        }
        if (action === "rename") {
            modal(
                "重命名代理",
                `<p>用用途命名，方便在官网和客户端中识别。</p><label for="rename">代理名称</label><input id="rename" class="dialog-input" maxlength="32" value="${esc(p.name)}">`,
                button(
                    "保存名称",
                    "save-name",
                    "",
                    "primary",
                    `data-id="${p.id}"`,
                ),
            );
            return;
        }
        if (action === "save-name") {
            const value = document.querySelector("#rename").value.trim();
            if (!value) {
                document.querySelector("#rename").focus();
                return;
            }
            p.name = value;
            dialog.close();
            render();
            toast("名称已更新到本次预览");
            return;
        }
        if (action === "reset") {
            modal(
                "重置代理密码",
                `<p>重置后，使用旧密码的连接将需要重新配置。其他端点的密码不变。</p><div class="dialog-summary"><b>${esc(p.name)}</b>${p.number} · 此操作仅改变示例密码</div>`,
                button(
                    "确认重置",
                    "confirm-reset",
                    "",
                    "primary",
                    `data-id="${p.id}"`,
                ),
            );
            return;
        }
        if (action === "confirm-reset") {
            p.password =
                "Demo-" +
                crypto.getRandomValues(new Uint32Array(1))[0].toString(36) +
                "!";
            state.reveal = false;
            dialog.close();
            render();
            toast("示例密码已重置，请重新复制配置");
            return;
        }
        if (action === "renew" || action === "buy") {
            const renew = action === "renew";
            modal(
                renew ? "续费代理" : "购买家宽固定 IP",
                `<p>${renew ? "续费沿用当前端点，剩余有效期继续保留。" : "美国固定出口，按月购买，开通后获取连接信息。"}</p><div class="dialog-summary"><b>${renew ? esc(p.name) : "美国 · 家宽固定 IP"}</b>最高 100 Mbps · 不限累计流量<br>SOCKS5 / HTTP · 独立用户名密码</div><div class="dialog-price">¥39<small> / 1个月</small></div><p>设计预览：不会创建真实订单或收取费用。</p>`,
                button(
                    renew ? "模拟续费" : "模拟购买",
                    renew ? "confirm-renew" : "confirm-buy",
                    "",
                    "primary",
                    `data-id="${p.id}"`,
                ),
            );
            return;
        }
        if (action === "confirm-renew") {
            const d = new Date(Math.max(epoch, p.expires || epoch));
            const day = d.getUTCDate();
            d.setUTCDate(1);
            d.setUTCMonth(d.getUTCMonth() + 1);
            const end = new Date(
                Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0),
            ).getUTCDate();
            d.setUTCDate(Math.min(day, end));
            p.expires = d.getTime();
            p.status = "active";
            dialog.close();
            render();
            toast("模拟续费成功，有效期增加一个月");
            return;
        }
        if (action === "confirm-buy") {
            const n = proxies.length + 1;
            proxies.push({
                id: "p" + String(n).padStart(2, "0"),
                name: "美国 · 新代理 " + n,
                number: "PX-" + (10000 + n),
                ip: "",
                port: null,
                user: "",
                password: "",
                expires: null,
                used: null,
                status: "pending",
                protocol: "SOCKS5",
            });
            dialog.close();
            location.hash = "#overview";
            render();
            toast("已添加待开通的示例代理");
            return;
        }
        if (action === "test") {
            const t = document.querySelector("#test-result");
            t.textContent = "示例检测完成 · 认证与 HTTPS 访问成功";
            toast("模拟检测通过；未向真实代理发出请求");
            return;
        }
        if (action === "use-client") {
            state.clientId = p.id;
            state.connection = "off";
            state.scenario = "normal";
            clearTimeout(state.connectionTimer);
            location.hash = "#client";
            render();
            return;
        }
        if (action === "select-client") {
            if (state.connection === "on" || state.connection === "busy") {
                toast("请先断开当前连接，再选择其他代理");
                return;
            }
            state.clientId = p.id;
            state.connection = "off";
            render();
            return;
        }
        if (action === "connect") {
            if (state.connection === "on") {
                state.connection = "off";
                render();
                return;
            }
            if (
                p.status !== "active" ||
                state.scenario === "empty" ||
                state.connection === "busy"
            )
                return;
            state.connection = "busy";
            render();
            state.connectionTimer = setTimeout(() => {
                state.connection =
                    state.scenario === "failure" ? "error" : "on";
                render();
            }, 900);
            return;
        }
        if (action === "export") {
            modal(
                "导出连接信息",
                `<p>将下载 ${state.selected.size} 条示例代理的地址、端口、账号和密码。请妥善保管包含认证信息的文件。</p>`,
                button("下载示例文件", "confirm-export", "download", "primary"),
            );
            return;
        }
        if (action === "confirm-export") {
            const rows = proxies.filter((p) => state.selected.has(p.id));
            const blob = new Blob(
                [
                    "# 设计预览：以下为虚构凭据，不可用于真实连接\n" +
                        rows.map((p) => connectionString(p)).join("\n"),
                ],
                { type: "text/plain;charset=utf-8" },
            );
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "capybara-proxies-DEMO.txt";
            a.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
            dialog.close();
            toast("示例连接信息已导出");
            return;
        }
        if (action === "guide") {
            modal(
                "连接指南",
                `<p>1. 在代理详情中选择 SOCKS5 或 HTTP。</p><p>2. 复制服务器地址、端口、用户名与密码到目标工具。</p><p>3. 测试连接，核对出口 IP；认证失败时检查协议、端口和密码。</p><div class="dialog-summary">两种协议使用同一个端点。HTTP 代理可通过 CONNECT 访问 HTTPS；SOCKS5 的 UDP 支持以最终服务配置为准。</div><p>本预览中的地址与密码仅为示例。</p>`,
            );
            return;
        }
        const messages = {
            vpn: "原有 VPN 连接入口保留。本轮演示新增的“我的代理”空间。",
            dashboard: "概览聚焦代理总数、可用状态、到期提醒与累计用量。",
            orders: "正式接入时展示真实订单；本次模拟购买与续费不会扣款。",
            settings: "账户设置沿用现有客户端与官网能力，本轮聚焦代理管理。",
            notice: "到期提醒示例：浏览器环境代理将在 3 天后到期。",
        };
        if (messages[action])
            modal(
                {
                    vpn: "VPN 连接",
                    dashboard: "工作空间",
                    orders: "订单记录",
                    settings: "账户设置",
                    notice: "到期提醒",
                }[action],
                `<p>${messages[action]}</p>`,
            );
    });
    document.addEventListener("input", (e) => {
        if (e.target.id === "query") {
            state.query = e.target.value;
            document.querySelector("#rows").innerHTML = rows();
            document.querySelector("#row-count").textContent =
                `共 ${filtered().length} 条代理`;
            syncSelection();
        }
        if (e.target.id === "client-query") {
            state.clientQuery = e.target.value;
            const start = e.target.selectionStart;
            render();
            const input = document.querySelector("#client-query");
            input.focus();
            input.setSelectionRange(start, start);
        }
    });
    document.addEventListener("change", (e) => {
        const el = e.target;
        if (el.dataset.select) {
            el.checked
                ? state.selected.add(el.dataset.select)
                : state.selected.delete(el.dataset.select);
            syncSelection();
        }
        if (el.id === "select-all") {
            for (const p of filtered().filter((p) => p.status !== "pending"))
                el.checked
                    ? state.selected.add(p.id)
                    : state.selected.delete(p.id);
            render();
        }
        if (el.id === "sort") {
            state.sort = el.value;
            render();
        }
        if (el.id === "chart-period") {
            state.chart = el.value;
            render();
        }
        if (el.id === "scenario") {
            state.scenario = el.value;
            state.connection = "off";
            clearTimeout(state.connectionTimer);
            render();
        }
    });
    dialog.addEventListener("close", () => {
        if (returnFocus?.isConnected) returnFocus.focus();
    });
    window.addEventListener("hashchange", () => {
        state.reveal = false;
        render();
        window.scrollTo(0, 0);
    });
    render();
})();
