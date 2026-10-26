import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
    act,
    cleanup,
    fireEvent,
    render,
    screen,
    waitFor,
} from "@testing-library/react";
import Invites from "../src/Invites";
import { command } from "../src/bridge";
import { emptyView } from "../src/model";
import {
    invitationLink,
    type Invitation,
    type InviteHistory,
} from "../src/invite-model";
import QRCode from "qrcode";
vi.mock("../src/bridge", () => ({
    command: vi.fn(),
    errorText: (e: Error) => e.message,
}));
vi.mock("qrcode", () => ({
    default: { toDataURL: vi.fn(async () => "data:image/png;base64,preview") },
}));
const user = {
    ...emptyView,
    logged_in: true,
    profile: { name: "A", email: "a@example.invalid" },
};
const login = vi.fn(),
    clipboard = vi.fn();
let data: Invitation, details: InviteHistory;
beforeEach(() => {
    data = {
        codes: [{ code: "OWN12345", created_at: 1792886400, visits: 4 }],
        stats: {
            registered: 3,
            total_commission: 1234,
            pending_commission: 234,
            available_commission: 1000,
        },
        rules: {
            generation_limit: 2,
            can_generate: true,
            registration_open: true,
            reusable: false,
            commission_rates: [7, 2, 1],
        },
    };
    details = {
        items: [
            {
                id: 1,
                order_amount: 10000,
                commission: 1000,
                created_at: 1792886400,
            },
        ],
        page: 1,
        page_size: 10,
        total: 11,
    };
    login.mockReset();
    clipboard.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: clipboard },
    });
    vi.mocked(QRCode.toDataURL).mockClear();
    vi.mocked(command)
        .mockReset()
        .mockImplementation(async (_name, args) => {
            if (args?.action === "details")
                return { ...details, page: args.page } as any;
            return structuredClone(data) as any;
        });
});
afterEach(cleanup);

it("未登录不读取邀请或自动生成，点击登录沿用账号登录", () => {
    render(<Invites view={emptyView} onLogin={login} />);
    expect(command).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "账号登录" }));
    expect(login).toHaveBeenCalledOnce();
});
it("本人分享链接与二维码一致，金额和分级比例来自接口，分页请求有界", async () => {
    render(<Invites view={user} onLogin={login} />);
    const input = await screen.findByRole("textbox", { name: "邀请链接" });
    expect((input as HTMLInputElement).value).toBe(
        "https://taige.us/#/register?code=OWN12345",
    );
    expect(screen.getByText("¥12.34")).toBeTruthy();
    expect(screen.getByText(/1级 7% · 2级 2% · 3级 1%/)).toBeTruthy();
    expect(screen.getByText(/仅可成功注册一次/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "复制邀请链接" }));
    await screen.findByText(/邀请链接已复制/);
    expect(clipboard).toHaveBeenCalledWith(invitationLink("OWN12345"));
    expect(QRCode.toDataURL).toHaveBeenCalledWith(
        invitationLink("OWN12345"),
        expect.anything(),
    );
    fireEvent.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("第 2 / 2 页");
    expect(command).toHaveBeenCalledWith("invite_request", {
        action: "details",
        page: 2,
    });
    expect(
        vi
            .mocked(command)
            .mock.calls.some(([, args]) => args?.action === "generate"),
    ).toBe(false);
});
it("双击只生成一次，超时后只回读并显示可能已创建的邀请码", async () => {
    let rejectWrite!: (e: Error) => void;
    vi.mocked(command).mockImplementation(async (_name, args) => {
        if (args?.action === "generate")
            return await new Promise((_, reject) => {
                rejectWrite = reject;
            });
        if (args?.action === "details") return details as any;
        return structuredClone(data) as any;
    });
    render(<Invites view={user} onLogin={login} />);
    const generate = await screen.findByRole("button", { name: "生成邀请码" });
    fireEvent.click(generate);
    fireEvent.click(generate);
    expect(
        vi
            .mocked(command)
            .mock.calls.filter(([, args]) => args?.action === "generate"),
    ).toHaveLength(1);
    data.codes.push({ code: "NEW12345", visits: 0, created_at: 1792886400 });
    data.rules.can_generate = false;
    await act(async () => rejectWrite(new Error("请求超时")));
    await screen.findByText(/请先查看已有邀请码/);
    expect(screen.getByRole("option", { name: "NEW12345" })).toBeTruthy();
    expect(
        (
            screen.getByRole("button", {
                name: "生成邀请码",
            }) as HTMLButtonElement
        ).disabled,
    ).toBe(true);
});
it("账号切换和注销丢弃旧请求，不泄露旧邀请码或二维码", async () => {
    let resolveOld!: (value: Invitation) => void;
    vi.mocked(command).mockImplementation(async (_name, args) =>
        args?.action === "index"
            ? await new Promise((resolve) => {
                  resolveOld = resolve;
              })
            : (details as any),
    );
    const page = render(<Invites view={user} onLogin={login} />);
    const old = resolveOld;
    vi.mocked(command).mockImplementation(async (_name, args) =>
        args?.action === "index"
            ? ({
                  ...data,
                  codes: [{ ...data.codes[0], code: "NEWUSER1" }],
              } as any)
            : (details as any),
    );
    page.rerender(
        <Invites
            view={{
                ...user,
                profile: { name: "B", email: "b@example.invalid" },
            }}
            onLogin={login}
        />,
    );
    await screen.findByRole("option", { name: "NEWUSER1" });
    await act(async () => old(data));
    expect(screen.queryByRole("option", { name: "OWN12345" })).toBeNull();
    page.rerender(<Invites view={emptyView} onLogin={login} />);
    expect(screen.queryByRole("textbox", { name: "邀请链接" })).toBeNull();
    expect(screen.queryByAltText("邀请注册链接二维码")).toBeNull();
});
it("空邀请码、注册关闭和失败状态不使用示例数据，复制失败不报成功", async () => {
    data.codes = [];
    data.rules.can_generate = false;
    data.rules.registration_open = false;
    const page = render(<Invites view={user} onLogin={login} />);
    await screen.findByText(/网站暂未开放注册/);
    expect(
        (
            screen.getByRole("button", {
                name: "生成邀请码",
            }) as HTMLButtonElement
        ).disabled,
    ).toBe(true);
    expect(screen.queryByRole("textbox", { name: "邀请链接" })).toBeNull();
    page.unmount();
    data.codes = [{ code: "OWN12345", visits: 0, created_at: 1792886400 }];
    data.rules.registration_open = true;
    clipboard.mockRejectedValue(new Error("denied"));
    render(<Invites view={user} onLogin={login} />);
    fireEvent.click(
        await screen.findByRole("button", { name: "复制邀请链接" }),
    );
    await screen.findByText(/复制失败/);
    expect(screen.queryByText(/邀请链接已复制/)).toBeNull();
});
it("读取失败可刷新恢复，明细失败不掩盖分享信息", async () => {
    vi.mocked(command).mockRejectedValue(new Error("暂时无法连接"));
    render(<Invites view={user} onLogin={login} />);
    await waitFor(() => expect(screen.getAllByRole("alert").length).toBe(2));
    expect(screen.queryByText("¥0.00")).toBeNull();
    vi.mocked(command).mockImplementation(async (_name, args) => {
        if (args?.action === "details") throw new Error("明细读取失败");
        return data as any;
    });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await screen.findByRole("textbox", { name: "邀请链接" });
    await screen.findByText("明细读取失败");
    expect(screen.getByRole("button", { name: "重试明细" })).toBeTruthy();
});
