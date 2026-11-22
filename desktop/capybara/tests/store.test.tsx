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

it("账号状态变化后丢弃迟到订单，并恢复新会话的购买按钮", async () => {
    let resolveSave: (value: unknown) => void = () => {};
    vi.mocked(command).mockImplementation(async (_, args) => {
        if (args?.action === "save")
            return new Promise((resolve) => {
                resolveSave = resolve;
            }) as never;
        if (args?.action === "catalog")
            return structuredClone(data.plans) as never;
        return structuredClone(data) as never;
    });
    const ui = mount();
    fireEvent.click(await screen.findByRole("button", { name: "选择套餐" }));
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    ui.rerender(<Plans view={emptyView} onLogin={login} onRefresh={refresh} />);
    const loginButton = await screen.findByRole("button", {
        name: "账号登录后购买",
    });
    expect((loginButton as HTMLButtonElement).disabled).toBe(false);
    await act(async () => resolveSave(order));
    expect(screen.queryByText("订单号 123456")).toBeNull();
    expect((loginButton as HTMLButtonElement).disabled).toBe(false);
});

it("后台预取与首次进入共用请求，重复切页直接显示已读套餐", async () => {
    let complete!: (value: Store) => void;
    vi.mocked(command).mockImplementation(
        () =>
            new Promise((resolve) => {
                complete = resolve;
            }) as never,
    );
    const page = (active: boolean) => (
        <Plans
            view={loggedIn}
            active={active}
            onLogin={login}
            onRefresh={refresh}
        />
    );
    const ui = render(page(false));
    expect(screen.queryByRole("heading", { name: "套餐" })).toBeNull();
    ui.rerender(page(true));
    await act(async () => complete(data));
    fireEvent.click(screen.getByRole("button", { name: "选择套餐" }));
    fireEvent.click(screen.getByRole("radio", { name: /年付/ }));
    ui.rerender(page(false));
    ui.rerender(page(true));
    expect(screen.getByRole("heading", { name: plan.name })).toBeTruthy();
    expect(
        (screen.getByRole("radio", { name: /年付/ }) as HTMLInputElement)
            .checked,
    ).toBe(true);
    expect(screen.queryByText("正在获取套餐与订单…")).toBeNull();
    expect(command).toHaveBeenCalledTimes(1);
});

it("目录过期后先显示原列表，后台更新价格和已下架套餐", async () => {
    vi.useFakeTimers();
    const page = (active: boolean) => (
        <Plans
            view={loggedIn}
            active={active}
            onLogin={login}
            onRefresh={refresh}
        />
    );
    const ui = render(page(false));
    await act(async () => {});
    await act(async () => vi.advanceTimersByTimeAsync(61_000));
    let complete!: (value: Store) => void;
    vi.mocked(command).mockImplementation(
        () =>
            new Promise((resolve) => {
                complete = resolve;
            }) as never,
    );
    ui.rerender(page(true));
    expect(screen.getByRole("heading", { name: plan.name })).toBeTruthy();
    expect(screen.queryByText("正在获取套餐与订单…")).toBeNull();
    await act(async () =>
        complete({
            ...data,
            plans: [
                {
                    ...plan,
                    id: 2,
                    name: "新套餐",
                    periods: [{ id: "month_price", amount: 2200 }],
                },
            ],
        }),
    );
    expect(screen.queryByRole("heading", { name: plan.name })).toBeNull();
    expect(screen.getByText("¥22.00")).toBeTruthy();
    expect(command).toHaveBeenCalledTimes(2);
});

it("首次加载失败会自行重试，离开套餐页暂停订单轮询", async () => {
    vi.useFakeTimers();
    vi.mocked(command).mockRejectedValueOnce(new Error("暂时超时"));
    data.order = order;
    const page = (active: boolean) => (
        <Plans
            view={loggedIn}
            active={active}
            onLogin={login}
            onRefresh={refresh}
        />
    );
    const ui = render(page(true));
    await act(async () => {});
    expect(screen.getByRole("alert").textContent).toContain("暂时超时");
    await act(async () => vi.advanceTimersByTimeAsync(15_000));
    expect(screen.getByText("订单号 123456")).toBeTruthy();
    ui.rerender(page(false));
    await act(async () => vi.advanceTimersByTimeAsync(30_000));
    expect(command).toHaveBeenCalledTimes(2);
});

it("换号期间丢弃上一账号预取结果，迟到的目录不能覆盖新建订单", async () => {
    let finishFirst!: (value: Store) => void;
    vi.mocked(command).mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                finishFirst = resolve;
            }) as never,
    );
    const page = (email: string) => (
        <Plans
            view={{ ...loggedIn, profile: { ...loggedIn.profile, email } }}
            onLogin={login}
            onRefresh={refresh}
        />
    );
    const ui = render(page("a@example.invalid"));
    ui.rerender(page("b@example.invalid"));
    await act(async () =>
        finishFirst({ ...data, order: { ...order, trade_no: "old-account" } }),
    );
    expect(screen.queryByText(/old-account/)).toBeNull();
    let finishRefresh!: (value: Store) => void;
    vi.mocked(command).mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                finishRefresh = resolve;
            }) as never,
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新套餐" }));
    fireEvent.click(screen.getByRole("button", { name: "选择套餐" }));
    fireEvent.click(screen.getByRole("button", { name: "创建订单" }));
    await screen.findByText("订单号 123456");
    await act(async () => finishRefresh({ ...data, order: null }));
    expect(screen.getByText("订单号 123456")).toBeTruthy();
});

