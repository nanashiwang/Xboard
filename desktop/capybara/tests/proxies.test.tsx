import { afterEach, expect, it, vi } from "vitest";
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import Proxies, { type ProxyRequest } from "../src/Proxies";
afterEach(cleanup);
const item = {
    id: 1,
    name: "工作代理",
    address: "216.36.108.173",
    port: 20001,
    status: "active",
    expires_at: 1900000000,
    checked_at: 1800000000,
};
function setup(items: unknown[] = [item], native = false) {
    const request = vi.fn(async (action: string) => {
        if (action === "index")
            return { price: 3900, available: 2, items, pending: null };
        if (action === "detail")
            return {
                ...item,
                credentials: {
                    username: "cp_testuser",
                    password: "secret-not-in-list",
                },
            };
        if (action === "save") return { trade_no: "test-order" };
        if (action === "order")
            return {
                trade_no: "test-order",
                status: 0,
                total_amount: 0,
                balance_amount: 3900,
            };
        if (action === "store") return { methods: [] };
        return {};
    });
    render(
        <Proxies
            request={request as ProxyRequest}
            loggedIn
            onLogin={() => {}}
            native={native}
        />,
    );
    return request;
}
it("shows real empty inventory and confirms before submitting a purchase", async () => {
    const request = setup([]);
    await screen.findByText("还没有家宽代理");
    fireEvent.click(screen.getByText("购买代理"));
    expect(request.mock.calls.some(([a]) => a === "save")).toBe(false);
    fireEvent.click(screen.getByText("确认"));
    await screen.findByRole("dialog", { name: "代理订单" });
    expect(request).toHaveBeenCalledWith("save", {});
    expect(screen.getByText("确认开通")).toBeTruthy();
});
it("loads credentials only on detail and connects by ID/protocol, never renderer-supplied credentials", async () => {
    const request = setup([item], true);
    await screen.findByText("🇺🇸 工作代理");
    expect(request.mock.calls.some(([a]) => a === "detail")).toBe(false);
    expect(screen.queryByText("secret-not-in-list")).toBeNull();
    fireEvent.click(screen.getByText("管理 →"));
    await screen.findByText("cp_testuser");
    expect(screen.queryByText("secret-not-in-list")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "HTTP", exact: true }));
    fireEvent.click(screen.getByText("连接此代理"));
    await waitFor(() =>
        expect(request).toHaveBeenCalledWith("connect", {
            id: 1,
            protocol: "HTTP",
        }),
    );
    fireEvent.click(screen.getByText("显示密码"));
    expect(screen.getByText("secret-not-in-list")).toBeTruthy();
});
it("does not send reset requests when the confirmation is cancelled", async () => {
    const request = setup();
    await screen.findByText("管理 →");
    fireEvent.click(screen.getByText("管理 →"));
    await screen.findByText("cp_testuser");
    fireEvent.click(screen.getByText("重置密码"));
    fireEvent.click(screen.getByRole("button", { name: "取消", exact: true }));
    expect(request.mock.calls.some(([a]) => a === "update")).toBe(false);
});
