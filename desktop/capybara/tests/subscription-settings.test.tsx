import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SubscriptionSettings from "../src/SubscriptionSettings";
import { emptyNodes, useNodes, type NodeView } from "../src/nodes";
import { command } from "../src/bridge";

vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (error: Error) => error.message,
}));
afterEach(() => {
    cleanup();
    vi.resetAllMocks();
});
function Harness() {
    return <SubscriptionSettings nodes={useNodes()} />;
}

it("默认一小时；保存未确认时保留旧值且禁止重复操作，确认后展示持久化周期", async () => {
    let finish!: (value: NodeView) => void;
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "set_subscription_interval")
            return (await new Promise<NodeView>((r) => {
                finish = r;
            })) as never;
        return { ...emptyNodes, revision: 1 } as never;
    });
    render(<Harness />);
    const select = screen.getByRole("combobox", {
        name: "自动更新周期",
    }) as HTMLSelectElement;
    expect(select.disabled).toBe(true);
    await waitFor(() => expect(select.disabled).toBe(false));
    expect(select.value).toBe("3600");
    expect(select.options).toHaveLength(6);
    fireEvent.change(select, { target: { value: "10800" } });
    expect(select.disabled).toBe(true);
    expect(select.value).toBe("3600");
    expect(screen.getByText("正在保存…")).toBeTruthy();
    expect(command).toHaveBeenCalledWith("set_subscription_interval", {
        seconds: 10800,
    });
    await act(async () =>
        finish({
            ...emptyNodes,
            revision: 2,
            subscription_interval_seconds: 10800,
        }),
    );
    expect(select.value).toBe("10800");
    expect(select.disabled).toBe(false);
});
it("保存失败保留原周期，重开读取已保存设置且不自动写入", async () => {
    vi.mocked(command).mockImplementation(async (name) => {
        if (name === "set_subscription_interval")
            throw new Error("磁盘保存失败");
        return {
            ...emptyNodes,
            revision: 2,
            subscription_interval_seconds: 21600,
        } as never;
    });
    const { unmount } = render(<Harness />);
    const select = screen.getByRole("combobox", {
        name: "自动更新周期",
    }) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("21600"));
    expect(vi.mocked(command).mock.calls.map(([name]) => name)).toEqual([
        "nodes_snapshot",
    ]);
    fireEvent.change(select, { target: { value: "3600" } });
    await screen.findByText("磁盘保存失败");
    expect(select.value).toBe("21600");
    expect(select.disabled).toBe(false);
    unmount();
    render(<Harness />);
    await waitFor(() =>
        expect(
            (
                screen.getByRole("combobox", {
                    name: "自动更新周期",
                }) as HTMLSelectElement
            ).value,
        ).toBe("21600"),
    );
    expect(screen.queryByRole("alert")).toBeNull();
});