it("钱包立即显示已读余额，修正网页版变动并区分取消退回", async () => {
    let complete!: (next: Store) => void;
    const goPlans = vi.fn();
    vi.mocked(command).mockImplementation(async (_, args) => {
        if (args?.action === "wallet")
            return new Promise((resolve) => {
                complete = resolve;
            }) as never;
        return structuredClone(data) as never;
    });
    const ui = mount();
    await screen.findByRole("button", { name: "选择套餐" });
    ui.rerender(
        <Plans
            wallet
            view={loggedIn}
            onPlans={goPlans}
            onLogin={login}
            onRefresh={refresh}
        />,
    );
    expect(screen.getByText("¥2.34")).toBeTruthy();
    await act(async () =>
        complete({
            ...data,
            balance: 500,
            wallet_orders: [{ ...order, status: 2, created_at: 1700000000 }],
        }),
    );
    expect(screen.getByText("¥5.00")).toBeTruthy();
    expect(screen.getByText("已退回钱包")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "购买套餐" }));
    expect(goPlans).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "网页版钱包" }));
    expect(command).toHaveBeenCalledWith("open_link", { target: "wallet" });
    fireEvent.focus(window);
    await act(async () => complete({ ...data, balance: 0, wallet_orders: [] }));
    expect(screen.getByText("¥0.00")).toBeTruthy();
    expect(screen.queryByText("已退回钱包")).toBeNull();
    ui.rerender(
        <Plans wallet view={emptyView} onLogin={login} onRefresh={refresh} />,
    );
    expect(screen.queryByText("¥0.00")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "登录账号" }));
    expect(login).toHaveBeenCalledOnce();
});

it("预取未完成时打开钱包会补读明细，访客不请求私人余额", async () => {
    let complete!: (next: Store) => void;
    vi.mocked(command).mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                complete = resolve;
            }) as never,
    );
    const ui = mount();
    ui.rerender(
        <Plans wallet view={loggedIn} onLogin={login} onRefresh={refresh} />,
    );
    vi.mocked(command).mockResolvedValue({
        ...data,
        wallet_orders: [],
    } as never);
    await act(async () => complete(data));
    expect(
        await screen.findByText("暂无使用钱包余额的套餐订单。"),
    ).toBeTruthy();
    expect(
        vi.mocked(command).mock.calls.filter(([, a]) => a?.action === "wallet"),
    ).toHaveLength(1);
    ui.unmount();
    vi.mocked(command).mockClear();
    render(
        <Plans wallet view={emptyView} onLogin={login} onRefresh={refresh} />,
    );
    await act(async () => {});
    expect(
        vi.mocked(command).mock.calls.some(([, a]) => a?.action === "wallet"),
    ).toBe(false);
});

it("可用余额旁创建独立充值，付款锁定所选通道，到账后更新余额", async () => {
    const second = {
        ...data.methods[0],
        id: 2,
        name: "银行卡",
        handling_fee_fixed: 50,
        handling_fee_percent: 0,
    };
    data.methods.push(second);
    data.topup_methods = data.methods;
    const funding = {
        ...order,
        product_type: "wallet_topup",
        payment_id: 2,
        plan_name: "钱包充值",
        total_amount: 3000,
        handling_amount: 50,
        balance_amount: 0,
        account_balance: data.balance,
    };
    vi.mocked(command).mockImplementation(async (_, args) => {
        if (args?.action === "topup") {
            data.order = funding;
            return structuredClone(funding) as never;
        }
        if (args?.action === "checkout") {
            data.order = null;
            data.balance = 3234;
            data.topups = [{ ...funding, status: 3 }];
            return {
                kind: "submitted",
                order: { ...funding, status: 3, account_balance: 3234 },
            } as never;
        }
        return structuredClone(data) as never;
    });
    render(
        <Plans wallet view={loggedIn} onLogin={login} onRefresh={refresh} />,
    );
    await screen.findByText("¥2.34");
    fireEvent.click(screen.getByRole("button", { name: "充值" }));
    const amount = screen.getByLabelText("充值金额（元）");
    fireEvent.change(amount, { target: { value: "1.001" } });
    const create = screen.getByRole("button", {
        name: "创建充值订单",
    }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    fireEvent.change(amount, { target: { value: "30.00" } });
    fireEvent.click(screen.getByRole("radio", { name: "银行卡" }));
    expect(screen.getByText(/手续费 ¥0.50，合计 ¥30.50/)).toBeTruthy();
    fireEvent.click(create);
    const pay = await screen.findByRole("button", { name: "前往支付" });
    expect(command).toHaveBeenCalledWith("store_request", {
        action: "topup",
        payload: { amount: 3000, method: 2 },
    });
    fireEvent.click(pay);
    expect(await screen.findByText("¥32.34")).toBeTruthy();
    expect(command).toHaveBeenCalledWith("store_request", {
        action: "checkout",
        payload: { trade_no: funding.trade_no, method: 2 },
    });
    expect(await screen.findByText("最近充值")).toBeTruthy();
});
