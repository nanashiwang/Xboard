import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import App from "../src/App";
import { command } from "../src/bridge";
import { emptyView, type View } from "../src/model";
import { emptyNodes, type NodeView } from "../src/nodes";
import { emptyRouting, type RoutingView } from "../src/routing-model";

vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    preview: null,
    native: false,
    errorText: (error: { message: string }) => error.message,
}));

type SelectionResult = { view: View; nodes: NodeView };
function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<T>((yes, no) => {
        resolve = yes;
        reject = no;
    });
    return { promise, resolve, reject };
}

let backend: View;
let nodeBackend: NodeView;
let routingBackend: RoutingView;
let select: (args: Record<string, unknown>) => Promise<SelectionResult>;
let snapshots: (() => Promise<View>)[];
const invoke = vi.mocked(command);
const calls = (name: string) =>
    invoke.mock.calls.filter(([commandName]) => commandName === name);
const nodeButton = (name: string) =>
    screen.getByRole<HTMLButtonElement>("button", {
        name: `选择节点 ${name}`,
        exact: true,
    });
const powerButton = () =>
    document.querySelector<HTMLButtonElement>("button.journey-power")!;
function connectedResult(name: string, connectionError: string | null = null) {
    backend = {
        ...backend,
        connection: "connected",
        connection_error: connectionError,
    };
    nodeBackend = {
        ...nodeBackend,
        revision: nodeBackend.revision + 1,
        routes: [{ ...nodeBackend.routes[0], selected: name }],
    };
    return structuredClone({ view: backend, nodes: nodeBackend });
}

beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
    HTMLDialogElement.prototype.showModal = function () {
        this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
        this.removeAttribute("open");
    };
    backend = {
        ...emptyView,
        logged_in: true,
        platform: "windows",
        profile: { name: "测试用户", email: "test@example.invalid" },
        subscription: {
            status: "active",
            plan_name: "测试套餐",
            expires_at: null,
            traffic: {
                total_bytes: 100 * 1073741824,
                used_bytes: 0,
                remaining_bytes: 100 * 1073741824,
                reset_at: null,
            },
            registered_device_count: 1,
            registered_device_limit: 3,
        },
    };
    nodeBackend = {
        ...emptyNodes,
        revision: 1,
        subscription_synced_at: 1_800_000_000,
        routes: [
            {
                group: "默认连接",
                selected: "日本 01",
                choices: ["日本 01", "美国 02"],
            },
        ],
    };
    routingBackend = {
        ...structuredClone(emptyRouting),
        ready: true,
        targets: ["默认连接", "日本 01", "美国 02"],
    };
    snapshots = [];
    select = async (args) => connectedResult(String(args.name));
    invoke.mockReset().mockImplementation(async (name, args) => {
        if (name === "snapshot") {
            const queued = snapshots.shift();
            return (
                queued ? await queued() : structuredClone(backend)
            ) as never;
        }
        if (name === "nodes_snapshot")
            return structuredClone(nodeBackend) as never;
        if (name === "routing_snapshot")
            return structuredClone(routingBackend) as never;
        if (name === "select_and_connect")
            return (await select(args || {})) as never;
        if (name === "connect" || name === "disconnect") {
            backend = {
                ...backend,
                connection: name === "connect" ? "connected" : "disconnected",
                connection_error: null,
            };
            return structuredClone(backend) as never;
        }
        throw new Error(`Unexpected command: ${name}`);
    });
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

async function mount() {
    await act(async () => {
        render(<App />);
    });
    expect(nodeButton("美国 02").disabled).toBe(false);
    expect(
        screen.getByRole<HTMLButtonElement>("button", {
            name: "全局",
            exact: true,
        }).disabled,
    ).toBe(false);
}

it.each(["美国 02", "日本 01"])(
    "未连接时点击 %s 即连接，当前已选节点也能发起连接",
    async (name) => {
        await mount();
        expect(powerButton().getAttribute("aria-label")).toBe("一键连接");
        fireEvent.click(nodeButton(name));
        await waitFor(() =>
            expect(powerButton().getAttribute("aria-label")).toBe("断开连接"),
        );
        expect(calls("select_and_connect")).toEqual([
            ["select_and_connect", { group: "默认连接", name }],
        ]);
        expect(nodeButton(name).getAttribute("aria-pressed")).toBe("true");
        expect(
            screen.getByText("已连接", { selector: ".connection-state" }),
        ).toBeTruthy();
        expect(calls("select_route")).toHaveLength(0);
        expect(calls("connect")).toHaveLength(0);
        expect(calls("disconnect")).toHaveLength(0);
    },
);

it("已连接切换节点保留连接，主按钮随后仍可明确断开", async () => {
    backend.connection = "connected";
    await mount();
    fireEvent.click(nodeButton("美国 02"));
    await waitFor(() =>
        expect(nodeButton("美国 02").getAttribute("aria-pressed")).toBe("true"),
    );
    expect(powerButton().getAttribute("aria-label")).toBe("断开连接");
    expect(calls("select_and_connect")).toHaveLength(1);
    expect(calls("connect")).toHaveLength(0);
    expect(calls("disconnect")).toHaveLength(0);
    fireEvent.click(powerButton());
    await waitFor(() =>
        expect(powerButton().getAttribute("aria-label")).toBe("一键连接"),
    );
    expect(calls("disconnect")).toHaveLength(1);
});

