import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react";
import {
    ArrowRight,
    CheckCircle2,
    Package,
    RefreshCw,
    ShoppingBag,
    Globe2,
} from "lucide-react";
import QRCode from "qrcode";
import Wallet from "./Wallet";
import { command, errorText } from "./bridge";
import type { View } from "./model";
import {
    fee,
    money,
    orderStatuses,
    periods,
    planDescription,
    type Checkout,
    type Order,
    type Plan,
    type Store,
} from "./store-model";
import "./store.css";

const request = <T,>(action: string, payload?: Record<string, unknown>) =>
    command<T>("store_request", { action, payload });
const catalogLifetime = 60_000;

export default function Plans({
    view,
    active = true,
    wallet = false,
    onPlans,
    onLogin,
    onRefresh,
}: {
    view: View;
    active?: boolean;
    wallet?: boolean;
    onPlans?: () => void;
    onLogin: () => void;
    onRefresh: () => void;
}) {
    const [store, setStore] = useState<Store>({
        plans: [],
        balance: 0,
        order: null,
        methods: [],
    });
    const [loading, setLoading] = useState(true),
        [busy, setBusy] = useState(false),
        [error, setError] = useState("");
    const [selected, setSelected] = useState<number | null>(null),
        [period, setPeriod] = useState("");
    const [coupon, setCoupon] = useState(""),
        [method, setMethod] = useState(0),
        [qr, setQr] = useState("");
    const [message, setMessage] = useState("");
    const generation = useRef(0),
        pending = useRef(false),
        fetching = useRef(false),
        orderVersion = useRef(0),
        loadedAt = useRef<number | null>(null),
        refreshed = useRef("");
    const [loadFailed, setLoadFailed] = useState(false);
    const walletVisible = useRef(wallet);
    walletVisible.current = wallet;
    const refreshAccount = useRef(onRefresh);
    refreshAccount.current = onRefresh;
    const checkoutRef = useRef<HTMLElement>(null);
    const plan = store.plans.find((p) => p.id === selected);
    const cycle = plan?.periods.find((p) => p.id === period);
    const order = store.order;
    const isTopup = order?.product_type === "wallet_topup";
    const payment = store.methods.find(
        (m) => m.id === (isTopup ? order.payment_id : method),
    );

    const load = useCallback(async (): Promise<void> => {
        if (fetching.current || pending.current) return;
        fetching.current = true;
        const run = generation.current;
        const version = orderVersion.current;
        const readWallet = view.logged_in && walletVisible.current;
        setLoading(true);
        setError("");
        try {
            const data = view.logged_in
                ? await request<Store>(readWallet ? "wallet" : "index")
                : {
                      plans: await request<Plan[]>("catalog"),
                      balance: 0,
                      methods: [],
                      order: null,
                  };
            if (run !== generation.current || version !== orderVersion.current)
                return;
            if (!Array.isArray(data?.plans) || !Array.isArray(data.methods))
                throw new Error("未能读取套餐列表，稍后将自动重试。");
            loadedAt.current = Date.now();
            setLoadFailed(false);
            setStore((old) => ({
                ...data,
                order:
                    data.order ||
                    (readWallet &&
                    old.order?.product_type === "wallet_topup" &&
                    [2, 3].includes(old.order.status)
                        ? old.order
                        : null),
                topups: readWallet ? data.topups : old.topups,
                topup_methods: readWallet
                    ? data.topup_methods
                    : old.topup_methods,
                wallet_orders: readWallet
                    ? data.wallet_orders
                    : old.wallet_orders,
            }));
            setMethod((old) =>
                data.methods.some((m) => m.id === old)
                    ? old
                    : data.methods[0]?.id || 0,
            );
        } catch (e) {
            if (
                run === generation.current &&
                version === orderVersion.current
            ) {
                setLoadFailed(true);
                setError(errorText(e));
            }
        } finally {
            if (run === generation.current) {
                fetching.current = false;
                setLoading(false);
                if (!readWallet && view.logged_in && walletVisible.current)
                    void load();
            }
        }
    }, [view.logged_in]);
    useLayoutEffect(() => {
        generation.current++;
        fetching.current = false;
        loadedAt.current = null;
        refreshed.current = "";
        pending.current = false;
        setBusy(false);
        setLoadFailed(false);
        setStore({ plans: [], balance: 0, methods: [], order: null });
        setCoupon("");
        setMethod(0);
        setQr("");
        setMessage("");
        void load();
        return () => {
            generation.current++;
        };
    }, [load, view.profile?.email]);

    const walletBusy = wallet && busy;
    useEffect(() => {
        if (!active || walletBusy) return;
        const maybeRefresh = () => {
            const age =
                loadedAt.current === null
                    ? Infinity
                    : Date.now() - loadedAt.current;
            if (
                !document.hidden &&
                ((wallet && view.logged_in) ||
                    age < 0 ||
                    age >= catalogLifetime)
            )
                void load();
        };
        maybeRefresh();
        document.addEventListener("visibilitychange", maybeRefresh);
        window.addEventListener("online", maybeRefresh);
        const pollWallet = wallet && view.logged_in;
        const timer = pollWallet
            ? window.setInterval(maybeRefresh, 30_000)
            : undefined;
        if (pollWallet) window.addEventListener("focus", maybeRefresh);
        return () => {
            window.clearInterval(timer);
            window.removeEventListener("focus", maybeRefresh);
            document.removeEventListener("visibilitychange", maybeRefresh);
            window.removeEventListener("online", maybeRefresh);
        };
    }, [active, wallet, load, view.logged_in, view.profile?.email, walletBusy]);
    useEffect(() => {
        if (!active || !loadFailed || loading || busy) return;
        const timer = setInterval(() => {
            if (!document.hidden) void load();
        }, 15_000);
        return () => clearInterval(timer);
    }, [active, loadFailed, loading, busy, load]);

    function acceptOrder(next: Order) {
        setStore((old) => ({
            ...old,
            order: next,
            balance: next.account_balance,
        }));
        if (next.status !== 0) setQr("");
        if (next.status === 3 && refreshed.current !== next.trade_no) {
            refreshed.current = next.trade_no;
            refreshAccount.current();
        }
    }
    async function checkOrder() {
        if (!order || pending.current) return;
        const run = generation.current;
        pending.current = true;
        orderVersion.current++;
        try {
            const next = await request<Order>("order", {
                trade_no: order.trade_no,
            });
            if (run === generation.current) {
                acceptOrder(next);
                setError("");
            }
        } catch (e) {
            if (run === generation.current) setError(errorText(e));
        } finally {
            if (run === generation.current) pending.current = false;
        }
    }
    useEffect(() => {
        if (
            !active ||
            (wallet && !isTopup) ||
            !order ||
            ![0, 1].includes(order.status)
        )
            return;
        const timer = setInterval(() => {
            if (!document.hidden && !fetching.current) void checkOrder();
        }, 5000);
        return () => clearInterval(timer);
    }, [active, wallet, isTopup, order?.trade_no, order?.status]);

    async function mutate(
        action: "save" | "checkout" | "cancel" | "topup",
        topup?: { amount: number; method: number },
    ) {
        if (pending.current || busy) return;
        pending.current = true;
        orderVersion.current++;
        setBusy(true);
        setError("");
        setMessage("");
        setQr("");
        const run = generation.current;
        try {
            if (action === "checkout" && order) {
                const result = await request<Checkout>(action, {
                    trade_no: order.trade_no,
                    method: payment?.id || null,
                });
                if (run !== generation.current) return;
                acceptOrder(result.order);
                if (result.kind === "qr" && result.data) {
                    const image = await QRCode.toDataURL(result.data, {
                        width: 256,
                        margin: 4,
                        errorCorrectionLevel: "M",
                    });
                    if (run === generation.current) {
                        setQr(image);
                        setMessage("请使用对应支付应用扫码付款。");
                    }
                } else
                    setMessage(
                        result.kind === "url"
                            ? "支付页面已在浏览器打开，付款后这里会自动更新。"
                            : isTopup
                              ? "付款已提交，正在确认到账。"
                              : "付款已提交，正在确认开通结果。",
                    );
            } else {
                const next = await request<Order>(
                    action,
                    action === "topup"
                        ? topup
                        : action === "save"
                          ? {
                                plan_id: selected,
                                period,
                                coupon_code: coupon.trim() || null,
                            }
                          : { trade_no: order?.trade_no },
                );
                if (run === generation.current) {
                    acceptOrder(next);
                    if (action === "topup")
                        requestAnimationFrame(() =>
                            checkoutRef.current?.focus(),
                        );
                }
            }
        } catch (e) {
            if (run !== generation.current) return;
            // Recover an order created before a lost response; never repeat the mutation automatically.
            if (action === "save" || action === "topup") {
                try {
                    const latest = await request<Store>(
                        walletVisible.current ? "wallet" : "index",
                    );
                    if (run === generation.current) setStore(latest);
                } catch {
                    /* Keep the original actionable error. */
                }
            }
            if (run === generation.current) setError(errorText(e));
        } finally {
            if (run === generation.current) {
                pending.current = false;
                setBusy(false);
            }
        }
    }
    if (!active) return null;
    const walletPanel = (
        <Wallet
            key={view.profile?.email || "guest"}
            loggedIn={view.logged_in}
            busy={busy}
            pendingOrder={!!order && [0, 1].includes(order.status)}
            methods={store.topup_methods}
            topups={store.topups}
            onTopUp={(amount, method) =>
                void mutate("topup", { amount, method })
            }
            balance={loadedAt.current === null ? null : store.balance}
            orders={store.wallet_orders}
            loading={loading}
            error={error}
            onRefresh={() => void load()}
            onLogin={onLogin}
            onPlans={onPlans}
            onWeb={() =>
                void command("open_link", { target: "wallet" }).catch((e) =>
                    setError(errorText(e)),
                )
            }
        />
    );
    const activeOrder = order && [0, 1].includes(order.status);
    return (
        <section
            className={`card page-card store-page${wallet ? " wallet-page" : ""}`}
        >
            {wallet ? (
                walletPanel
            ) : (
                <>
                    <div className="section-heading">
                        <div>
                            <span className="eyebrow">
                                A LITTLE MORE FREEDOM
                            </span>
                            <h2>套餐</h2>
                            <p>选一个适合你的套餐，轻松连接更大的世界。</p>
                        </div>
                        <ShoppingBag size={35} />
                    </div>
                    <div className="store-toolbar">
                        <span>
                            {view.logged_in ? (
                                <>
                                    当前套餐：
                                    {view.subscription?.plan_name || "暂无套餐"}
                                    {loadedAt.current !== null && !error && (
                                        <span className="store-balance">
                                            账户余额 {money(store.balance)}
                                        </span>
                                    )}
                                </>
                            ) : (
                                "先看看套餐，登录后即可购买。"
                            )}
                        </span>
                        <button
                            className="text-button"
                            disabled={busy || loading}
                            onClick={() => void load()}
                        >
                            <RefreshCw
                                size={16}
                                className={loading ? "spin" : ""}
                            />
                            刷新套餐
                        </button>
                    </div>
                    {error && (
                        <div className="store-alert" role="alert">
                            <p>{error}</p>
                            <button
                                className="text-button"
                                onClick={() =>
                                    void command("open_link", {
                                        target: "plans",
                                    }).catch((e) => setError(errorText(e)))
                                }
                            >
                                前往网站购买或管理订单 <Globe2 size={16} />
                            </button>
                        </div>
                    )}
                    {loading && loadedAt.current === null ? (
                        <p className="store-empty" role="status">
                            正在获取套餐与订单…
                        </p>
                    ) : (
                        <>
                            {store.plans.length === 0 && !error && (
                                <p className="store-empty">
                                    暂无可购买套餐，请稍后再来看看。
                                </p>
                            )}
                            <div className="plan-grid">
                                {store.plans.map((item) => (
                                    <article
                                        className={
                                            "plan-card" +
                                            (item.id === selected
                                                ? " selected"
                                                : "")
                                        }
                                        key={item.id}
                                    >
                                        <div className="plan-name">
                                            <Package size={22} />
                                            <h3>{item.name}</h3>
                                            {item.current && (
                                                <span>当前套餐</span>
                                            )}
                                        </div>
                                        <div className="plan-price">
                                            {item.periods.length ? (
                                                <>
                                                    <strong>
                                                        {money(
                                                            Math.min(
                                                                ...item.periods.map(
                                                                    (p) =>
                                                                        p.amount,
                                                                ),
                                                            ),
                                                        )}
                                                    </strong>
                                                    <span>起</span>
                                                </>
                                            ) : (
                                                <strong>暂不可购买</strong>
                                            )}
                                        </div>
                                        <ul className="plan-facts">
                                            <li>
                                                <CheckCircle2 size={16} />
                                                {item.transfer_gb} GB 套餐流量
                                            </li>
                                            <li>
                                                <CheckCircle2 size={16} />
                                                {item.speed_mbps
                                                    ? `${item.speed_mbps} Mbps 速率上限`
                                                    : "不限速率"}
                                            </li>
                                            <li>
                                                <CheckCircle2 size={16} />
                                                {item.device_limit
                                                    ? `${item.device_limit} 个 IP 同时在线`
                                                    : "不限同时在线 IP"}
                                            </li>
                                        </ul>
                                        {item.description && (
                                            <p className="plan-description">
                                                {planDescription(
                                                    item.description,
                                                )}
                                            </p>
                                        )}
                                        <button
                                            className="primary-button"
                                            disabled={
                                                !!activeOrder ||
                                                busy ||
                                                !item.purchasable ||
                                                !item.periods.length
                                            }
                                            onClick={() => {
                                                setSelected(item.id);
                                                setPeriod(
                                                    item.periods[0]?.id || "",
                                                );
                                                setCoupon("");
                                                setStore((old) => ({
                                                    ...old,
                                                    order: null,
                                                }));
                                                setMessage("");
                                                setTimeout(
                                                    () =>
                                                        checkoutRef.current?.scrollIntoView(
                                                            {
                                                                behavior:
                                                                    "smooth",
                                                                block: "nearest",
                                                            },
                                                        ),
                                                    0,
                                                );
                                            }}
                                        >
                                            {!item.purchasable
                                                ? "暂不可续费"
                                                : item.current
                                                  ? "续费套餐"
                                                  : "选择套餐"}
                                            <ArrowRight size={17} />
                                        </button>
                                    </article>
                                ))}
                            </div>
                        </>
                    )}
                </>
            )}
            {(wallet ? isTopup : order || plan) && (
                <section
                    className="store-checkout"
                    ref={checkoutRef}
                    tabIndex={-1}
                    aria-label={isTopup ? "充值订单" : "套餐订单"}
                >
                    {order ? (
                        <>
                            <div className="order-heading">
                                <div>
                                    <span className="eyebrow">YOUR ORDER</span>
                                    <h3>
                                        {order.plan_name}
                                        {!isTopup &&
                                            ` · ${periods[order.period] || order.period}`}
                                    </h3>
                                    <p className="fine-print">
                                        订单号 {order.trade_no}
                                    </p>
                                </div>
                                <b
                                    className={
                                        order.status === 3
                                            ? "order-complete"
                                            : ""
                                    }
                                >
                                    {(isTopup && order.status === 3
                                        ? "已到账"
                                        : orderStatuses[order.status]) ||
                                        "订单状态更新中"}
                                </b>
                            </div>
                            <div className="order-breakdown">
                                {order.discount_amount > 0 && (
                                    <p>
                                        优惠抵扣{" "}
                                        <span>
                                            −{money(order.discount_amount)}
                                        </span>
                                    </p>
                                )}
                                {order.surplus_amount > 0 && (
                                    <p>
                                        原套餐折抵{" "}
                                        <span>
                                            −{money(order.surplus_amount)}
                                        </span>
                                    </p>
                                )}
                                {order.balance_amount > 0 && (
                                    <p>
                                        {order.status === 2
                                            ? "已退回钱包"
                                            : "钱包余额抵扣"}{" "}
                                        <span>
                                            {order.status === 2 ? "" : "−"}
                                            {money(order.balance_amount)}
                                        </span>
                                    </p>
                                )}
                                {order.surplus_credit > 0 && (
                                    <p>
                                        开通后退回余额{" "}
                                        <span>
                                            {money(order.surplus_credit)}
                                        </span>
                                    </p>
                                )}
                                <p>
                                    订单金额{" "}
                                    <span>{money(order.total_amount)}</span>
                                </p>
                                <p>
                                    支付手续费{" "}
                                    <span>
                                        {money(
                                            order.status === 0 && !isTopup
                                                ? fee(
                                                      order.total_amount,
                                                      payment,
                                                  )
                                                : order.handling_amount,
                                        )}
                                    </span>
                                </p>
                                <p className="order-total">
                                    {order.status === 0 ? "待支付" : "支付金额"}
                                    <strong>
                                        {money(
                                            order.total_amount +
                                                (order.status === 0 && !isTopup
                                                    ? fee(
                                                          order.total_amount,
                                                          payment,
                                                      )
                                                    : order.handling_amount),
                                        )}
                                    </strong>
                                </p>
                            </div>
                            {order.status === 0 && (
                                <>
                                    {order.total_amount > 0 && !isTopup && (
                                        <fieldset className="store-options">
                                            <legend>支付方式</legend>
                                            {store.methods.length ? (
                                                store.methods.map((m) => (
                                                    <label key={m.id}>
                                                        <input
                                                            type="radio"
                                                            name="payment"
                                                            value={m.id}
                                                            checked={
                                                                m.id === method
                                                            }
                                                            disabled={busy}
                                                            onChange={() => {
                                                                setMethod(m.id);
                                                                setQr("");
                                                                setMessage("");
                                                            }}
                                                        />
                                                        {m.name}
                                                    </label>
                                                ))
                                            ) : (
                                                <p>
                                                    暂未提供可用支付方式，请稍后重试或联系客服。
                                                </p>
                                            )}
                                        </fieldset>
                                    )}
                                    {isTopup && (
                                        <p>
                                            支付方式：
                                            {payment?.name || "当前通道不可用"}
                                        </p>
                                    )}
                                    {qr && (
                                        <img
                                            className="payment-qr"
                                            src={qr}
                                            alt="订单支付二维码"
                                        />
                                    )}
                                    <div className="store-actions">
                                        <button
                                            className="primary-button fit"
                                            disabled={
                                                busy ||
                                                (order.total_amount > 0 &&
                                                    !payment)
                                            }
                                            onClick={() =>
                                                void mutate("checkout")
                                            }
                                        >
                                            {busy
                                                ? "正在处理…"
                                                : order.total_amount === 0
                                                  ? "确认开通"
                                                  : "前往支付"}
                                            <ArrowRight size={17} />
                                        </button>
                                        <button
                                            className="text-button"
                                            disabled={busy}
                                            onClick={() =>
                                                void mutate("cancel")
                                            }
                                        >
                                            取消订单
                                        </button>
                                        <button
                                            className="text-button"
                                            disabled={busy}
                                            onClick={() => void checkOrder()}
                                        >
                                            我已支付，刷新状态
                                        </button>
                                    </div>
                                </>
                            )}
                            {order.status === 1 && (
                                <p role="status">
                                    付款已确认，正在开通套餐，请稍候。
                                    <button
                                        className="text-button"
                                        onClick={() => void checkOrder()}
                                    >
                                        刷新状态
                                    </button>
                                </p>
                            )}
                            {order.status === 3 && (
                                <p role="status">
                                    {isTopup
                                        ? "充值已到账，可用余额已更新。"
                                        : "套餐已开通，账户权益正在同步。"}
                                </p>
                            )}
                            {[2, 3, 4].includes(order.status) && (
                                <button
                                    className="text-button"
                                    onClick={() => {
                                        setStore((old) => ({
                                            ...old,
                                            order: null,
                                        }));
                                        setSelected(null);
                                        setMessage("");
                                        void load();
                                    }}
                                >
                                    {wallet ? "返回钱包" : "返回套餐列表"}
                                </button>
                            )}
                        </>
                    ) : (
                        plan && (
                            <>
                                <h3>购买 {plan.name}</h3>
                                <fieldset className="store-options">
                                    <legend>选择购买周期</legend>
                                    {plan.periods.map((p) => (
                                        <label key={p.id}>
                                            <input
                                                type="radio"
                                                name="period"
                                                checked={p.id === period}
                                                onChange={() => setPeriod(p.id)}
                                                disabled={busy}
                                            />
                                            {periods[p.id] || p.id}
                                            <b>{money(p.amount)}</b>
                                        </label>
                                    ))}
                                </fieldset>
                                <label className="coupon-label">
                                    优惠码（选填）
                                    <input
                                        value={coupon}
                                        maxLength={128}
                                        disabled={busy}
                                        placeholder="有优惠码可以在这里填写"
                                        onChange={(e) =>
                                            setCoupon(e.target.value)
                                        }
                                    />
                                </label>
                                <p className="fine-print">
                                    {view.logged_in
                                        ? `当前钱包余额 ${money(store.balance)}。创建订单时优先抵扣余额，不足部分在下一步支付。`
                                        : "登录后可用钱包余额抵扣套餐费用。"}{" "}
                                    折扣和原套餐折抵以订单金额为准。
                                </p>
                                <button
                                    className="primary-button fit"
                                    disabled={
                                        busy ||
                                        !cycle ||
                                        !plan.purchasable ||
                                        !!view.browser_login
                                    }
                                    onClick={
                                        view.logged_in
                                            ? () => void mutate("save")
                                            : onLogin
                                    }
                                >
                                    {busy
                                        ? "正在创建订单…"
                                        : view.logged_in
                                          ? "创建订单"
                                          : "账号登录后购买"}
                                    <ArrowRight size={17} />
                                </button>
                            </>
                        )
                    )}
                    {message && (
                        <p className="store-message" role="status">
                            {message}
                        </p>
                    )}
                </section>
            )}
        </section>
    );
}
