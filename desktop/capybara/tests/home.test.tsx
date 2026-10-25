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

afterEach(cleanup);
function setup(overrides: Partial<View> = {}) {
    const view: View = {
        ...emptyView,
        logged_in: true,
        connection: "connected",
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
        ...overrides,
    };
    const onAction = vi.fn(async () => {}),
        onPrimary = vi.fn();
    const props = {
        view,
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
    const { onAction } = setup();
    const panel = within(screen.getByRole("region", { name: "首页节点列表" }));
    fireEvent.click(panel.getByRole("button", { name: "亚洲", exact: true }));
    expect(
        panel.queryByRole("button", { name: "选择节点 美国 03" }),
    ).toBeNull();
    fireEvent.change(panel.getByRole("textbox", { name: "搜索节点" }), {
        target: { value: "日本" },
    });
    fireEvent.click(panel.getByRole("button", { name: "选择节点 日本 02" }));
    expect(onAction).toHaveBeenLastCalledWith("select_route", {
        group: "默认连接",
        name: "日本 02",
    });
    fireEvent.change(panel.getByRole("combobox", { name: "选择分流组" }), {
        target: { value: "影音分流" },
    });
    expect(
        (panel.getByRole("textbox", { name: "搜索节点" }) as HTMLInputElement)
            .value,
    ).toBe("");
    fireEvent.click(panel.getByRole("button", { name: "选择节点 香港影音" }));
    expect(onAction).toHaveBeenLastCalledWith("select_route", {
        group: "影音分流",
        name: "香港影音",
    });
});
it("断开后不显示残留节点，重新连接会重置旧搜索", () => {
    const { props, rerender } = setup();
    fireEvent.change(screen.getByRole("textbox", { name: "搜索节点" }), {
        target: { value: "不会匹配" },
    });
    expect(screen.getByText("没有找到匹配节点")).toBeTruthy();
    rerender(
        <Home
            {...props}
            view={{ ...props.view, connection: "disconnected" }}
        />,
    );
    expect(
        screen.queryByRole("button", { name: "选择节点 新加坡 01" }),
    ).toBeNull();
    expect(screen.getByText("连接后，选择你的目的地")).toBeTruthy();
    rerender(<Home {...props} />);
    expect(
        screen.getByRole("button", { name: "选择节点 新加坡 01" }),
    ).toBeTruthy();
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
