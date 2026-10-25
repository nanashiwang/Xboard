import type { Order, Store } from "./store-model";
const demo: Store = {
    balance: 500,
    order: null,
    plans: [
        {
            id: 1,
            name: "轻量套餐",
            transfer_gb: 100,
            speed_mbps: 100,
            device_limit: 3,
            description: "日常浏览与轻松连接\n每月重置流量",
            current: false,
            purchasable: true,
            periods: [
                { id: "month_price", amount: 1500 },
                { id: "year_price", amount: 15000 },
            ],
        },
        {
            id: 2,
            name: "标准套餐",
            transfer_gb: 200,
            speed_mbps: null,
            device_limit: 5,
            description: "多设备使用，从容畅享\n每月重置流量",
            current: true,
            purchasable: true,
            periods: [
                { id: "month_price", amount: 2500 },
                { id: "quarter_price", amount: 6800 },
                { id: "year_price", amount: 25000 },
            ],
        },
        {
            id: 3,
            name: "畅享套餐",
            transfer_gb: 500,
            speed_mbps: null,
            device_limit: 8,
            description: "更多流量，给热爱留足空间\n每月重置流量",
            current: false,
            purchasable: true,
            periods: [
                { id: "month_price", amount: 5000 },
                { id: "year_price", amount: 50000 },
            ],
        },
    ],
    methods: [
        {
            id: 1,
            name: "支付宝",
            handling_fee_fixed: 0,
            handling_fee_percent: 0,
        },
        {
            id: 2,
            name: "银行卡",
            handling_fee_fixed: 100,
            handling_fee_percent: 2.9,
        },
    ],
};
const sample: Order = {
    account_balance: 0,
    trade_no: "PREVIEW20261025",
    plan_name: "标准套餐",
    period: "month_price",
    total_amount: 2000,
    balance_amount: 500,
    discount_amount: 0,
    surplus_amount: 0,
    surplus_credit: 0,
    handling_amount: 0,
    status: 0,
};
let order: Order | null = null;
let initialized = false;
export async function storePreview(
    mode: string,
    action: string,
    payload?: Record<string, unknown>,
) {
    if (mode === "store-error")
        throw { message: "暂时无法获取套餐，请检查网络后重试。" };
    if (!initialized) {
        initialized = true;
        if (["store-pending", "store-processing"].includes(mode))
            order = { ...sample, status: mode === "store-processing" ? 1 : 0 };
    }
    if (action === "catalog")
        return structuredClone(
            mode === "store-empty"
                ? []
                : demo.plans.map((p) => ({ ...p, current: false })),
        );
    if (action === "index")
        return structuredClone({
            ...demo,
            order,
            plans: mode === "store-empty" ? [] : demo.plans,
        });
    if (action === "save") {
        const plan = demo.plans.find((p) => p.id === payload?.plan_id)!;
        const period = plan.periods.find((p) => p.id === payload?.period)!;
        order = {
            ...sample,
            plan_name: plan.name,
            period: period.id,
            total_amount: Math.max(0, period.amount - demo.balance),
        };
    }
    if (action === "cancel" && order) order.status = 2;
    if (action === "checkout" && order) {
        if (mode !== "store-qr") order.status = 3;
        return structuredClone({
            kind: mode === "store-qr" ? "qr" : "submitted",
            data:
                mode === "store-qr"
                    ? "https://example.invalid/preview-only"
                    : null,
            order,
        });
    }
    return structuredClone(order);
}
