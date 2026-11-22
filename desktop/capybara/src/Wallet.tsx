import { useState } from "react";
import {
    ArrowRight,
    ExternalLink,
    RefreshCw,
    Wallet as WalletIcon,
} from "lucide-react";
import { fee, money, orderStatuses, type Store } from "./store-model";

type Props = {
    loggedIn: boolean;
    balance: number | null;
    orders: Store["wallet_orders"];
    loading: boolean;
    error: string;
    busy: boolean;
    pendingOrder: boolean;
    methods: Store["topup_methods"];
    topups: Store["topups"];
    onTopUp: (amount: number, method: number) => void;
    onRefresh: () => void;
    onLogin: () => void;
    onPlans?: () => void;
    onWeb: () => void;
};

export default function Wallet({
    loggedIn,
    balance,
    orders,
    loading,
    error,
    busy,
    pendingOrder,
    methods,
    topups,
    onTopUp,
    onRefresh,
    onLogin,
    onPlans,
    onWeb,
}: Props) {
    const [editing, setEditing] = useState(false);
    const [amount, setAmount] = useState("");
    const [methodId, setMethodId] = useState(0);
    const method = methods?.find((m) => m.id === methodId) || methods?.[0];
    const cents = /^\d{1,5}(?:\.\d{1,2})?$/.test(amount)
        ? Math.round(Number(amount) * 100)
        : 0;
    const valid = cents > 0 && cents <= 1000000;
    return (
        <section className="wallet-content" aria-label="钱包">
            <div className="section-heading">
                <h2>钱包</h2>
                {loggedIn && (
                    <button
                        className="text-button"
                        disabled={loading}
                        onClick={onRefresh}
                    >
                        <RefreshCw
                            size={16}
                            className={loading ? "spin" : ""}
                        />
                        刷新余额
                    </button>
                )}
            </div>
            {loggedIn ? (
                <>
                    <div className="wallet-balance">
                        <span>
                            <WalletIcon size={20} />
                            可用余额
                        </span>
                        <strong>
                            {balance === null ? "—" : money(balance)}
                        </strong>
                        <p>
                            与网页版共用。购买套餐时自动抵扣，余额不足时可补付差额。
                        </p>
                        <div className="wallet-actions">
                            <button
                                className="primary-button"
                                disabled={busy || (loading && balance === null)}
                                aria-expanded={editing}
                                onClick={() => setEditing(!editing)}
                            >
                                充值
                            </button>
                            {onPlans && (
                                <button
                                    className="text-button"
                                    onClick={onPlans}
                                >
                                    购买套餐 <ArrowRight size={16} />
                                </button>
                            )}
                            <button className="text-button" onClick={onWeb}>
                                网页版钱包 <ExternalLink size={15} />
                            </button>
                        </div>
                    </div>
                    {editing &&
                        (pendingOrder ? (
                            <p role="status">请先处理当前未完成订单。</p>
                        ) : (
                            <form
                                className="store-checkout"
                                aria-label="钱包充值"
                                onSubmit={(e) => {
                                    e.preventDefault();
                                    if (valid && method && !busy)
                                        onTopUp(cents, method.id);
                                }}
                            >
                                <label className="coupon-label">
                                    充值金额（元）
                                    <input
                                        autoFocus
                                        inputMode="decimal"
                                        placeholder="0.01–10000.00"
                                        value={amount}
                                        maxLength={8}
                                        onChange={(e) =>
                                            setAmount(e.target.value)
                                        }
                                    />
                                </label>
                                {amount && !valid && (
                                    <p>
                                        请输入 0.01 至 10000 元，最多两位小数。
                                    </p>
                                )}
                                <fieldset className="store-options">
                                    <legend>充值支付方式</legend>
                                    {methods?.map((m) => (
                                        <label key={m.id}>
                                            <input
                                                type="radio"
                                                name="topup-method"
                                                checked={m.id === method?.id}
                                                onChange={() =>
                                                    setMethodId(m.id)
                                                }
                                            />
                                            {m.name}
                                        </label>
                                    ))}
                                    {!methods?.length && (
                                        <p>暂无可用的充值支付方式。</p>
                                    )}
                                </fieldset>
                                {valid && method && (
                                    <p>
                                        到账 {money(cents)}，手续费{" "}
                                        {money(fee(cents, method))}，合计{" "}
                                        {money(cents + fee(cents, method))}。
                                    </p>
                                )}
                                <button
                                    className="primary-button"
                                    type="submit"
                                    disabled={!valid || !method || busy}
                                >
                                    创建充值订单
                                </button>
                            </form>
                        ))}
                    {!!topups?.length && (
                        <>
                            <h3>最近充值</h3>
                            <ul className="wallet-orders">
                                {topups.map((t) => (
                                    <li key={t.trade_no}>
                                        <div>
                                            <strong>
                                                {money(t.total_amount)}
                                            </strong>
                                            <small>{t.trade_no}</small>
                                        </div>
                                        <span>
                                            {t.status === 3
                                                ? "已到账"
                                                : orderStatuses[t.status]}
                                        </span>
                                    </li>
                                ))}
                            </ul>
                        </>
                    )}
                    {error && (
                        <p role="alert" className="store-alert">
                            {error}
                        </p>
                    )}
                    <h3>最近套餐抵扣</h3>
                    {orders === undefined ? (
                        <p className="fine-print" role="status">
                            {loading
                                ? "正在读取抵扣记录…"
                                : "暂时无法读取抵扣记录。"}
                        </p>
                    ) : orders.length === 0 ? (
                        <p className="fine-print">
                            暂无使用钱包余额的套餐订单。
                        </p>
                    ) : (
                        <ul className="wallet-orders">
                            {orders.map((order) => (
                                <li key={order.trade_no}>
                                    <div>
                                        <strong>{order.plan_name}</strong>
                                        <small>
                                            {new Date(
                                                order.created_at * 1000,
                                            ).toLocaleDateString("zh-CN")}{" "}
                                            · {order.trade_no}
                                        </small>
                                    </div>
                                    <div>
                                        <strong>
                                            {money(order.balance_amount)}
                                        </strong>
                                        <small>
                                            {order.status === 2
                                                ? "已退回钱包"
                                                : `已抵扣 · ${orderStatuses[order.status] || "状态更新中"}`}
                                        </small>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </>
            ) : (
                <div className="wallet-balance">
                    <p>登录后可查看余额和套餐抵扣记录。</p>
                    <button className="primary-button" onClick={onLogin}>
                        登录账号
                    </button>
                </div>
            )}
        </section>
    );
}
