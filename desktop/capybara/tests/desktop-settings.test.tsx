import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import DesktopSettings, {
    type DesktopSettingsView,
} from "../src/DesktopSettings";
import { command } from "../src/bridge";

vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    native: true,
    preview: null,
    errorText: () => "系统未应用设置",
}));
let state: DesktopSettingsView;
beforeEach(() => {
    state = { autostart_enabled: false, background_available: true };
    vi.mocked(command)
        .mockReset()
        .mockImplementation(async (name, args) => {
            if (name === "set_autostart")
                state.autostart_enabled = args?.enabled === true;
            return { ...state } as never;
        });
});
afterEach(cleanup);

describe("启动设置以系统状态为准", () => {
    it("读取已注册状态，允许关闭且不会在打开设置时自动开启", async () => {
        state.autostart_enabled = true;
        render(<DesktopSettings />);
        await screen.findByText("已开启");
        expect(vi.mocked(command).mock.calls.map(([name]) => name)).toEqual([
            "desktop_settings",
        ]);
        fireEvent.click(screen.getByRole("switch", { name: "开机自启" }));
        await screen.findByText("已关闭");
        expect(command).toHaveBeenCalledWith("set_autostart", {
            enabled: false,
        });
    });

    it("保存期间禁止重复切换和焦点读取，不提前显示成功", async () => {
        let finish!: (value: DesktopSettingsView) => void;
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "set_autostart")
                return new Promise((resolve) => {
                    finish = resolve as typeof finish;
                });
            return { ...state } as never;
        });
        render(<DesktopSettings />);
        await screen.findByText("已关闭");
        const button = screen.getByRole("switch", { name: "开机自启" });
        fireEvent.click(button);
        fireEvent.click(button);
        fireEvent(window, new Event("focus"));
        expect((button as HTMLButtonElement).disabled).toBe(true);
        expect(button.getAttribute("aria-checked")).toBe("false");
        expect(vi.mocked(command).mock.calls.map(([name]) => name)).toEqual([
            "desktop_settings",
            "set_autostart",
        ]);
        await act(async () => finish({ ...state, autostart_enabled: true }));
        await screen.findByText("已开启");
    });

    it("写入后报告失败仍回读实际状态，并允许重新读取清除错误", async () => {
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "set_autostart") {
                state.autostart_enabled = true;
                throw new Error("readback failed");
            }
            return { ...state } as never;
        });
        render(<DesktopSettings />);
        await screen.findByText("已关闭");
        fireEvent.click(screen.getByRole("switch", { name: "开机自启" }));
        await screen.findByRole("alert");
        expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe(
            "true",
        );
        fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
        await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    });

    it("读取失败不当作关闭；重试后呈现托盘不可用的退出行为", async () => {
        vi.mocked(command).mockRejectedValueOnce(new Error("unavailable"));
        state.background_available = false;
        render(<DesktopSettings />);
        await screen.findByText("读取失败");
        expect((screen.getByRole("switch") as HTMLButtonElement).disabled).toBe(
            true,
        );
        fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
        await screen.findByText("已关闭");
        expect(
            screen.getByText("当前系统托盘不可用，关闭窗口会退出应用。"),
        ).toBeTruthy();
    });

    it("重新聚焦会回读用户在系统中修改的状态", async () => {
        render(<DesktopSettings />);
        await screen.findByText("已关闭");
        state.autostart_enabled = true;
        fireEvent(window, new Event("focus"));
        await screen.findByText("已开启");
        expect(
            vi
                .mocked(command)
                .mock.calls.every(([name]) => name === "desktop_settings"),
        ).toBe(true);
    });
});
