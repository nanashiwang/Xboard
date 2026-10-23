import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import {
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import Updates, { emptyUpdate, type UpdateView } from "../src/Updates";
import { command } from "../src/bridge";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    native: true,
    preview: null,
    errorText: () => "操作失败",
}));
let state: UpdateView;
beforeEach(() => {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
        configurable: true,
        value() {
            this.open = true;
        },
    });
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
        configurable: true,
        value() {
            this.open = false;
        },
    });
    state = {
        ...emptyUpdate,
        phase: "available",
        prompt: true,
        release: { version: "0.1.0-alpha.4", notes: "修复连接问题" },
    };
    vi.mocked(command)
        .mockReset()
        .mockImplementation(async (name) => {
            if (name === "dismiss_update") state = { ...state, prompt: false };
            if (name === "install_update")
                state = {
                    ...state,
                    phase: "error",
                    error: "签名校验失败，未安装更新",
                };
            return structuredClone(state) as never;
        });
});
afterEach(cleanup);
describe("更新需用户确认", () => {
    it("自动发现只展示提示；稍后不下载且关闭弹窗", async () => {
        render(
            <Updates
                version="0.1.0-alpha.3"
                settings={false}
                blocked={false}
            />,
        );
        await screen.findByText("修复连接问题");
        expect(document.querySelector("dialog")?.open).toBe(true);
        fireEvent.click(
            screen.getByRole("button", { name: "稍后", exact: true }),
        );
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(false),
        );
        expect(
            vi
                .mocked(command)
                .mock.calls.some(([name]) => name === "install_update"),
        ).toBe(false);
    });
    it("确认才调用安装；校验失败保留重试且不声称成功", async () => {
        render(
            <Updates version="0.1.0-alpha.3" settings={true} blocked={false} />,
        );
        await screen.findByText("修复连接问题");
        fireEvent.click(screen.getByRole("button", { name: "更新并重启" }));
        expect(await screen.findByRole("alert")).toHaveProperty(
            "textContent",
            "签名校验失败，未安装更新",
        );
        expect(screen.getByRole("button", { name: "重试更新" })).toBeTruthy();
        expect(
            vi
                .mocked(command)
                .mock.calls.filter(([name]) => name === "install_update"),
        ).toHaveLength(1);
    });
    it("不打断登录；登录结束后再提示", async () => {
        const { rerender } = render(
            <Updates version="0.1" settings={false} blocked />,
        );
        await screen.findByText("修复连接问题");
        expect(document.querySelector("dialog")?.open).toBe(false);
        rerender(<Updates version="0.1" settings={false} blocked={false} />);
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(true),
        );
    });
    it("手动检查显示已是最新版本，DEB 明确系统安装边界", async () => {
        state = { ...state, manual_install: true };
        render(<Updates version="0.1" settings blocked={false} />);
        await screen.findByRole("button", { name: "前往下载更新" });
        expect(screen.getByText(/通过系统安装器更新/)).toBeTruthy();
        fireEvent.click(
            screen.getByRole("button", { name: "稍后", exact: true }),
        );
        await waitFor(() =>
            expect(document.querySelector("dialog")?.open).toBe(false),
        );
        state = { ...emptyUpdate, phase: "current" };
        fireEvent.click(screen.getByRole("button", { name: "立即检查" }));
        await screen.findByText("已是最新版本");
        expect(document.querySelector("dialog")?.open).toBe(false);
    });
    it("下载安装期间不能 Escape 关闭或重复确认", async () => {
        state = { ...state, phase: "downloading", downloaded: 25, total: 100 };
        render(<Updates version="0.1" settings blocked={false} />);
        await screen.findByText(/25%/);
        const dialog = document.querySelector("dialog")!;
        const event = new Event("cancel", { cancelable: true });
        fireEvent(dialog, event);
        expect(event.defaultPrevented).toBe(true);
        expect(screen.queryByRole("button", { name: "更新并重启" })).toBeNull();
        expect(dialog.open).toBe(true);
        expect(
            vi
                .mocked(command)
                .mock.calls.some(([name]) => name === "dismiss_update"),
        ).toBe(false);
    });
});
