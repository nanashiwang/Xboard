import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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

vi.mock("../src/Updates", () => ({ default: () => null }));
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    preview: null,
    errorText: () => "未获得钥匙串授权，可以重试或重新登录",
}));
let state: View;
beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: () => null, setItem: () => {} });
    for (const [name, open] of [
        ["showModal", true],
        ["close", false],
    ] as const)
        Object.defineProperty(HTMLDialogElement.prototype, name, {
            configurable: true,
            value() {
                this.open = open;
            },
        });
    state = { ...emptyView, platform: "macos", session_needs_unlock: true };
    vi.mocked(command)
        .mockReset()
        .mockImplementation(async () => structuredClone(state) as never);
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("钥匙串授权由用户发起", () => {
    it("启动和连续轮询只读状态，不自动请求恢复授权", async () => {
        vi.useFakeTimers();
        render(<App />);
        await act(async () => {
            await vi.advanceTimersByTimeAsync(60_000);
        });
        expect(screen.getByText("登录记录等待授权")).toBeTruthy();
        expect(vi.mocked(command).mock.calls.length).toBeGreaterThan(2);
        expect(
            vi
                .mocked(command)
                .mock.calls.every(([name]) => name === "snapshot"),
        ).toBe(true);
        expect(document.querySelector("dialog")?.open).toBe(false);
    });
    it("点击才恢复、等待时不可重复操作、拒绝后可重试且不会自动连接", async () => {
        let rejectRestore: (error: Error) => void = () => {};
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "restore_session")
                return new Promise((_, reject) => {
                    rejectRestore = reject;
                });
            return structuredClone(state) as never;
        });
        render(<App />);
        fireEvent.click(
            await screen.findByRole("button", {
                name: "恢复登录",
                exact: true,
            }),
        );
        const waiting = screen.getAllByRole("button", { name: "正在恢复登录" });
        expect(
            waiting.every((button) => (button as HTMLButtonElement).disabled),
        ).toBe(true);
        await act(async () => rejectRestore(new Error("denied")));
        expect(
            await screen.findByRole("button", {
                name: "恢复登录",
                exact: true,
            }),
        ).toBeTruthy();
        expect(
            vi
                .mocked(command)
                .mock.calls.filter(([name]) => name === "restore_session"),
        ).toHaveLength(1);
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "restore_session")
                state = { ...emptyView, logged_in: true };
            return structuredClone(state) as never;
        });
        fireEvent.click(
            screen.getByRole("button", { name: "恢复登录", exact: true }),
        );
        await waitFor(() =>
            expect(screen.queryByText("登录记录等待授权")).toBeNull(),
        );
        expect(
            vi.mocked(command).mock.calls.some(([name]) => name === "connect"),
        ).toBe(false);
    });
    it("授权受阻时仍可打开账号登录，并解释系统密码的用途", async () => {
        render(<App />);
        await screen.findByText("登录记录等待授权");
        fireEvent.click(screen.getByRole("button", { name: "登录你的账号" }));
        expect(document.querySelector("dialog")?.open).toBe(true);
        expect(screen.getByText(/系统密码只在 macOS 弹窗内输入/)).toBeTruthy();
        expect(
            vi
                .mocked(command)
                .mock.calls.some(([name]) => name === "restore_session"),
        ).toBe(false);
    });
});
