import Updates from "./Updates";
import Plans from "./Plans";
import { useEffect, useRef, useState } from "react";
import {
    ArrowDownToLine,
    ArrowRight,
    ArrowUpRight,
    Check,
    CheckCircle2,
    ChevronRight,
    Clock3,
    Globe2,
    House,
    Compass,
    LifeBuoy,
    LoaderCircle,
    LogOut,
    Monitor,
    Moon,
    Power,
    RefreshCw,
    ShieldCheck,
    Sun,
    UserRound,
    Wifi,
    X,
    TriangleAlert,
    Copy,
    ShoppingBag,
} from "lucide-react";
import { command, errorText, preview } from "./bridge";
import {
    bytes,
    date,
    emptyView,
    quotaPercent,
    statusMessage,
    type View,
} from "./model";
const pages = [
    { id: "home", name: "首页", icon: House },
    { id: "routes", name: "线路", icon: Globe2 },
    { id: "plans", name: "套餐", icon: ShoppingBag },
    { id: "help", name: "帮助与设置", icon: LifeBuoy },
];
export default function App() {
    const [view, setView] = useState<View>(emptyView),
        [page, setPage] = useState("home"),
        [busy, setBusy] = useState(""),
        [error, setError] = useState(""),
        [dark, setDark] = useState(
            () => localStorage.getItem("capybara-theme") === "dark",
        ),
        [copied, setCopied] = useState(false);
    const loginOpen = !!view.browser_login;
    const registering = view.browser_login?.registration === true;
    const loginRef = useRef<HTMLDialogElement>(null),
        polling = useRef(false),
        mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        const update = async () => {
            if (polling.current) return;
            polling.current = true;
            try {
                const next = await command("snapshot");
                if (mounted.current) setView(next);
            } catch (e) {
                if (mounted.current) setError(errorText(e));
            } finally {
                polling.current = false;
            }
        };
        void update();
        const id = setInterval(update, 2000);
        return () => {
            mounted.current = false;
            clearInterval(id);
        };
    }, []);
    useEffect(() => {
        document.documentElement.dataset.theme = dark ? "dark" : "light";
        localStorage.setItem("capybara-theme", dark ? "dark" : "light");
    }, [dark]);
    useEffect(() => {
        if (loginOpen) loginRef.current?.showModal();
        else loginRef.current?.close();
    }, [loginOpen]);
    const act = async (name: string, args?: Record<string, unknown>) => {
        if (busy) return;
        setBusy(name);
        setError("");
        try {
            const next = await command(name, args);
            if (next) setView(next);
        } catch (e) {
            setError(errorText(e));
        } finally {
            setBusy("");
        }
    };
    const link = async (target: string) => {
        try {
            await command("open_link", { target });
        } catch (e) {
            setError(errorText(e));
        }
    };
    const s = view.subscription,
        percent = quotaPercent(s),
        status = statusMessage(view),
        connected = view.connection === "connected";
    const primary = () =>
        view.logged_in
            ? void act(connected ? "disconnect" : "connect")
            : void act("begin_browser_login");
    const eligible =
        !view.logged_in ||
        connected ||
        (!view.sync_error && s?.status === "active");
    const primaryText =
        busy === "connect"
            ? "正在建立连接"
            : busy === "disconnect"
              ? "正在断开"
              : busy === "restore_session"
                ? "正在恢复登录"
                : !view.logged_in
                  ? "账号登录"
                  : connected
                    ? "断开连接"
                    : "一键连接";
    const syncLabel = view.synced_at
        ? `同步于 ${new Date(view.synced_at * 1000).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`
        : "等待同步";
    const attention = status.tone === "warning" || status.tone === "danger";
    const statusCard = (
        <section className={"status-card " + status.tone} aria-live="polite">
            <span className="status-icon">
                {status.tone === "warning" || status.tone === "danger" ? (
                    <TriangleAlert size={21} />
                ) : (
                    <Compass size={21} />
                )}
            </span>
            <div>
                <h3>{status.title}</h3>
                <p>{status.text}</p>
            </div>
            {view.session_needs_unlock ? (
                <button
                    disabled={!!busy}
                    onClick={() => void act("restore_session")}
                >
                    {busy === "restore_session" ? "正在恢复登录" : "恢复登录"}
                    <ShieldCheck size={16} />
                </button>
            ) : view.logged_in && (s?.status !== "active" || percent >= 90) ? (
                <button onClick={() => setPage("plans")}>
                    查看套餐
                    <ArrowRight size={16} />
                </button>
            ) : (
                <span className="status-decoration">Take it easy.</span>
            )}
        </section>
    );
    return (
        <div className="app-shell">
            <aside className="sidebar">
                <a
                    className="brand"
                    aria-label="卡皮巴拉首页"
                    href="#"
                    onClick={(e) => {
                        e.preventDefault();
                        setPage("home");
                    }}
                >
                    <span className="brand-mark">
                        <img src="/capybara-icon.png" alt="" />
                    </span>
                    <span>
                        <strong>卡皮巴拉</strong>
                        <small>CAPYBARA</small>
                    </span>
                </a>
                <div className="sidebar-caption">你的连接小伙伴</div>
                <nav aria-label="主导航">
                    {pages.map((p) => (
                        <button
                            key={p.id}
                            aria-label={p.name}
                            className={
                                page === p.id ? "nav-item active" : "nav-item"
                            }
                            onClick={() => setPage(p.id)}
                            aria-current={page === p.id ? "page" : undefined}
                        >
                            <p.icon size={19} />
                            <span>{p.name}</span>
                            {page === p.id && <span className="nav-dot" />}
                        </button>
                    ))}
                </nav>
                <div className="sidebar-note">
                    <Compass size={20} />
                    <p>
                        慢下来，
                        <br />
                        世界依然很近。
                    </p>
                    <span>Stay calm. Stay connected.</span>
                </div>
                <button
                    className="sidebar-account"
                    aria-label={
                        view.logged_in ? "查看我的账户" : "登录你的账号"
                    }
                    onClick={() =>
                        view.logged_in
                            ? setPage("account")
                            : void act("begin_browser_login")
                    }
                >
                    <span className="avatar">
                        <UserRound size={18} />
                    </span>
                    <span>
                        <b>{view.profile?.name || "欢迎你"}</b>
                        <small>
                            {view.logged_in ? "查看我的账户" : "登录你的账号"}
                        </small>
                    </span>
                    <ChevronRight size={16} />
                </button>
                <div className="sidebar-footer">
                    <div className="sidebar-version">
                        v{view.version} <span>测试版</span>
                    </div>
                    <button
                        className="icon-button"
                        aria-label={dark ? "切换浅色主题" : "切换深色主题"}
                        title={dark ? "切换浅色主题" : "切换深色主题"}
                        onClick={() => setDark(!dark)}
                    >
                        {dark ? <Sun size={19} /> : <Moon size={19} />}
                    </button>
                </div>
            </aside>
            <main>
                <h1 className="sr-only">
                    {page === "account"
                        ? "我的账户"
                        : pages.find((p) => p.id === page)?.name}
                </h1>
                {preview && (
                    <div className="preview-label">
                        界面预览 · 模拟数据 · 不会连接真实线路
                    </div>
                )}
                {error && (
                    <div className="inline-error" role="alert">
                        <TriangleAlert size={18} />
                        <span>{error}</span>
                        <button
                            aria-label="关闭提示"
                            onClick={() => setError("")}
                        >
                            <X size={16} />
                        </button>
                    </div>
                )}
                {page === "home" && (
                    <>
                        {attention && statusCard}
                        <section className="hero">
                            <div className="hero-copy">
                                <span className="tag">
                                    <Compass size={13} />{" "}
                                    和卡皮巴拉一起，探索世界
                                </span>
                                <h2>
                                    世界很大，
                                    <br />
                                    慢慢连接。
                                </h2>
                                <p>
                                    把连接的事交给我。
                                    <br />
                                    你只管享受自己的节奏。
                                </p>
                                <span className="hero-signature">
                                    Your calm connection to the world.
                                </span>
                            </div>
                            <div className="mascot-scene">
                                <div className="orbit orbit-one" />
                                <div className="orbit orbit-two" />
                                <div className="sun-disc" />
                                <span className="spark spark-one">✦</span>
                                <span className="spark spark-two">✧</span>
                                <img
                                    className="mascot"
                                    src="/capybara.png"
                                    alt="戴蓝围巾、背旅行包的卡皮巴拉水豚"
                                />
                                <span className="mascot-caption">
                                    <span /> 今天，也要松弛一点。
                                </span>
                            </div>
                        </section>
                        <div className="main-grid">
                            <section className="card connect-card">
                                <div className="card-label">
                                    <span>
                                        <Wifi size={17} /> 我的连接
                                    </span>
                                    <span className="subtle">系统代理</span>
                                </div>
                                <div className="connect-body">
                                    <button
                                        className={
                                            "power-button " +
                                            (connected ? "on" : "")
                                        }
                                        onClick={primary}
                                        disabled={!!busy || !eligible}
                                        aria-label={primaryText}
                                    >
                                        {busy === "connect" ||
                                        busy === "disconnect" ? (
                                            <LoaderCircle
                                                className="spin"
                                                size={32}
                                            />
                                        ) : (
                                            <Power size={32} />
                                        )}
                                    </button>
                                    <div>
                                        <h3>
                                            {connected
                                                ? "已连接"
                                                : view.logged_in
                                                  ? "准备连接"
                                                  : "从这里开始"}
                                        </h3>
                                        <p>
                                            {connected
                                                ? view.routes[0]?.selected ||
                                                  "按规则自动分流"
                                                : view.logged_in
                                                  ? "选择轻松，连接世界。"
                                                  : "登录后，开启你的第一段连接。"}
                                        </p>
                                    </div>
                                </div>
                                <button
                                    className={
                                        "primary-button " +
                                        (connected ? "quiet" : "")
                                    }
                                    disabled={!!busy || !eligible}
                                    onClick={primary}
                                >
                                    {primaryText}
                                    <ArrowRight size={18} />
                                </button>
                                {!view.logged_in && (
                                    <div className="register-entry">
                                        <span>还没有账号？</span>
                                        <button
                                            disabled={!!busy}
                                            onClick={() =>
                                                void act(
                                                    "begin_browser_login",
                                                    { registration: true },
                                                )
                                            }
                                        >
                                            注册账号
                                            <ArrowUpRight size={15} />
                                        </button>
                                    </div>
                                )}
                                <div className="connect-foot">
                                    <ShieldCheck size={14} />
                                    <span>连接前自动检查套餐状态</span>
                                    {connected && (
                                        <button
                                            onClick={() => setPage("routes")}
                                        >
                                            切换线路
                                        </button>
                                    )}
                                </div>
                            </section>
                            <section className="card quota-card">
                                <div className="card-label">
                                    <span>
                                        <ArrowDownToLine size={17} /> 本期流量
                                    </span>
                                    <button
                                        className="icon-button small"
                                        disabled={!view.logged_in || !!busy}
                                        onClick={() => void act("refresh")}
                                        aria-label="立即同步流量"
                                    >
                                        <RefreshCw
                                            size={15}
                                            className={
                                                busy === "refresh" ? "spin" : ""
                                            }
                                        />
                                    </button>
                                </div>
                                <div className="quota-value">
                                    {
                                        bytes(s?.traffic.remaining_bytes).split(
                                            " ",
                                        )[0]
                                    }
                                    <span>{s ? "GB 可用" : "登录后查看"}</span>
                                </div>
                                <div
                                    className={
                                        "progress-track " +
                                        (percent >= 90 ? "low" : "")
                                    }
                                    role="progressbar"
                                    aria-label="本期流量已使用"
                                    aria-valuenow={Math.round(percent)}
                                    aria-valuemin={0}
                                    aria-valuemax={100}
                                >
                                    <div style={{ width: `${percent}%` }} />
                                </div>
                                <div className="quota-detail">
                                    <span>
                                        已用 {bytes(s?.traffic.used_bytes)}
                                    </span>
                                    <span>
                                        共 {bytes(s?.traffic.total_bytes)}
                                    </span>
                                </div>
                                <div className="quota-bottom">
                                    <span>
                                        <Clock3 size={14} />
                                        {s?.traffic.reset_at
                                            ? `${date(s.traffic.reset_at)} 重置`
                                            : "重置日期以套餐为准"}
                                    </span>
                                    <small>
                                        {view.logged_in
                                            ? syncLabel
                                            : "自动同步，无需刷新订阅"}
                                    </small>
                                </div>
                            </section>
                        </div>
                        {!attention && statusCard}
                        <div className="bottom-links">
                            <span>
                                <ShieldCheck size={14} /> 账号状态每 30
                                秒自动同步
                            </span>
                            <button onClick={() => setPage("help")}>
                                遇到问题？我们陪你解决{" "}
                                <ArrowUpRight size={14} />
                            </button>
                        </div>
                    </>
                )}
                {page === "routes" && (
                    <section className="card page-card">
                        <div className="section-heading">
                            <div>
                                <span className="eyebrow">FIND YOUR WAY</span>
                                <h2>选一条喜欢的线路</h2>
                                <p>系统根据规则分流，切换后会重新检查连接。</p>
                            </div>
                            <Globe2 size={35} />
                        </div>
                        {!connected ? (
                            <div className="empty-state">
                                <img src="/capybara.png" alt="等待连接的水豚" />
                                <h3>先连接，再挑一条路</h3>
                                <p>连接后会显示当前套餐的实际线路。</p>
                                <button
                                    className="primary-button"
                                    disabled={!!busy || !eligible}
                                    onClick={primary}
                                >
                                    {primaryText}
                                    <ArrowRight size={18} />
                                </button>
                            </div>
                        ) : view.routes.length === 0 ? (
                            <p className="empty-text">
                                当前配置没有可手动选择的线路组，正在按服务器规则运行。
                            </p>
                        ) : (
                            view.routes.map((route) => (
                                <div className="route-group" key={route.group}>
                                    <h3>
                                        {route.group}
                                        <span>
                                            {route.choices.length} 个选项
                                        </span>
                                    </h3>
                                    {route.choices.map((name) => (
                                        <button
                                            className={
                                                "route-item " +
                                                (route.selected === name
                                                    ? "selected"
                                                    : "")
                                            }
                                            key={name}
                                            disabled={!!busy}
                                            onClick={() =>
                                                void act("select_route", {
                                                    group: route.group,
                                                    name,
                                                })
                                            }
                                        >
                                            <span className="route-symbol">
                                                <Globe2 size={18} />
                                            </span>
                                            <span>{name}</span>
                                            {route.selected === name ? (
                                                <CheckCircle2 size={20} />
                                            ) : (
                                                <ChevronRight size={17} />
                                            )}
                                        </button>
                                    ))}
                                </div>
                            ))
                        )}
                        {connected && (
                            <button
                                className="text-button"
                                disabled={!!busy}
                                onClick={() => void act("check_connection")}
                            >
                                <RefreshCw
                                    size={16}
                                    className={
                                        busy === "check_connection"
                                            ? "spin"
                                            : ""
                                    }
                                />
                                检测当前连接
                            </button>
                        )}
                    </section>
                )}
                {page === "plans" && (
                    <Plans
                        view={view}
                        onLogin={() => void act("begin_browser_login")}
                        onRefresh={() => void act("refresh")}
                    />
                )}
                {page === "account" && (
                    <section className="card page-card">
                        <div className="section-heading">
                            <div>
                                <span className="eyebrow">
                                    YOUR LITTLE SPACE
                                </span>
                                <h2>我的账户</h2>
                                <p>你的套餐和用量，清清楚楚。</p>
                            </div>
                            <UserRound size={35} />
                        </div>
                        {view.logged_in ? (
                            <>
                                <div className="profile-line">
                                    <span className="avatar large">
                                        <UserRound size={28} />
                                    </span>
                                    <div>
                                        <h3>
                                            {view.profile?.name || "已登录用户"}
                                        </h3>
                                        <p>
                                            {view.profile?.email ||
                                                "正在同步账号资料"}
                                        </p>
                                    </div>
                                    <button
                                        className="text-button"
                                        disabled={!!busy}
                                        onClick={() => void act("logout")}
                                    >
                                        <LogOut size={16} />
                                        退出登录
                                    </button>
                                </div>
                                <div className="account-grid">
                                    <div>
                                        <span>当前套餐</span>
                                        <b>{s?.plan_name || "暂无套餐"}</b>
                                    </div>
                                    <div>
                                        <span>到期日期</span>
                                        <b>
                                            {s?.expires_at
                                                ? date(s.expires_at)
                                                : s
                                                  ? "无固定到期日"
                                                  : "—"}
                                        </b>
                                    </div>
                                    <div>
                                        <span>剩余流量</span>
                                        <b>
                                            {bytes(s?.traffic.remaining_bytes)}
                                        </b>
                                    </div>
                                    <div>
                                        <span>已注册设备</span>
                                        <b>
                                            {s?.registered_device_count ?? "—"}{" "}
                                            /{" "}
                                            {s?.registered_device_limit ||
                                                "不限"}
                                        </b>
                                    </div>
                                </div>
                                <div className={"status-card " + status.tone}>
                                    <TriangleAlert size={20} />
                                    <div>
                                        <h3>{status.title}</h3>
                                        <p>{status.text}</p>
                                    </div>
                                </div>
                                <button
                                    className="primary-button fit"
                                    onClick={() => setPage("plans")}
                                >
                                    续费与管理套餐
                                    <ArrowUpRight size={17} />
                                </button>
                                <p className="fine-print">
                                    在套餐页选择周期并购买；设备管理仍可从帮助与设置打开网站账户中心。
                                </p>
                            </>
                        ) : (
                            <div className="empty-state">
                                <img src="/capybara.png" alt="水豚" />
                                <h3>给自己一个轻松的开始</h3>
                                <button
                                    className="primary-button"
                                    onClick={() =>
                                        void act("begin_browser_login")
                                    }
                                >
                                    登录账号
                                    <ArrowRight size={18} />
                                </button>
                            </div>
                        )}
                    </section>
                )}
                {page === "help" && (
                    <section className="card page-card">
                        <div className="section-heading">
                            <div>
                                <span className="eyebrow">
                                    WE ARE HERE FOR YOU
                                </span>
                                <h2>有问题，慢慢来</h2>
                                <p>先看看连接和套餐，我们一起找到原因。</p>
                            </div>
                            <LifeBuoy size={35} />
                        </div>
                        <div className="help-grid">
                            <article>
                                <ShieldCheck />
                                <h3>账号会自动同步</h3>
                                <p>
                                    每 30
                                    秒查看流量与到期状态；计费上报可能有延迟。无法同步时会明确提示，不把旧数据当成最新结果。
                                </p>
                            </article>
                            <article>
                                <Monitor />
                                <h3>系统代理怎么用</h3>
                                <p>
                                    点击连接后，为遵循系统代理的应用提供连接。首版暂不支持
                                    TUN；Linux 目前支持 GNOME 桌面。
                                </p>
                            </article>
                            <article>
                                <RefreshCw />
                                <h3>连接不通怎么办</h3>
                                <p>
                                    先检查套餐状态，再切换线路。如果其他代理应用正在运行，请先关闭它的系统代理。
                                </p>
                            </article>
                            <article>
                                <Compass />
                                <h3>关于卡皮巴拉</h3>
                                <p>
                                    v{view.version} · 使用 Mihomo
                                    内核。当前为测试版本，安装签名及更多系统兼容性仍在完善。
                                </p>
                            </article>
                        </div>
                        <div className="help-actions">
                            <button
                                className="secondary-button"
                                onClick={() => void link("support")}
                            >
                                <LifeBuoy size={17} />
                                联系支持
                                <ArrowUpRight size={15} />
                            </button>
                            <button
                                className="secondary-button"
                                onClick={async () => {
                                    try {
                                        await navigator.clipboard.writeText(
                                            `Capybara ${view.version}\nPlatform: ${view.platform || "browser-preview"}\nConnection: ${view.connection}\nAccount sync: ${view.sync_error ? "failed" : view.synced_at ? "ok" : "pending"}\nSubscription: ${s?.status || "unknown"}`,
                                        );
                                        setCopied(true);
                                        setTimeout(
                                            () => setCopied(false),
                                            2000,
                                        );
                                    } catch {
                                        setError(
                                            "无法复制，请手动记录版本与连接状态",
                                        );
                                    }
                                }}
                            >
                                {copied ? (
                                    <Check size={17} />
                                ) : (
                                    <Copy size={17} />
                                )}
                                复制诊断摘要
                            </button>
                        </div>
                        <p className="fine-print">
                            诊断摘要只包含版本和状态，不含邮箱、登录凭据或订阅链接。
                        </p>
                    </section>
                )}
                <Updates
                    version={view.version}
                    settings={page === "help"}
                    blocked={loginOpen || !!busy}
                />
            </main>
            <dialog
                ref={loginRef}
                className="login-dialog"
                aria-labelledby="browser-login-title"
                onCancel={(e) => {
                    e.preventDefault();
                    if (!busy) void act("cancel_browser_login");
                }}
            >
                <button
                    className="modal-close icon-button"
                    aria-label="取消登录"
                    disabled={!!busy}
                    onClick={() => void act("cancel_browser_login")}
                >
                    <X size={20} />
                </button>
                <img
                    className="login-mascot"
                    src="/capybara.png"
                    alt="卡皮巴拉"
                />
                <span className="eyebrow">WELCOME TO CAPYBARA</span>
                <h2 id="browser-login-title">
                    {view.browser_login?.phase === "error"
                        ? "登录尚未完成"
                        : registering
                          ? "在浏览器中注册账号"
                          : "在浏览器中完成登录"}
                </h2>
                <p>
                    {view.browser_login?.phase === "starting"
                        ? "正在准备授权页面…"
                        : registering
                          ? "在官网完成注册后，确认授权即可回到客户端。"
                          : "使用官网已登录的账号，确认授权后即可回到这里。"}
                </p>
                {view.browser_login?.error && (
                    <div className="login-error" role="alert">
                        {view.browser_login.error}
                    </div>
                )}
                {error && (
                    <div className="login-error" role="alert">
                        {error}
                    </div>
                )}
                {view.browser_login?.phase !== "error" && (
                    <p className="credential-hint">
                        <LoaderCircle size={16} className="spin" />{" "}
                        正在等待浏览器授权，五分钟内有效。
                    </p>
                )}
                {view.browser_login?.phase === "waiting" && (
                    <button
                        className="primary-button"
                        disabled={!!busy}
                        onClick={() => void act("reopen_browser_login")}
                    >
                        <ArrowUpRight size={17} />
                        重新打开浏览器
                    </button>
                )}
                {view.browser_login?.phase === "error" && (
                    <button
                        className="primary-button"
                        disabled={!!busy}
                        onClick={() =>
                            void act("begin_browser_login", {
                                registration: registering,
                            })
                        }
                    >
                        {registering ? "继续注册" : "重新登录"}
                        <ArrowRight size={17} />
                    </button>
                )}
                {!registering && (
                    <div className="register-entry">
                        <span>还没有账号？</span>
                        <button
                            disabled={!!busy}
                            onClick={() =>
                                void act("begin_browser_login", {
                                    registration: true,
                                })
                            }
                        >
                            注册账号
                            <ArrowUpRight size={15} />
                        </button>
                    </div>
                )}
                {registering && (
                    <p className="fine-print">
                        若注册超过五分钟，完成后回到客户端重新点“账号登录”即可。
                    </p>
                )}
                <button
                    className="secondary-button"
                    disabled={!!busy}
                    onClick={() => void act("cancel_browser_login")}
                >
                    取消
                </button>
                <small className="fine-print">
                    无需在客户端输入密码，登录记录由系统凭据库安全保管。
                </small>
            </dialog>
        </div>
    );
}
