import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
    within,
} from "@testing-library/react";
import Routing, { useRouting, type RoutingState } from "../src/Routing";
import Home from "../src/Home";
import {
    emptyRouting,
    type RoutingSettings,
    type RoutingView,
} from "../src/routing-model";
import { emptyView } from "../src/model";
import { emptyNodes } from "../src/nodes";
import { command } from "../src/bridge";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (error: { message: string }) => error.message,
}));
const invoke = vi.mocked(command);
let backend: RoutingView;
let saved = vi.fn();
beforeEach(() => {
    vi.clearAllMocks();
    backend = structuredClone(emptyRouting);
    backend.ready = true;
    backend.targets = ["卡皮巴拉", "日本 01", "美国 02"];
    saved = vi.fn();
    invoke.mockImplementation(async (name, args) => {
        if (name === "save_routing")
            backend.settings = structuredClone(
                args?.settings as RoutingSettings,
            );
        return structuredClone(backend) as never;
    });
    HTMLDialogElement.prototype.showModal = function () {
        this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close = function () {
        this.removeAttribute("open");
    };
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
});
function Harness() {
    return <Routing routing={useRouting(saved)} />;
}
async function setup() {
    render(<Harness />);
    await waitFor(() =>
        expect(
            screen
                .getByRole("button", { name: "规则", exact: true })
                .getAttribute("aria-pressed"),
        ).toBe("true"),
    );
}
it("模式等待原生确认，失败保留旧模式，再次成功后刷新节点", async () => {
    await setup();
    let reject: (error: unknown) => void = () => {};
    invoke.mockImplementationOnce(
        () =>
            new Promise((_, no) => {
                reject = no;
            }),
    );
    fireEvent.click(screen.getByRole("button", { name: "全局", exact: true }));
    expect(
        screen
            .getByRole("button", { name: "规则", exact: true })
            .getAttribute("aria-pressed"),
    ).toBe("true");
    expect(
        screen
            .getByRole("button", { name: "直连", exact: true })
            .hasAttribute("disabled"),
    ).toBe(true);
    await act(async () => reject({ message: "内核未确认修改" }));
    expect(screen.getByRole("alert").textContent).toContain("内核未确认修改");
    expect(saved).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "全局", exact: true }));
    await waitFor(() =>
        expect(
            screen
                .getByRole("button", { name: "全局", exact: true })
                .getAttribute("aria-pressed"),
        ).toBe("true"),
    );
    expect(saved).toHaveBeenCalledTimes(1);
    expect(invoke).toHaveBeenLastCalledWith("save_routing", {
        settings: { mode: "global", rules: [], global_target: null },
    });
});
it("规则可以新增、编辑、排序、删除，保存时保留全局节点", async () => {
    backend.settings.global_target = "日本 01";
    backend.settings.rules = [
        { kind: "DOMAIN", value: "old.example.com", target: "DIRECT" },
        { kind: "DOMAIN-SUFFIX", value: "keep.example.com", target: "REJECT" },
    ];
    await setup();
    fireEvent.click(screen.getByRole("button", { name: /管理规则/ }));
    const dialog = within(
        screen.getByRole("dialog", { name: "自定义分流规则" }),
    );
    fireEvent.change(dialog.getByRole("textbox", { name: "规则 1 匹配内容" }), {
        target: { value: " new.example.com " },
    });
    fireEvent.change(
        dialog.getByRole("combobox", { name: "规则 1 处理方式" }),
        { target: { value: "日本 01" } },
    );
    fireEvent.click(dialog.getByRole("button", { name: "下移规则 1" }));
    fireEvent.click(dialog.getByRole("button", { name: "删除规则 1" }));
    fireEvent.click(dialog.getByRole("button", { name: "添加规则" }));
    fireEvent.change(
        dialog.getByRole("combobox", { name: "规则 2 匹配类型" }),
        { target: { value: "IP-CIDR6" } },
    );
    fireEvent.change(dialog.getByRole("textbox", { name: "规则 2 匹配内容" }), {
        target: { value: "2001:db8::/32" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "保存规则" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(backend.settings).toEqual({
        mode: "rule",
        global_target: "日本 01",
        rules: [
            { kind: "DOMAIN", value: "new.example.com", target: "日本 01" },
            { kind: "IP-CIDR6", value: "2001:db8::/32", target: "DIRECT" },
        ],
    });
    expect(screen.getByRole("status").textContent).toContain("已保存并应用");
});
it("无节点时仍可保存本机直连规则，无效输入和原生错误保留草稿", async () => {
    backend.ready = false;
    backend.targets = [];
    await setup();
    fireEvent.click(screen.getByRole("button", { name: /管理规则/ }));
    fireEvent.click(screen.getByRole("button", { name: "添加规则" }));
    fireEvent.click(screen.getByRole("button", { name: "保存规则" }));
    expect(screen.getByRole("alert").textContent).toContain(
        "请填写第 1 条规则",
    );
    expect(invoke).not.toHaveBeenCalledWith("save_routing", expect.anything());
    const target = screen.getByRole("combobox", { name: "规则 1 处理方式" });
    expect(
        within(target)
            .getAllByRole("option")
            .map((option) => option.textContent),
    ).toEqual(["直连", "拦截"]);
    fireEvent.change(screen.getByRole("textbox", { name: "规则 1 匹配内容" }), {
        target: { value: "example.com" },
    });
    invoke.mockRejectedValueOnce({ message: "应用数据保存失败" });
    fireEvent.click(screen.getByRole("button", { name: "保存规则" }));
    await waitFor(() =>
        expect(screen.getByRole("alert").textContent).toContain(
            "应用数据保存失败",
        ),
    );
    expect(
        (
            screen.getByRole("textbox", {
                name: "规则 1 匹配内容",
            }) as HTMLInputElement
        ).value,
    ).toBe("example.com");
    fireEvent.click(screen.getByRole("button", { name: "保存规则" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("status").textContent).toContain(
        "准备节点时自动应用",
    );
});
it("取消规则修改不会保存，无法使用的旧目标仍可辨认与删除", async () => {
    backend.settings.rules = [
        { kind: "DOMAIN", value: "example.com", target: "已移除节点" },
    ];
    await setup();
    fireEvent.click(screen.getByRole("button", { name: /管理规则/ }));
    expect(
        screen.getByRole("option", { name: "已移除节点（暂不可用）" }),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "删除规则 1" }));
    fireEvent.click(screen.getByRole("button", { name: "取消", exact: true }));
    expect(invoke).not.toHaveBeenCalledWith("save_routing", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: /管理规则/ }));
    expect(
        screen.getByRole("textbox", { name: "规则 1 匹配内容" }),
    ).toBeTruthy();
});
it("较早的轮询结果不会覆盖刚保存的模式", async () => {
    vi.useFakeTimers();
    let resolveOld: (value: RoutingView) => void = () => {};
    render(<Harness />);
    await act(async () => {});
    const old = structuredClone(backend);
    invoke.mockImplementationOnce(
        () =>
            new Promise((resolve) => {
                resolveOld = resolve as typeof resolveOld;
            }),
    );
    await act(async () => {
        vi.advanceTimersByTime(2000);
    });
    await act(async () =>
        fireEvent.click(
            screen.getByRole("button", { name: "直连", exact: true }),
        ),
    );
    await act(async () => resolveOld(old));
    expect(
        screen
            .getByRole("button", { name: "直连", exact: true })
            .getAttribute("aria-pressed"),
    ).toBe("true");
});
it("首次读取失败时不允许用空设置覆盖已保存规则，重试成功后恢复", async () => {
    vi.useFakeTimers();
    invoke.mockRejectedValueOnce({ message: "设置暂时读取失败" });
    render(<Harness />);
    await act(async () => {});
    expect(screen.getByRole("alert").textContent).toContain("设置暂时读取失败");
    expect(
        screen
            .getByRole("button", { name: "全局", exact: true })
            .hasAttribute("disabled"),
    ).toBe(true);
    expect(
        screen
            .getByRole("button", { name: /管理规则/ })
            .hasAttribute("disabled"),
    ).toBe(true);
    await act(async () => {
        vi.advanceTimersByTime(2000);
    });
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
        screen
            .getByRole("button", { name: "全局", exact: true })
            .hasAttribute("disabled"),
    ).toBe(false);
});
it("首页全局模式只控制 GLOBAL，直连不展示旧节点", () => {
    const routing: RoutingState = {
        view: { ...backend, settings: { ...backend.settings, mode: "global" } },
        busy: false,
        loading: false,
        error: "",
        save: vi.fn(),
    };
    const nodes = {
        view: {
            ...emptyNodes,
            routes: [
                {
                    group: "普通分流",
                    selected: "美国 02",
                    choices: ["美国 02"],
                },
                { group: "GLOBAL", selected: "日本 01", choices: ["日本 01"] },
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
    const props = {
        routing,
        nodes,
        view: { ...emptyView, logged_in: true, connection: "connected" },
        busy: "",
        eligible: true,
        primaryText: "断开连接",
        onPrimary: vi.fn(),
        onAction: vi.fn(async () => {}),
        onPlans: vi.fn(),
        notice: null,
    };
    const { rerender } = render(<Home {...props} />);
    expect(
        screen.queryByRole("button", { name: "选择节点 美国 02" }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "选择节点 日本 01" }));
    expect(nodes.select).toHaveBeenCalledWith("GLOBAL", "日本 01");
    rerender(
        <Home
            {...props}
            routing={{
                ...routing,
                view: {
                    ...routing.view,
                    settings: { ...routing.view.settings, mode: "direct" },
                },
            }}
        />,
    );
    expect(
        screen.queryByRole("button", { name: "选择节点 日本 01" }),
    ).toBeNull();
    expect(screen.getByText("当前流量直接访问")).toBeTruthy();
    expect(
        screen
            .getByRole("button", { name: "一键测速" })
            .hasAttribute("disabled"),
    ).toBe(true);
});
