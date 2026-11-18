import { useEffect, useRef, useState } from "react";
import QRCode from "qrcode";
import {
    Globe2,
    Plus,
    RefreshCw,
    Copy,
    ArrowLeft,
    ShieldCheck,
    Search,
} from "lucide-react";
import "./proxies.css";

export type ProxyItem = {
    id: number;
    name: string;
    address: string;
    port: number;
    status: string;
    expires_at: number;
    checked_at: number | null;
    credentials?: { username: string; password: string };
};
type Index = {
    price: number;
    available: number;
    items: ProxyItem[];
    pending: { trade_no: string } | null;
};
type Order = {
    trade_no: string;
    status: number;
    total_amount: number;
    balance_amount: number;
};
export type ProxyRequest = <T>(
    action: string,
    payload?: Record<string, unknown>,
) => Promise<T>;
const statusNames: Record<string, string> = {
    active: "可用",
    provisioning: "正在同步",
    expired: "已到期",
};
const date = (t: number | null) =>
    t ? new Date(t * 1000).toLocaleString("zh-CN", { hour12: false }) : "—";
const money = (v: number) => (v / 100).toFixed(2);

export default function Proxies({
    request,
    loggedIn,
    onLogin,
    native = false,
    connectedId = null,
    onConnection,
}: {
    request: ProxyRequest;
    loggedIn: boolean;
    onLogin: () => void;
    native?: boolean;
    connectedId?: number | null;
    onConnection?: () => void;
}) {
    const [data, setData] = useState<Index>({
        price: 3900,
        available: 0,
        items: [],
        pending: null,
    });
    const [selected, setSelected] = useState<ProxyItem | null>(null),
        [protocol, setProtocol] = useState("SOCKS5"),
        [reveal, setReveal] = useState(false);
    const [busy, setBusy] = useState(false),
        [loading, setLoading] = useState(true),
        [error, setError] = useState(""),
        [message, setMessage] = useState("");
    const [search, setSearch] = useState(""),
        [filter, setFilter] = useState("all"),
        [confirm, setConfirm] = useState<"buy" | "renew" | "reset" | null>(
            null,
        );
    const [order, setOrder] = useState<Order | null>(null),
        [methods, setMethods] = useState<{ id: number; name: string }[]>([]),
        [method, setMethod] = useState(0),
        [qr, setQr] = useState("");
    const [rename, setRename] = useState("");
    const mounted = useRef(true),
        generation = useRef(0),
        pending = useRef(false),
        selection = useRef<number | null>(null);
    async function load() {
        const epoch = generation.current;
        if (!loggedIn) {
            setLoading(false);
            return;
        }
        const next = await request<Index>("index");
        if (epoch !== generation.current || !mounted.current) return;
        if (mounted.current) {
            setData(next);
            setLoading(false);
        }
        if (selection.current) {
            const detail = await request<ProxyItem>("detail", {
                id: selection.current,
            });
            if (mounted.current && epoch === generation.current && detail.id === selection.current)
                setSelected(detail);
        }
    }
    useEffect(() => {
        generation.current++;
        mounted.current = true;
        if (!loggedIn) {
            selection.current = null;
            setSelected(null);
            setOrder(null);
            setConfirm(null);
            setQr("");
            setData({ price: 3900, available: 0, items: [], pending: null });
        }
        void load().catch((e) => {
            setError(String(e.message || e));
            setLoading(false);
        });
        const timer = setInterval(() => {
            if (!pending.current) void load().catch(() => {});
        }, 15000);
        return () => {
            generation.current++;
            mounted.current = false;
            clearInterval(timer);
        };
    }, [loggedIn]);
    async function action(fn: () => Promise<void>) {
        if (pending.current) return;
        pending.current = true;
        setBusy(true);
        setError("");
        setMessage("");
        try {
            await fn();
        } catch (e) {
            setError(String((e as Error).message || e));
        } finally {
            pending.current = false;
            setBusy(false);
        }
    }
    async function openOrder(trade: string) {
        const epoch = generation.current;
        const result = await request<Order>("order", { trade_no: trade });
        if (epoch !== generation.current || !mounted.current) return;
        setOrder(result);
        setQr("");
        const store = await request<{
            methods: { id: number; name: string }[];
        }>("store");
        if (epoch !== generation.current || !mounted.current) return;
        setMethods(store.methods);
        setMethod(store.methods[0]?.id || 0);
    }
    async function choose(item: ProxyItem) {
        const epoch = generation.current;
        selection.current = item.id;
        setSelected(null);
        setReveal(false);
        const detail = await request<ProxyItem>("detail", { id: item.id });
        if (selection.current === item.id && epoch === generation.current && mounted.current) {
            setSelected(detail);
            setRename(detail.name);
        }
    }
    async function copy(value: string) {
        await navigator.clipboard.writeText(value);
        setMessage("已复制，请妥善保管连接信息");
    }
    const items = data.items.filter(
        (p) =>
            (filter === "all" || p.status === filter) &&
            `${p.name} ${p.address} ${p.id}`.includes(search),
    );
    const connection = selected?.credentials
        ? `${protocol === "HTTP" ? "http" : "socks5"}://${encodeURIComponent(selected.credentials.username)}:${encodeURIComponent(selected.credentials.password)}@${selected.address}:${selected.port}`
        : "";
    return (
        <section className="rp" aria-label="我的代理">
            <header className="rp-heading">
                <div>
                    <span className="rp-eyebrow">RESIDENTIAL PROXY</span>
                    <h2>{selected ? selected.name : "我的代理"}</h2>
                    <p>
                        固定出口 · SOCKS5 / HTTP · 每个端点最高 100 Mbps ·
                        不限累计流量
                    </p>
                </div>
                <div className="rp-actions">
                    <button disabled={busy} onClick={() => void action(load)}>
                        <RefreshCw size={16} />
                        刷新
                    </button>
                    <button
                        className="rp-primary"
                        disabled={busy || !loggedIn || !data.available}
                        onClick={() => setConfirm("buy")}
                    >
                        <Plus size={17} />
                        购买代理
                    </button>
                </div>
            </header>
            {error && (
                <div className="rp-error" role="alert">
                    {error}
                </div>
            )}
            {message && (
                <div className="rp-message" role="status">
                    {message}
                </div>
            )}
            {!loggedIn ? (
                <div className="rp-empty">
                    <Globe2 size={40} />
                    <h3>登录后管理你的家宽代理</h3>
                    <p>¥39 / 月，一条代理对应一组独立连接账号。</p>
                    <button className="rp-primary" onClick={onLogin}>
                        登录账号
                    </button>
                </div>
            ) : (
                <>
                    {data.pending && !order && (
                        <div className="rp-pending">
                            你有一笔代理订单尚未完成。
                            <button
                                onClick={() =>
                                    void action(() =>
                                        openOrder(data.pending!.trade_no),
                                    )
                                }
                            >
                                继续处理
                            </button>
                        </div>
                    )}
                    {selected ? (
                        <>
                            <button
                                className="rp-back"
                                onClick={() => {
                                    selection.current = null;
                                    setSelected(null);
                                    setReveal(false);
                                }}
                            >
                                <ArrowLeft size={16} />
                                返回我的代理
                            </button>
                            <div className="rp-detail">
                                <section className="rp-card">
                                    <div className="rp-section-title">
                                        <h3>连接信息</h3>
                                        <div
                                            className="rp-protocol"
                                            role="group"
                                            aria-label="连接协议"
                                        >
                                            {["SOCKS5", "HTTP"].map((p) => (
                                                <button
                                                    key={p}
                                                    aria-pressed={
                                                        protocol === p
                                                    }
                                                    className={
                                                        protocol === p
                                                            ? "active"
                                                            : ""
                                                    }
                                                    onClick={() =>
                                                        setProtocol(p)
                                                    }
                                                >
                                                    {p}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                    <p className="rp-muted">
                                        两种协议使用相同的端口和账号。HTTP 支持
                                        HTTPS CONNECT。
                                    </p>
                                    <dl className="rp-credentials">
                                        {[
                                            ["服务器地址", selected.address],
                                            ["端口", String(selected.port)],
                                            [
                                                "用户名",
                                                selected.credentials?.username,
                                            ],
                                            [
                                                "密码",
                                                selected.credentials?.password,
                                            ],
                                        ].map(([label, value]) => (
                                            <div key={label}>
                                                <dt>{label}</dt>
                                                <dd>
                                                    {label === "密码" &&
                                                    !reveal &&
                                                    value
                                                        ? "••••••••••••••"
                                                        : value || "到期后隐藏"}
                                                </dd>
                                                <button
                                                    aria-label={`复制${label}`}
                                                    disabled={!value}
                                                    onClick={() =>
                                                        void action(() =>
                                                            copy(value!),
                                                        )
                                                    }
                                                >
                                                    <Copy size={15} />
                                                </button>
                                            </div>
                                        ))}
                                    </dl>
                                    <div className="rp-actions">
                                        <button
                                            onClick={() => setReveal(!reveal)}
                                        >
                                            {reveal ? "隐藏" : "显示"}密码
                                        </button>
                                        <button
                                            disabled={!connection}
                                            onClick={() =>
                                                void action(() =>
                                                    copy(connection),
                                                )
                                            }
                                        >
                                            复制连接串
                                        </button>
                                        <button
                                            disabled={
                                                busy || !selected.credentials
                                            }
                                            onClick={() => setConfirm("reset")}
                                        >
                                            重置密码
                                        </button>
                                    </div>
                                    {native && (
                                        <div className="rp-connect">
                                            <button
                                                className="rp-primary"
                                                disabled={
                                                    busy ||
                                                    (connectedId !==
                                                        selected.id &&
                                                        selected.status !==
                                                            "active")
                                                }
                                                onClick={() =>
                                                    void action(async () => {
                                                        await request(
                                                            connectedId ===
                                                                selected.id
                                                                ? "disconnect"
                                                                : "connect",
                                                            {
                                                                id: selected.id,
                                                                protocol,
                                                            },
                                                        );
                                                        onConnection?.();
                                                        setMessage(
                                                            connectedId ===
                                                                selected.id
                                                                ? "已断开代理"
                                                                : "代理已连接",
                                                        );
                                                    })
                                                }
                                            >
                                                {connectedId === selected.id
                                                    ? "断开代理"
                                                    : "连接此代理"}
                                            </button>
                                            <span>
                                                连接会替换客户端当前连接；不影响原
                                                VPN 套餐权益。
                                            </span>
                                        </div>
                                    )}
                                </section>
                                <aside className="rp-card">
                                    <h3>
                                        代理状态{" "}
                                        <span
                                            className={`rp-badge ${selected.status}`}
                                        >
                                            {statusNames[selected.status]}
                                        </span>
                                    </h3>
                                    <dl className="rp-facts">
                                        <div>
                                            <dt>地区</dt>
                                            <dd>美国 · IPv4</dd>
                                        </div>
                                        <div>
                                            <dt>到期时间</dt>
                                            <dd>{date(selected.expires_at)}</dd>
                                        </div>
                                        <div>
                                            <dt>月付价格</dt>
                                            <dd>¥{money(data.price)}</dd>
                                        </div>
                                        <div>
                                            <dt>流量</dt>
                                            <dd>不限累计流量</dd>
                                        </div>
                                        <div>
                                            <dt>服务同步</dt>
                                            <dd>{date(selected.checked_at)}</dd>
                                        </div>
                                    </dl>
                                    <button
                                        className="rp-primary rp-full"
                                        disabled={busy}
                                        onClick={() => setConfirm("renew")}
                                    >
                                        续费一个月
                                    </button>
                                    <label className="rp-label">
                                        备注名称
                                        <input
                                            value={rename}
                                            maxLength={60}
                                            onChange={(e) =>
                                                setRename(e.target.value)
                                            }
                                        />
                                    </label>
                                    <button
                                        disabled={busy || !rename.trim()}
                                        onClick={() =>
                                            void action(async () => {
                                                await request("update", {
                                                    id: selected.id,
                                                    name: rename.trim(),
                                                });
                                                await load();
                                                setMessage("名称已保存");
                                            })
                                        }
                                    >
                                        保存名称
                                    </button>
                                </aside>
                            </div>
                            <div className="rp-note">
                                <ShieldCheck size={18} />
                                <span>
                                    只把连接信息填写到可信应用中。到期后自动停用；续费或重置认证后通常在一分钟内同步。当前不提供
                                    UDP 转发。
                                </span>
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="rp-stats">
                                <div className="rp-card">
                                    <span>全部代理</span>
                                    <strong>
                                        {data.items.length}
                                        <small>个</small>
                                    </strong>
                                </div>
                                <div className="rp-card">
                                    <span>可用代理</span>
                                    <strong>
                                        {
                                            data.items.filter(
                                                (p) => p.status === "active",
                                            ).length
                                        }
                                        <small>个</small>
                                    </strong>
                                </div>
                                <div className="rp-card">
                                    <span>家宽固定代理</span>
                                    <strong>
                                        ¥{money(data.price)}
                                        <small>/ 月</small>
                                    </strong>
                                </div>
                            </div>
                            <section className="rp-card rp-list">
                                <div className="rp-toolbar">
                                    <div className="rp-tabs">
                                        {[
                                            ["all", "全部"],
                                            ["active", "可用"],
                                            ["provisioning", "正在同步"],
                                            ["expired", "已到期"],
                                        ].map(([id, label]) => (
                                            <button
                                                key={id}
                                                className={
                                                    filter === id
                                                        ? "active"
                                                        : ""
                                                }
                                                onClick={() => setFilter(id)}
                                            >
                                                {label}
                                            </button>
                                        ))}
                                    </div>
                                    <label className="rp-search">
                                        <Search size={16} />
                                        <input
                                            aria-label="搜索代理"
                                            value={search}
                                            placeholder="搜索名称、IP 或编号"
                                            onChange={(e) =>
                                                setSearch(e.target.value)
                                            }
                                        />
                                    </label>
                                </div>
                                {loading ? (
                                    <div className="rp-empty">
                                        正在加载你的代理…
                                    </div>
                                ) : !items.length ? (
                                    <div className="rp-empty">
                                        <Globe2 size={38} />
                                        <h3>
                                            {data.items.length
                                                ? "没有匹配的代理"
                                                : "还没有家宽代理"}
                                        </h3>
                                        <p>
                                            {data.available
                                                ? "购买后自动分配连接信息，支持 SOCKS5 和 HTTP。"
                                                : "当前暂无可售库存，请稍后再试。"}
                                        </p>
                                        {!!data.available && (
                                            <button
                                                className="rp-primary"
                                                onClick={() =>
                                                    setConfirm("buy")
                                                }
                                            >
                                                购买家宽代理 · ¥39 / 月
                                            </button>
                                        )}
                                    </div>
                                ) : (
                                    <div className="rp-table">
                                        <div className="rp-table-head">
                                            <span>代理 / 名称</span>
                                            <span>服务器地址</span>
                                            <span>协议 / 规格</span>
                                            <span>到期时间</span>
                                            <span>状态</span>
                                            <span />
                                        </div>
                                        {items.map((p) => (
                                            <button
                                                className="rp-row"
                                                key={p.id}
                                                disabled={busy}
                                                onClick={() =>
                                                    void action(() => choose(p))
                                                }
                                            >
                                                <span>
                                                    <b>🇺🇸 {p.name}</b>
                                                    <small>
                                                        PX-
                                                        {String(p.id).padStart(
                                                            5,
                                                            "0",
                                                        )}
                                                    </small>
                                                </span>
                                                <span className="rp-mono">
                                                    {p.address}:{p.port}
                                                </span>
                                                <span>
                                                    SOCKS5 / HTTP
                                                    <small>
                                                        100 Mbps · 不限量
                                                    </small>
                                                </span>
                                                <span>
                                                    {date(p.expires_at)}
                                                </span>
                                                <span
                                                    className={`rp-badge ${p.status}`}
                                                >
                                                    {statusNames[p.status]}
                                                </span>
                                                <span className="rp-manage">
                                                    管理 →
                                                </span>
                                            </button>
                                        ))}
                                    </div>
                                )}
                            </section>
                        </>
                    )}
                </>
            )}
            {confirm && (
                <div className="rp-overlay">
                    <section
                        className="rp-modal"
                        role="dialog"
                        aria-modal="true"
                        aria-label={
                            confirm === "reset"
                                ? "重置代理密码"
                                : "确认代理订单"
                        }
                    >
                        <h3>
                            {confirm === "reset"
                                ? "重置连接密码？"
                                : confirm === "renew"
                                  ? "续费家宽代理"
                                  : "购买家宽代理"}
                        </h3>
                        <p>
                            {confirm === "reset"
                                ? "旧连接信息将在同步后失效，请更新已配置的应用。"
                                : "¥39 / 一个月，最高 100 Mbps、不限累计流量。支持 SOCKS5 / HTTP；余额优先抵扣，剩余金额使用现有支付方式结算。"}
                        </p>
                        <div className="rp-actions">
                            <button
                                disabled={busy}
                                onClick={() => setConfirm(null)}
                            >
                                取消
                            </button>
                            <button
                                className="rp-primary"
                                disabled={busy}
                                onClick={() =>
                                    void action(async () => {
                                        if (confirm === "reset") {
                                            await request("update", {
                                                id: selected!.id,
                                                reset: true,
                                            });
                                            await load();
                                            setReveal(false);
                                        } else {
                                            const created =
                                                await request<Order>(
                                                    "save",
                                                    confirm === "renew"
                                                        ? { id: selected!.id }
                                                        : {},
                                                );
                                            await openOrder(created.trade_no);
                                            await load();
                                        }
                                        setConfirm(null);
                                    })
                                }
                            >
                                {busy ? "正在处理…" : "确认"}
                            </button>
                        </div>
                    </section>
                </div>
            )}
            {order && (
                <div className="rp-overlay">
                    <section
                        className="rp-modal"
                        role="dialog"
                        aria-modal="true"
                        aria-label="代理订单"
                    >
                        <h3>家宽代理订单</h3>
                        <p className="rp-muted">{order.trade_no}</p>
                        <dl className="rp-facts">
                            <div>
                                <dt>余额抵扣</dt>
                                <dd>¥{money(order.balance_amount)}</dd>
                            </div>
                            <div>
                                <dt>待支付</dt>
                                <dd>¥{money(order.total_amount)}</dd>
                            </div>
                            <div>
                                <dt>状态</dt>
                                <dd>
                                    {["待支付", "正在开通", "已取消", "已开通"][
                                        order.status
                                    ] || "已处理"}
                                </dd>
                            </div>
                        </dl>
                        {order.status === 0 && order.total_amount > 0 && (
                            <label className="rp-label">
                                支付方式
                                <select
                                    value={method}
                                    onChange={(e) =>
                                        setMethod(Number(e.target.value))
                                    }
                                >
                                    {methods.map((m) => (
                                        <option key={m.id} value={m.id}>
                                            {m.name}
                                        </option>
                                    ))}
                                </select>
                            </label>
                        )}
                        {qr && (
                            <img className="rp-qr" src={qr} alt="支付二维码" />
                        )}
                        <div className="rp-actions">
                            {order.status === 0 && (
                                <>
                                    <button
                                        disabled={busy}
                                        onClick={() =>
                                            void action(async () => {
                                                await request("cancel", {
                                                    trade_no: order.trade_no,
                                                });
                                                await openOrder(order.trade_no);
                                                await load();
                                            })
                                        }
                                    >
                                        取消订单
                                    </button>
                                    <button
                                        className="rp-primary"
                                        disabled={
                                            busy ||
                                            (order.total_amount > 0 && !method)
                                        }
                                        onClick={() =>
                                            void action(async () => {
                                                const result = await request<{
                                                    kind: string;
                                                    data: string | null;
                                                }>("checkout", {
                                                    trade_no: order.trade_no,
                                                    method,
                                                });
                                                if (
                                                    result.kind === "qr" &&
                                                    result.data
                                                )
                                                    setQr(
                                                        await QRCode.toDataURL(
                                                            result.data,
                                                        ),
                                                    );
                                                if (
                                                    result.kind === "url" &&
                                                    result.data
                                                ) {
                                                    const u = new URL(
                                                        result.data,
                                                    );
                                                    if (
                                                        ![
                                                            "https:",
                                                            "http:",
                                                        ].includes(
                                                            u.protocol,
                                                        ) ||
                                                        u.username ||
                                                        u.password
                                                    )
                                                        throw new Error(
                                                            "支付链接无效",
                                                        );
                                                    window.location.assign(
                                                        u.href,
                                                    );
                                                }
                                                setOrder(
                                                    await request<Order>(
                                                        "order",
                                                        {
                                                            trade_no:
                                                                order.trade_no,
                                                        },
                                                    ),
                                                );
                                                await load();
                                            })
                                        }
                                    >
                                        {order.total_amount
                                            ? "前往支付"
                                            : "确认开通"}
                                    </button>
                                </>
                            )}
                            <button
                                disabled={busy}
                                onClick={() =>
                                    void action(async () => {
                                        setOrder(
                                            await request<Order>("order", {
                                                trade_no: order.trade_no,
                                            }),
                                        );
                                        await load();
                                    })
                                }
                            >
                                刷新状态
                            </button>
                            <button
                                disabled={busy}
                                onClick={() => setOrder(null)}
                            >
                                关闭
                            </button>
                        </div>
                        <p className="rp-muted">
                            支付完成后点击刷新状态，以订单显示已开通为准。
                        </p>
                    </section>
                </div>
            )}
        </section>
    );
}
