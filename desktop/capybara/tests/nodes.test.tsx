import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { command } from "../src/bridge";
import { emptyView, type View } from "../src/model";
import {
    delayLabel,
    emptyNodes,
    latestNodes,
    useNodes,
    type NodeView,
    type NodeConnection,
} from "../src/nodes";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (e: Error) => e.message,
}));
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
    vi.useRealTimers();
});
it("订阅更新用专用命令、阻止重复及竞争操作，成功才推进配置时间", async () => {
    let resolve!: (view: NodeView) => void;
    const old = { ...loaded, subscription_synced_at: 100 };
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "refresh_subscription")
            return (await new Promise<NodeView>((r) => {
                resolve = r;
            })) as never;
        return old as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.ready).toBe(true));
    let pending!: Promise<void>;
    act(() => {
        pending = result.current.refreshSubscription();
    });
    expect(result.current.subscriptionPending).toBe("refresh");
    expect(result.current.view.subscription_synced_at).toBe(100);
    await act(async () => {
        await result.current.refreshSubscription();
        await result.current.setSubscriptionInterval(1800);
        await result.current.select("默认", "新节点");
        await result.current.test();
    });
    expect(vi.mocked(command).mock.calls.map(([name]) => name)).toEqual([
        "nodes_snapshot",
        "refresh_subscription",
    ]);
    await act(async () => {
        resolve({ ...old, revision: 4, subscription_synced_at: 200 });
        await pending;
    });
    expect(result.current.subscriptionPending).toBeNull();
    expect(result.current.view.subscription_synced_at).toBe(200);
    expect(result.current.subscriptionMessage).toBe("订阅已更新");
    await act(async () => {
        await result.current.refresh();
    });
    expect(result.current.view.subscription_synced_at).toBe(200);
    expect(result.current.view.revision).toBe(4);
});
it("订阅失败保留旧成功时间和节点，可重试且不伪造更新成功", async () => {
    const old = { ...loaded, subscription_synced_at: 100 };
    let failed = true;
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "refresh_subscription") {
            if (failed) throw new Error("更新未应用");
            return {
                ...old,
                revision: 4,
                subscription_synced_at: 200,
            } as never;
        }
        return old as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
        await result.current.refreshSubscription();
    });
    expect(result.current.subscriptionError).toBe("更新未应用");
    expect(result.current.subscriptionMessage).toBe("");
    expect(result.current.view.subscription_synced_at).toBe(100);
    expect(result.current.view.routes).toEqual(old.routes);
    expect(result.current.subscriptionPending).toBeNull();
    failed = false;
    await act(async () => {
        await result.current.refreshSubscription();
    });
    expect(result.current.subscriptionError).toBe("");
    expect(result.current.view.subscription_synced_at).toBe(200);
    expect(
        vi
            .mocked(command)
            .mock.calls.some(
                ([name]) => name === "connect" || name === "refresh",
            ),
    ).toBe(false);
});
it("周期保存以原生返回为准，失败不改值，旧轮询不覆盖持久化结果", async () => {
    let fail = true;
    vi.mocked(command).mockImplementation(async (name, args) => {
        if (name === "set_subscription_interval") {
            if (fail) throw new Error("周期保存失败");
            return {
                ...loaded,
                revision: 5,
                subscription_interval_seconds: args?.seconds,
            } as never;
        }
        return loaded as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.view.subscription_interval_seconds).toBe(3600);
    await act(async () => {
        await result.current.setSubscriptionInterval(10800);
    });
    expect(result.current.subscriptionError).toBe("周期保存失败");
    expect(result.current.view.subscription_interval_seconds).toBe(3600);
    fail = false;
    await act(async () => {
        await result.current.setSubscriptionInterval(10800);
    });
    expect(command).toHaveBeenCalledWith("set_subscription_interval", {
        seconds: 10800,
    });
    expect(result.current.view.subscription_interval_seconds).toBe(10800);
    await act(async () => {
        await result.current.refresh();
    });
    expect(result.current.view.subscription_interval_seconds).toBe(10800);
});
it("后续自动更新成功会清除过期的手动错误，旧快照不能误清除", async () => {
    let backend = { ...loaded, subscription_synced_at: 100 };
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "refresh_subscription") throw new Error("更新失败");
        return backend as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(async () => {
        await result.current.refreshSubscription();
    });
    await act(async () => {
        await result.current.refresh();
    });
    expect(result.current.subscriptionError).toBe("更新失败");
    backend = { ...backend, revision: 4, subscription_synced_at: 200 };
    await act(async () => {
        await result.current.refresh();
    });
    expect(result.current.subscriptionError).toBe("");
    expect(result.current.view.subscription_synced_at).toBe(200);
});
const loaded: NodeView = {
    ...emptyNodes,
    revision: 3,
    routes: [
        { group: "默认", selected: "旧节点", choices: ["旧节点", "新节点"] },
    ],
};
it("旧轮询不能覆盖新选择或注销后的空列表", () => {
    const selected = {
        ...loaded,
        revision: 4,
        routes: [{ ...loaded.routes[0], selected: "新节点" }],
    };
    expect(latestNodes(selected, loaded)).toBe(selected);
    const loggedOut = { ...emptyNodes, revision: 5 };
    expect(latestNodes(loggedOut, selected)).toBe(loggedOut);
    expect(delayLabel()).toBe("未测速");
    expect(delayLabel({ status: "超时", ms: null })).toBe("超时");
});
it("点击立即反馈，原生确认节点和连接后更新，重复点击不并发，失败可重试", async () => {
    let resolve!: (view: NodeConnection) => void;
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "select_and_connect")
            return (await new Promise<NodeConnection>((r) => {
                resolve = r;
            })) as never;
        return loaded as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.view.revision).toBe(3));
    let selecting!: Promise<View | void>;
    act(() => {
        selecting = result.current.select("默认", "新节点");
    });
    expect(result.current.pending?.name).toBe("新节点");
    expect(result.current.view.routes[0].selected).toBe("旧节点");
    await act(async () => {
        await result.current.select("默认", "旧节点");
    });
    expect(
        vi
            .mocked(command)
            .mock.calls.filter(([n]) => n === "select_and_connect"),
    ).toHaveLength(1);
    await act(async () => {
        resolve({
            view: { ...emptyView, connection: "connected" },
            nodes: {
                ...loaded,
                revision: 4,
                routes: [{ ...loaded.routes[0], selected: "新节点" }],
            },
        });
        expect((await selecting)?.connection).toBe("connected");
    });
    expect(result.current.pending).toBeNull();
    expect(result.current.view.routes[0].selected).toBe("新节点");
    vi.mocked(command).mockRejectedValueOnce(new Error("本地连接操作失败"));
    await act(async () => {
        await result.current.select("默认", "旧节点");
    });
    expect(result.current.error).toBe("本地连接操作失败");
    expect(result.current.view.routes[0].selected).toBe("新节点");
    expect(result.current.pending).toBeNull();
});
