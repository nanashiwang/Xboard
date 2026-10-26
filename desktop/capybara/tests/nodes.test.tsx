import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { command } from "../src/bridge";
import {
    delayLabel,
    emptyNodes,
    latestNodes,
    useNodes,
    type NodeView,
} from "../src/nodes";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (e: Error) => e.message,
}));
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
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
it("点击立即反馈，内核确认后切换，重复点击不并发，失败可重试", async () => {
    let resolve!: (view: NodeView) => void;
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "select_route")
            return (await new Promise<NodeView>((r) => {
                resolve = r;
            })) as never;
        return loaded as never;
    });
    const { result } = renderHook(useNodes);
    await waitFor(() => expect(result.current.view.revision).toBe(3));
    let selecting!: Promise<void>;
    act(() => {
        selecting = result.current.select("默认", "新节点");
    });
    expect(result.current.pending?.name).toBe("新节点");
    expect(result.current.view.routes[0].selected).toBe("旧节点");
    await act(async () => {
        await result.current.select("默认", "旧节点");
    });
    expect(
        vi.mocked(command).mock.calls.filter(([n]) => n === "select_route"),
    ).toHaveLength(1);
    await act(async () => {
        resolve({
            ...loaded,
            revision: 4,
            routes: [{ ...loaded.routes[0], selected: "新节点" }],
        });
        await selecting;
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
