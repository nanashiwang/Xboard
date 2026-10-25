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
    it("点击账号登录会打开浏览器授权，不读取钥匙串或要求输入密码", async () => {
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "begin_browser_login")
                state = {
                    ...state,
                    browser_login: {
                        phase: "waiting",
                        expires_at: 2000000000,
                        error: null,
                    },
                };
            if (name === "cancel_browser_login")
                state = { ...state, browser_login: null };
            return structuredClone(state) as never;
        });
        render(<App />);
        await screen.findByText("登录记录等待授权");
        fireEvent.click(screen.getByRole("button", { name: "登录你的账号" }));
        await screen.findByText("在浏览器中完成登录");
        expect(document.querySelector("dialog")?.open).toBe(true);
        expect(document.querySelector('input[type="password"]')).toBeNull();
        expect(
            vi
                .mocked(command)
                .mock.calls.some(([name]) => name === "restore_session"),
        ).toBe(false);
        fireEvent.click(screen.getByRole("button", { name: "重新打开浏览器" }));
        await waitFor(() =>
            expect(
                vi
                    .mocked(command)
                    .mock.calls.some(
                        ([name]) => name === "reopen_browser_login",
                    ),
            ).toBe(true),
        );
        fireEvent.click(
            screen.getByRole("button", { name: "取消登录", exact: true }),
        );
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(false),
        );
    });
    it("授权失败可重新发起，成功后关闭等待页且不自动连接", async () => {
        state = {
            ...emptyView,
            browser_login: {
                phase: "error",
                expires_at: null,
                error: "连接超时",
            },
        };
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "begin_browser_login")
                state = { ...emptyView, logged_in: true };
            return structuredClone(state) as never;
        });
        render(<App />);
        await screen.findByText("连接超时");
        fireEvent.click(
            screen.getByRole("button", { name: "重新登录", exact: true }),
        );
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(false),
        );
        expect(
            vi.mocked(command).mock.calls.some(([name]) => name === "connect"),
        ).toBe(false);
    });
    it("未登录首页可发起注册，注册重试保留意图且成功后不自动连接", async () => {
        state = { ...emptyView };
        vi.mocked(command).mockImplementation(async (name, args) => {
            if (name === "begin_browser_login")
                state = {
                    ...state,
                    browser_login: {
                        phase: "error",
                        registration: args?.registration === true,
                        expires_at: null,
                        error: "网络暂时不可用",
                    },
                };
            return structuredClone(state) as never;
        });
        render(<App />);
        fireEvent.click(
            await screen.findByRole("button", {
                name: "注册账号",
                exact: true,
            }),
        );
        await screen.findByText("网络暂时不可用");
        expect(
            vi
                .mocked(command)
                .mock.calls.some(
                    ([name, args]) =>
                        name === "begin_browser_login" &&
                        args?.registration === true,
                ),
        ).toBe(true);
        expect(document.querySelector('input[type="password"]')).toBeNull();
        vi.mocked(command).mockImplementation(async (name) => {
            if (name === "begin_browser_login")
                state = { ...emptyView, logged_in: true };
            return structuredClone(state) as never;
        });
        fireEvent.click(
            screen.getByRole("button", { name: "继续注册", exact: true }),
        );
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(false),
        );
        expect(
            screen.queryByRole("button", { name: "注册账号", exact: true }),
        ).toBeNull();
        expect(
            vi.mocked(command).mock.calls.some(([name]) => name === "connect"),
        ).toBe(false);
    });
    it("登录等待页可切换为注册，并显示注册完成后的返回提示", async () => {
        state = {
            ...emptyView,
            browser_login: {
                phase: "waiting",
                expires_at: 2000000000,
                error: null,
            },
        };
        vi.mocked(command).mockImplementation(async (name, args) => {
            if (name === "begin_browser_login")
                state = {
                    ...state,
                    browser_login: {
                        phase: "waiting",
                        registration: args?.registration === true,
                        expires_at: 2000000000,
                        error: null,
                    },
                };
            return structuredClone(state) as never;
        });
        render(<App />);
        await screen.findByText("在浏览器中完成登录");
        const dialog = document.querySelector("dialog")!;
        fireEvent.click(
            Array.from(dialog.querySelectorAll("button")).find((button) =>
                button.textContent?.includes("注册账号"),
            )!,
        );
        await screen.findByText("在浏览器中注册账号");
        expect(
            screen.getByText("在官网完成注册后，确认授权即可回到客户端。"),
        ).toBeTruthy();
        expect(
            vi
                .mocked(command)
                .mock.calls.some(
                    ([name, args]) =>
                        name === "begin_browser_login" &&
                        args?.registration === true,
                ),
        ).toBe(true);
    });
});
