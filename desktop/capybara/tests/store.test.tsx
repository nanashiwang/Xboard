import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import Plans from "../src/Plans";
import { command } from "../src/bridge";
import { emptyView } from "../src/model";
import { fee, type Order, type Store } from "../src/store-model";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (e: Error) => e.message,
}));
vi.mock("qrcode", () => ({
    default: { toDataURL: async () => "data:image/png;base64,preview" },
}));
const plan = {
    id: 1,
    name: "标准套餐",
    description: "每月重置流量",
    transfer_gb: 100,
    speed_mbps: null,
    device_limit: 3,
    current: false,
    purchasable: true,
    periods: [
        { id: "month_price", amount: 1234 },
        { id: "year_price", amount: 10000 },
    ],
};
const order: Order = {
    account_balance: 0,
    trade_no: "123456",
    plan_name: plan.name,
    period: "month_price",
    status: 0,
    total_amount: 1000,
    balance_amount: 234,
    discount_amount: 0,
    surplus_amount: 0,
    surplus_credit: 0,
    handling_amount: 0,
};
let data: Store;
const loggedIn = {
    ...emptyView,
    logged_in: true,
    profile: { name: "Test", email: "a@example.invalid" },
};
const refresh = vi.fn(),
    login = vi.fn();
const mount = (view = loggedIn) =>
    render(<Plans view={view} onLogin={login} onRefresh={refresh} />);
beforeEach(() => {
    data = {
        plans: [plan],
        balance: 234,
        methods: [
            {
                id: 1,
                name: "支付宝",
                handling_fee_fixed: 10,
                handling_fee_percent: 2.9,
            },
        ],
        order: null,
    };
    refresh.mockReset();
    login.mockReset();
    HTMLElement.prototype.scrollIntoView = vi.fn();
    vi.mocked(command)
        .mockReset()
        .mockImplementation(async (_, args) => {
            if (args?.action === "catalog")
                return structuredClone(data.plans) as never;
            if (args?.action === "index") return structuredClone(data) as never;
            if (args?.action === "save" || args?.action === "order")
                return structuredClone(order) as never;
            if (args?.action === "cancel")
                return { ...order, status: 2 } as never;
            return { kind: "url", data: null, order } as never;
        });
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

it("游客先浏览套餐，保留选择并登录，不发起订单", async () => {
    mount(emptyView);
    fireEvent.click(await screen.findByRole("button", { name: "选择套餐" }));
    fireEvent.click(screen.getByRole("radio", { name: /年付/ }));
    fireEvent.click(screen.getByRole("button", { name: "账号登录后购买" }));
    expect(login).toHaveBeenCalledOnce();
    expect(
        vi.mocked(command).mock.calls.some(([, a]) => a?.action === "save"),
    ).toBe(false);
});
it("周期和优惠码传递给后端，最终金额采用服务器订单并计算手续费", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "选择套餐" }));
    fireEvent.click(screen.getByRole("radio", { name: /年付/ }));
    fireEvent.change(screen.getByLabelText("优惠码（选填）"), {
        target: { value: " SAVE " },
    });
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    await screen.findByText("订单号 123456");
    expect(command).toHaveBeenCalledWith("store_request", {
        action: "save",
        payload: { plan_id: 1, period: "year_price", coupon_code: "SAVE" },
    });
    expect(screen.getByText("¥10.39")).toBeTruthy();
    expect(screen.getByText("−¥2.34")).toBeTruthy();
    expect(fee(1234, data.methods[0])).toBe(46);
});
it("恢复待支付订单，不允许重复下单，取消后可重新选择", async () => {
    data.order = order;
    mount();
    await screen.findByText("订单号 123456");
    expect(
        (screen.getByRole("button", { name: "选择套餐" }) as HTMLButtonElement)
            .disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "取消订单" }));
    await screen.findByText("已取消");
    expect(
        (screen.getByRole("button", { name: "选择套餐" }) as HTMLButtonElement)
            .disabled,
    ).toBe(false);
});
it("打开支付页不视为成功，只有服务器已开通才同步权益", async () => {
    data.order = order;
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "前往支付" }));
    await screen.findByText("支付页面已在浏览器打开，付款后这里会自动更新。");
    expect(refresh).not.toHaveBeenCalled();
    vi.mocked(command).mockResolvedValue({ ...order, status: 3 } as never);
    fireEvent.click(screen.getByRole("button", { name: "我已支付，刷新状态" }));
    await screen.findByText("已开通");
    expect(refresh).toHaveBeenCalledOnce();
});
it("零元订单无需选择支付方式，二维码支付可在客户端展示", async () => {
    data.order = { ...order, total_amount: 0 };
    data.methods = [];
    mount();
    const button = await screen.findByRole("button", { name: "确认开通" });
    expect((button as HTMLButtonElement).disabled).toBe(false);
    cleanup();
    data.order = order;
    data.methods = [
        {
            id: 1,
            name: "扫码支付",
            handling_fee_fixed: 0,
            handling_fee_percent: 0,
        },
    ];
    vi.mocked(command).mockImplementation(
        async (_, args) =>
            (args?.action === "index"
                ? data
                : {
                      kind: "qr",
                      data: "https://example.invalid/qr",
                      order,
                  }) as never,
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "前往支付" }));
    expect(await screen.findByAltText("订单支付二维码")).toBeTruthy();
});
it("下单响应丢失后找回订单，不自动再次下单，连点只发送一次", async () => {
    let rejectSave: (e: Error) => void = () => {};
    vi.mocked(command).mockImplementation(async (_, args) => {
        if (args?.action === "save")
            return new Promise((_, reject) => {
                rejectSave = reject;
            });
        return structuredClone(data) as never;
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "选择套餐" }));
    const button = screen.getByRole("button", { name: "创建订单" });
    fireEvent.click(button);
    fireEvent.click(button);
    data.order = order;
    await act(async () => rejectSave(new Error("请求超时，请刷新订单")));
    await screen.findByText("订单号 123456");
    expect(
        vi.mocked(command).mock.calls.filter(([, a]) => a?.action === "save"),
    ).toHaveLength(1);
});
it("空套餐和加载失败有明确状态；退出后不展示旧订单", async () => {
    data.plans = [];
    const ui = mount();
    await screen.findByText("暂无可购买套餐，请稍后再来看看。");
    data = { ...data, plans: [plan], order };
    fireEvent.click(screen.getByRole("button", { name: "刷新套餐" }));
    await screen.findByText("订单号 123456");
    ui.rerender(<Plans view={emptyView} onLogin={login} onRefresh={refresh} />);
    await waitFor(() => expect(screen.queryByText("订单号 123456")).toBeNull());
    vi.mocked(command).mockRejectedValue(new Error("服务正在准备中"));
    fireEvent.click(await screen.findByRole("button", { name: "刷新套餐" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
});
