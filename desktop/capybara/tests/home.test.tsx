import { afterEach, expect, it, vi } from "vitest";
import {
    cleanup,
    fireEvent,
    render,
    screen,
    within,
} from "@testing-library/react";
import Home, { nodeLocation } from "../src/Home";
import { emptyView, type View } from "../src/model";
import { emptyNodes } from "../src/nodes";

afterEach(cleanup);
function setup(overrides: Partial<View> = {}) {
    const view: View = {
        ...emptyView,
        logged_in: true,
        connection: "connected",
        ...overrides,
    };
    const nodes = {
        view: {
            ...emptyNodes,
            routes: [
                {
                    group: "默认连接",
                    selected: "新加坡 01",
                    choices: ["新加坡 01", "日本 02", "美国 03", "自动选择"],
                },
                {
                    group: "影音分流",
                    selected: "日本影音",
                    choices: ["日本影音", "香港影音"],
                },
            ],
        },
        pending: null,
        error: "",
        ready: true,
        subscriptionPending: null,
        subscriptionError: "",
        subscriptionMessage: "",
        refreshSubscription: vi.fn(async () => {}),
        setSubscriptionInterval: vi.fn(async () => {}),
        select: vi.fn(async () => {}),
        test: vi.fn(async () => {}),
    };
    const onAction = vi.fn(async () => {}),
        onPrimary = vi.fn();
    const props = {
        view,
        nodes,
        busy: "",
        eligible: true,
        primaryText: "断开连接",
        onPrimary,
        onAction,
        onPlans: vi.fn(),
        notice: null,
    };
    const result = render(<Home {...props} />);
    return { ...result, props, onAction, onPrimary };
}
it("搜索和地区筛选保留真实名称，切换始终提交对应分流组", () => {
    const { props } = setup();
    const panel = within(screen.getByRole("region", { name: "首页节点列表" }));
    fireEvent.click(panel.getByRole("button", { name: "亚洲", exact: true }));
    expect(
        panel.queryByRole("button", { name: "选择节点 美国 03" }),
    ).toBeNull();
    fireEvent.change(panel.getByRole("textbox", { name: "搜索节点" }), {
        target: { value: "日本" },
    });
    fireEvent.click(panel.getByRole("button", { name: "选择节点 日本 02" }));
    expect(props.nodes.select).toHaveBeenLastCalledWith("默认连接", "日本 02");
    fireEvent.change(panel.getByRole("combobox", { name: "选择分流组" }), {
        target: { value: "影音分流" },
    });
    expect(
        (panel.getByRole("textbox", { name: "搜索节点" }) as HTMLInputElement)
            .value,
    ).toBe("");
    fireEvent.click(panel.getByRole("button", { name: "选择节点 香港影音" }));
    expect(props.nodes.select).toHaveBeenLastCalledWith("影音分流", "香港影音");
});
it("登录后未连接即可选节点和测速，断开保留节点，注销不展示旧节点", () => {
    const { props, rerender } = setup({ connection: "disconnected" });
    fireEvent.click(screen.getByRole("button", { name: "选择节点 日本 02" }));
    expect(props.nodes.select).toHaveBeenCalledWith("默认连接", "日本 02");
    fireEvent.click(screen.getByRole("button", { name: "一键测速" }));
    expect(props.nodes.test).toHaveBeenCalledTimes(1);
    rerender(
        <Home {...props} view={{ ...props.view, connection: "connected" }} />,
    );
    rerender(<Home {...props} />);
    expect(
        screen.getByRole("button", { name: "选择节点 新加坡 01" }),
    ).toBeTruthy();
    rerender(<Home {...props} view={{ ...props.view, logged_in: false }} />);
    expect(
        screen.queryByRole("button", { name: "选择节点 新加坡 01" }),
    ).toBeNull();
});
it("切换立即提示处理中，确认前保留当前节点；延迟逐项显示", () => {
    const { props, rerender } = setup();
    rerender(
        <Home
            {...props}
            nodes={{
                ...props.nodes,
                pending: { group: "默认连接", name: "日本 02" },
                view: {
                    ...props.nodes.view,
                    testing: true,
                    delays: {
                        "新加坡 01": { status: "ok", ms: 42 },
                        "日本 02": { status: "pending", ms: null },
                        "美国 03": { status: "超时", ms: null },
                    },
                },
            }}
        />,
    );
    expect(screen.getByLabelText("正在切换")).toBeTruthy();
    expect(
        screen
            .getByRole("button", { name: "选择节点 新加坡 01" })
            .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
        screen
            .getByRole("button", { name: "选择节点 日本 02" })
            .getAttribute("aria-pressed"),
    ).toBe("false");
    expect(screen.getByText("42 ms")).toBeTruthy();
    expect(screen.getByText("超时")).toBeTruthy();
    expect(
        screen
            .getByRole("button", { name: "测速中 2/3" })
            .hasAttribute("disabled"),
    ).toBe(true);
});
it("资格不可用或正在处理时不能连接与重复切换", () => {
    const { props, rerender, onPrimary, onAction } = setup();
    rerender(<Home {...props} eligible={false} busy="select_route" />);
    fireEvent.click(
        screen.getByRole("button", { name: "断开连接", exact: true }),
    );
    fireEvent.click(screen.getByRole("button", { name: "选择节点 日本 02" }));
    expect(onPrimary).not.toHaveBeenCalled();
    expect(onAction).not.toHaveBeenCalled();
});
it("连接异常不显示成功状态，未测延迟和速度不伪造", () => {
    setup({ connection_error: "连接检测失败" });
    expect(screen.getByText("连接待检查")).toBeTruthy();
    expect(screen.queryByText("已连接", { exact: true })).toBeNull();
    expect(document.body.textContent).not.toMatch(/\d+\s*(ms|Mbps)/);
    expect(nodeLocation("未命名节点")).toEqual({ flag: "", region: "其他" });
});
it("更新订阅入口独立于流量刷新，空列表仍能更新且显示真实配置时间", () => {
    const { props, rerender, onAction } = setup({
        synced_at: 1_800_000_000,
        subscription: {
            status: "active",
            plan_name: "测试",
            expires_at: null,
            traffic: {
                total_bytes: 100,
                used_bytes: 0,
                remaining_bytes: 100,
                reset_at: null,
            },
            registered_device_count: 1,
            registered_device_limit: 3,
        },
    });
    rerender(
        <Home
            {...props}
            nodes={{ ...props.nodes, view: { ...emptyNodes, revision: 3 } }}
        />,
    );
    expect(screen.getByText("每 1 小时 自动更新")).toBeTruthy();
    expect(screen.getByText("上次更新：尚未更新")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "更新订阅" }));
    expect(props.nodes.refreshSubscription).toHaveBeenCalledTimes(1);
    expect(onAction).not.toHaveBeenCalled();
    expect(screen.queryByText(/线路已恢复|节点可用/)).toBeNull();
});
it("未登录、套餐不可用、更新或切换处理中不能触发订阅更新", () => {
    const { props, rerender } = setup({ logged_in: false });
    fireEvent.click(screen.getByRole("button", { name: "更新订阅" }));
    expect(props.nodes.refreshSubscription).not.toHaveBeenCalled();
    rerender(<Home {...props} view={{ ...props.view, logged_in: true }} />);
    expect(
        screen
            .getByRole("button", { name: "更新订阅" })
            .hasAttribute("disabled"),
    ).toBe(true);
    rerender(
        <Home
            {...props}
            view={{ ...props.view, logged_in: true }}
            nodes={{
                ...props.nodes,
                view: { ...props.nodes.view, loading: true },
            }}
        />,
    );
    expect(
        screen.getByRole("button", { name: "更新中" }).hasAttribute("disabled"),
    ).toBe(true);
    expect(
        screen
            .getByRole("button", { name: "选择节点 日本 02" })
            .hasAttribute("disabled"),
    ).toBe(true);
});
it("配置刷新失败保留成功时间和测速错误，不显示连接恢复", () => {
    const { props, rerender } = setup({ connection_error: "连接检测失败" });
    const updated = 1_700_000_000;
    rerender(
        <Home
            {...props}
            nodes={{
                ...props.nodes,
                subscriptionError: "订阅更新失败",
                view: {
                    ...props.nodes.view,
                    subscription_synced_at: updated,
                    error: "订阅更新失败",
                    delays: { "新加坡 01": { status: "超时", ms: null } },
                },
            }}
        />,
    );
    expect(screen.getByRole("alert").textContent).toBe("订阅更新失败");
    expect(screen.getByText(/上次更新：/).textContent).not.toContain(
        "尚未更新",
    );
    expect(screen.getByText("连接待检查")).toBeTruthy();
    expect(screen.getByText("超时")).toBeTruthy();
    rerender(
        <Home
            {...props}
            nodes={{ ...props.nodes, subscriptionMessage: "订阅已更新" }}
        />,
    );
    expect(screen.getByText("订阅已更新")).toBeTruthy();
    expect(screen.getByText("连接待检查")).toBeTruthy();
});
