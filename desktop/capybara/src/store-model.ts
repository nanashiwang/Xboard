export type Plan = {
    id: number;
    name: string;
    description: string;
    transfer_gb: number;
    speed_mbps: number | null;
    device_limit: number | null;
    current: boolean;
    purchasable: boolean;
    periods: { id: string; amount: number }[];
};
export type Order = {
    account_balance: number;
    trade_no: string;
    plan_name: string;
    period: string;
    status: number;
    total_amount: number;
    balance_amount: number;
    discount_amount: number;
    surplus_amount: number;
    surplus_credit: number;
    handling_amount: number;
};
export type PaymentMethod = {
    id: number;
    name: string;
    handling_fee_fixed: number | null;
    handling_fee_percent: number | null;
};
export type Store = {
    plans: Plan[];
    balance: number;
    order: Order | null;
    methods: PaymentMethod[];
};
export type Checkout = {
    kind: "url" | "qr" | "submitted";
    data: string | null;
    order: Order;
};
export const periods: Record<string, string> = {
    month_price: "月付",
    quarter_price: "季付",
    half_year_price: "半年付",
    year_price: "年付",
    two_year_price: "两年付",
    three_year_price: "三年付",
    onetime_price: "一次性",
    reset_price: "流量重置",
};
export const orderStatuses = [
    "待支付",
    "正在开通",
    "已取消",
    "已开通",
    "已折抵",
];
export const planDescription = (text: string) =>
    text
        .replace(/^#{1,6}\s+/gm, "")
        .replace(/^\s*[-*+]\s+/gm, "• ")
        .replace(/\*\*(.+?)\*\*/g, "$1");
export const money = (amount: number) =>
    new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency: "CNY",
    }).format(amount / 100);
export const fee = (amount: number, method?: PaymentMethod) =>
    amount > 0 && method
        ? Math.round(
              (amount * Number(method.handling_fee_percent || 0)) / 100 +
                  Number(method.handling_fee_fixed || 0),
          )
        : 0;
