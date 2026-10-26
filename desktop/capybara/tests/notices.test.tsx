import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import Notifications from "../src/Notifications";
import { command } from "../src/bridge";
import {
    noticeHtml,
    noticeLink,
    loadReadMarks,
    readKey,
    type NoticePage,
    type SystemNotice,
} from "../src/notice-model";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    native: true,
    preview: null,
    errorText: (e: Error) => e.message,
}));
const notice = (id = 1): SystemNotice => ({
    id,
    title: `公告 ${id}`,
    content: "**消息正文** [官网](https://taige.us/)",
    published_at: "2026-10-26T00:00:00Z",
    image_url: null,
    level: "info",
    fingerprint: String(id).repeat(64),
});
const page = (
    items = [notice()],
    current = 1,
    total = items.length,
): NoticePage => ({ items, page: current, page_size: 20, total });
beforeEach(() => {
    const saved = new Map<string, string>();
    vi.stubGlobal("localStorage", {
        getItem: (key: string) => saved.get(key) ?? null,
        setItem: (key: string, value: string) => saved.set(key, value),
        clear: () => saved.clear(),
    });
    vi.mocked(command)
        .mockReset()
        .mockResolvedValue(page() as never);
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
});
afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});
const open = () =>
    fireEvent.click(
        screen.getByRole("button", { name: "系统通知", exact: true }),
    );
it("syncs the official feed; opening the bell does not mark notices read, details do and persist", async () => {
    const view = render(<Notifications />);
    await waitFor(() =>
        expect(screen.getByLabelText("有未读通知")).toBeTruthy(),
    );
    open();
    expect(screen.getByText("未读")).toBeTruthy();
    fireEvent.click(screen.getByText("公告 1"));
    expect(screen.queryByText("未读")).toBeNull();
    expect(screen.getByText("消息正文").tagName).toBe("STRONG");
    expect(loadReadMarks()["1"]).toBe(notice().fingerprint);
    fireEvent.click(screen.getByRole("link", { name: "官网" }));
    await waitFor(() =>
        expect(command).toHaveBeenCalledWith("open_notice_link", {
            url: "https://taige.us/",
        }),
    );
    view.unmount();
    render(<Notifications />);
    await waitFor(() =>
        expect(command).toHaveBeenCalledWith("fetch_notices", { page: 1 }),
    );
    expect(screen.queryByLabelText("有未读通知")).toBeNull();
});
it("an edited notice becomes unread again and failed refresh retains known content", async () => {
    localStorage.setItem(readKey, JSON.stringify({ 1: notice().fingerprint }));
    render(<Notifications />);
    open();
    await screen.findByText("公告 1");
    vi.mocked(command).mockResolvedValue(
        page([{ ...notice(), fingerprint: "f".repeat(64) }]) as never,
    );
    fireEvent.click(screen.getByRole("button", { name: "刷新系统通知" }));
    await screen.findByText("未读");
    vi.mocked(command).mockRejectedValue(new Error("连接超时"));
    fireEvent.click(screen.getByRole("button", { name: "刷新系统通知" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText("公告 1")).toBeTruthy();
    expect(screen.queryByText("暂时没有系统通知")).toBeNull();
});
it("page navigation and page-only read do not mark unseen notices", async () => {
    vi.mocked(command).mockImplementation(
        async (_, args) =>
            page(
                [notice(Number(args?.page || 1))],
                Number(args?.page || 1),
                21,
            ) as never,
    );
    render(<Notifications />);
    open();
    await screen.findByText("公告 1");
    fireEvent.click(screen.getByText("本页已读"));
    fireEvent.click(screen.getByRole("button", { name: "下一页通知" }));
    await screen.findByText("公告 2");
    expect(screen.getByText("未读")).toBeTruthy();
    expect(loadReadMarks()["2"]).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "关闭系统通知" }));
    expect(document.querySelector<HTMLDialogElement>("dialog")?.open).toBe(
        false,
    );
});
it("an old response cannot overwrite the first page after closing the dialog", async () => {
    let finish: (value: NoticePage) => void = () => {};
    vi.mocked(command).mockImplementation(async (_, args) =>
        args?.page === 2
            ? new Promise((resolve) => {
                  finish = resolve as typeof finish;
              })
            : (page([notice()], 1, 21) as never),
    );
    render(<Notifications />);
    open();
    await screen.findByText("公告 1");
    fireEvent.click(screen.getByRole("button", { name: "下一页通知" }));
    fireEvent.click(screen.getByRole("button", { name: "关闭系统通知" }));
    await act(async () => {
        finish(page([notice(2)], 2, 21));
    });
    open();
    await screen.findByText("公告 1");
    expect(screen.queryByText("公告 2")).toBeNull();
});
it("empty feed and initial failure are distinct; polling runs every five minutes", async () => {
    vi.useFakeTimers();
    vi.mocked(command).mockResolvedValue(page([]) as never);
    render(<Notifications />);
    await act(async () => {});
    open();
    await act(async () => {});
    expect(screen.getByText("暂时没有系统通知")).toBeTruthy();
    vi.mocked(command).mockClear();
    await act(async () => {
        await vi.advanceTimersByTimeAsync(300_000);
    });
    expect(command).toHaveBeenCalledTimes(1);
});
it("storage errors are explicit and malicious content cannot add executable markup or local links", async () => {
    const html = noticeHtml(
        '<script>alert(1)</script><img src="https://tracker.invalid/pixel" onerror="alert(1)"><iframe src="https://evil.invalid"></iframe><p style="color:red" onclick="alert(1)">正文</p><a href="javascript:alert(1)">坏链接</a><a href="https://taige.us/">官网</a><svg onload="alert(1)"></svg>',
    );
    expect(html).toContain("正文");
    expect(html).not.toMatch(
        /<script|<img|<iframe|onclick|onerror|style=|javascript:|<svg/,
    );
    for (const url of [
        "javascript:alert(1)",
        "file:///tmp/test",
        "data:text/html,x",
        "https://u:p@evil.invalid",
        "https://evil.invalid/\n",
    ])
        expect(noticeLink(url)).toBeNull();
    expect(noticeLink("/#/plan")).toBe("https://taige.us/#/plan");
    localStorage.setItem(readKey, "malformed");
    expect(loadReadMarks()).toEqual({});
    render(<Notifications />);
    open();
    await screen.findByText("公告 1");
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
        throw new Error("full");
    });
    fireEvent.click(screen.getByText("公告 1"));
    expect(screen.getByText(/已读状态暂时无法保存/)).toBeTruthy();
});