it("选择连接失败保持未连接和原节点，显示错误后可重试", async () => {
    select = async () => {
        throw new Error("节点已失效，请重新选择");
    };
    await mount();
    fireEvent.click(nodeButton("美国 02"));
    await waitFor(() => expect(nodeButton("美国 02").disabled).toBe(false));
    expect(
        screen.getAllByText("节点已失效，请重新选择").length,
    ).toBeGreaterThan(0);
    expect(powerButton().getAttribute("aria-label")).toBe("一键连接");
    expect(nodeButton("日本 01").getAttribute("aria-pressed")).toBe("true");
    expect(calls("connect")).toHaveLength(0);
    select = async (args) => connectedResult(String(args.name));
    fireEvent.click(nodeButton("美国 02"));
    await waitFor(() =>
        expect(powerButton().getAttribute("aria-label")).toBe("断开连接"),
    );
    expect(calls("select_and_connect")).toHaveLength(2);
    expect(screen.queryByText("节点已失效，请重新选择")).toBeNull();
});

it("选择失败后回读真实断开状态和失效套餐，不保留旧的已连接显示", async () => {
    backend.connection = "connected";
    select = async () => {
        backend = {
            ...backend,
            connection: "disconnected",
            subscription: { ...backend.subscription!, status: "expired" },
        };
        nodeBackend = { ...emptyNodes, revision: nodeBackend.revision + 1 };
        throw new Error("套餐已到期，连接已停止");
    };
    await mount();
    fireEvent.click(nodeButton("美国 02"));
    await waitFor(() =>
        expect(powerButton().getAttribute("aria-label")).toBe("一键连接"),
    );
    expect(powerButton().disabled).toBe(true);
    expect(
        screen.queryByRole("button", { name: "选择节点 日本 01" }),
    ).toBeNull();
    expect(
        screen.getByText("未连接", { selector: ".connection-state" }),
    ).toBeTruthy();
});

it("节点连接处理中阻止重复点击、连接按钮、模式和订阅更新", async () => {
    const pending = deferred<SelectionResult>();
    select = () => pending.promise;
    await mount();
    const otherNode = nodeButton("日本 01");
    const power = powerButton();
    const mode = screen.getByRole<HTMLButtonElement>("button", {
        name: "全局",
        exact: true,
    });
    const refresh = screen.getByRole<HTMLButtonElement>("button", {
        name: "更新订阅",
        exact: true,
    });
    // React has not rendered busy yet between these events. The action gate must
    // stop a second selection and the power action synchronously.
    act(() => {
        nodeButton("美国 02").click();
        otherNode.click();
        power.click();
    });
    expect(calls("select_and_connect")).toHaveLength(1);
    expect(calls("connect")).toHaveLength(0);
    expect(calls("disconnect")).toHaveLength(0);
    expect(otherNode.disabled).toBe(true);
    expect(power.disabled).toBe(true);
    expect(mode.disabled).toBe(true);
    expect(refresh.disabled).toBe(true);
    fireEvent.click(mode);
    fireEvent.click(refresh);
    expect(calls("save_routing")).toHaveLength(0);
    expect(calls("refresh_subscription")).toHaveLength(0);
    await act(async () => pending.resolve(connectedResult("美国 02")));
    expect(powerButton().getAttribute("aria-label")).toBe("断开连接");
    expect(powerButton().disabled).toBe(false);
    expect(nodeButton("日本 01").disabled).toBe(false);
});

it("连接前已发出的旧状态响应不能覆盖新的已连接状态", async () => {
    vi.useFakeTimers();
    await mount();
    const old = structuredClone(backend);
    const pending = deferred<View>();
    snapshots.push(() => pending.promise);
    await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
    });
    expect(snapshots).toHaveLength(0);
    await act(async () => nodeButton("美国 02").click());
    expect(powerButton().getAttribute("aria-label")).toBe("断开连接");
    await act(async () => pending.resolve(old));
    expect(powerButton().getAttribute("aria-label")).toBe("断开连接");
    expect(
        screen.getByText("已连接", { selector: ".connection-state" }),
    ).toBeTruthy();
});

it("系统代理已开启但检测失败时显示连接待检查，仍提供断开按钮", async () => {
    select = async (args) => connectedResult(String(args.name), "出口检测超时");
    await mount();
    fireEvent.click(nodeButton("美国 02"));
    await waitFor(() =>
        expect(
            screen.getByText("连接待检查", { selector: ".connection-state" }),
        ).toBeTruthy(),
    );
    expect(powerButton().getAttribute("aria-label")).toBe("断开连接");
    expect(
        screen.getByRole<HTMLButtonElement>("button", { name: /^连接检测/ })
            .disabled,
    ).toBe(false);
    expect(nodeButton("美国 02").getAttribute("aria-pressed")).toBe("true");
});
