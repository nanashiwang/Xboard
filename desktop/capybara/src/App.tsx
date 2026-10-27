import Updates from "./Updates";
import Notifications from "./Notifications";
import Plans from "./Plans";
import Home from "./Home";
import { useNodes } from "./nodes";
import { useRouting } from "./Routing";
import DesktopSettings from "./DesktopSettings";
import SubscriptionSettings from "./SubscriptionSettings";
import Invites from "./Invites";
import { useEffect, useRef, useState } from "react";
import {
    ArrowRight,
    ArrowUpRight,
    Check,
    ChevronRight,
    House,
    Compass,
    LifeBuoy,
    LoaderCircle,
    LogOut,
    Monitor,
    Moon,
    RefreshCw,
    ShieldCheck,
    Sun,
    UserRound,
    X,
    TriangleAlert,
    Copy,
    ShoppingBag,
    Users,
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
    { id: "plans", name: "套餐", icon: ShoppingBag },
    { id: "invite", name: "邀请好友", icon: Users },
    { id: "help", name: "帮助与设置", icon: LifeBuoy },
];
export default function App() {
    const nodes = useNodes();
    const routing = useRouting(nodes.refresh);
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
        mainRef = useRef<HTMLElement>(null),
        polling = useRef(false),
        acting = useRef(false),
        mutation = useRef(0),
        mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        const update = async () => {
            if (polling.current || acting.current) return;
            polling.current = true;
            const epoch = mutation.current;
            try {
                const next = await command("snapshot");
                if (mounted.current && epoch === mutation.current)
                    setView(next);
            } catch (e) {
                if (mounted.current && epoch === mutation.current)
                    setError(errorText(e));
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
    useEffect(() => {
        if (mainRef.current) mainRef.current.scrollTop = 0;
    }, [page]);
    const act = async (name: string, args?: Record<string, unknown>) => {
        if (acting.current) return;
        acting.current = true;
        mutation.current++;
        setBusy(name);
        setError("");
        try {
            const next = await command(name, args);
            if (next) setView(next);
        } catch (e) {
            setError(errorText(e));
        } finally {
            mutation.current++;
            acting.current = false;
            setBusy("");
        }
    };
    const selectNode = async (group: string, name: string) => {
        if (acting.current || routing.busy || nodes.subscriptionPending) return;
        acting.current = true;
        mutation.current++;
        setBusy("select_and_connect");
        setError("");
        try {
            const next = await nodes.select(group, name);
            if (next) setView(next);
            else {
                // A failed operation can still revoke eligibility or stop the core.
                // Reconcile both states instead of retaining an old connected badge.
                await nodes.refresh();
                setView(await command("snapshot"));
            }
            return next;
        } catch (e) {
            setError(errorText(e));
        } finally {
            mutation.current++;
            acting.current = false;
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
        busy === "select_and_connect"
            ? connected
                ? "正在切换节点"
                : "正在建立连接"
            : busy === "connect"
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
        <div className="app-shell scenic-shell">
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
                <div className="sidebar-tools">
                    <div className="sidebar-caption">你的连接小伙伴</div>
                    <Notifications />
                </div>
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
                        v{view.version}{" "}
                        <span>
                            {view.version.includes("-") ? "预览版" : "正式版"}
                        </span>
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
            <main
                ref={mainRef}
                className={page === "home" ? "home-main" : "page-main"}
            >
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
                {page === "invite" && (
                    <Invites
                        view={view}
                        onLogin={() => void act("begin_browser_login")}
                    />
                )}
                {page === "home" && (
                    <Home
                        nodes={{ ...nodes, select: selectNode }}
                        routing={routing}
                        view={view}
                        busy={busy}
                        eligible={eligible}
                        primaryText={primaryText}
                        onPrimary={primary}
                        onAction={act}
                        onPlans={() => setPage("plans")}
                        notice={attention ? statusCard : null}
                    />
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
                        <DesktopSettings />
                        <SubscriptionSettings
                            nodes={nodes}
                            disabled={!!busy || !!routing?.busy}
                        />
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
                                    内核。支持官网账号登录、套餐购买与安全更新。
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
                <small className="fine-print">
                    无需在客户端输入密码，登录记录由系统凭据库安全保管。
                </small>
            </dialog>
        </div>
    );
}
