import {
    ArrowRight,
    ExternalLink,
    RefreshCw,
    Wallet as WalletIcon,
} from "lucide-react";
import { money, orderStatuses, type Store } from "./store-model";

type Props = {
    loggedIn: boolean;
    balance: number | null;
    orders: Store["wallet_orders"];
    loading: boolean;
    error: string;
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
    onRefresh,
    onLogin,
    onPlans,
    onWeb,
}: Props) {
    return (
        <section
            className="card page-card store-page wallet-page"
            aria-label="钱包"
        >
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
                            {onPlans && (
                                <button
                                    className="primary-button"
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
