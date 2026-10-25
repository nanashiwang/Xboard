import { invoke, isTauri } from "@tauri-apps/api/core";
import type { UpdateView } from "./Updates";
import { emptyView, type View } from "./model";
export const native = isTauri();
export const preview =
    import.meta.env.DEV && !native
        ? new URLSearchParams(location.search).get("preview")
        : null;
let demo: View = {
    ...emptyView,
    logged_in: true,
    profile: { name: "卡皮巴拉", email: "preview@example.invalid" },
    subscription: {
        status: "active",
        plan_name: "标准套餐",
        expires_at: "2026-11-23T00:00:00Z",
        traffic: {
            total_bytes: 200 * 1073741824,
            used_bytes: 36.8 * 1073741824,
            remaining_bytes: 163.2 * 1073741824,
            reset_at: "2026-11-01T00:00:00Z",
        },
        registered_device_count: 1,
        registered_device_limit: 3,
    },
    synced_at: Math.floor(Date.now() / 1000),
    platform: "macos",
    routes: [],
};
if (preview === "exhausted")
    demo = {
        ...demo,
        subscription: {
            ...demo.subscription!,
            status: "traffic_exhausted",
            traffic: {
                ...demo.subscription!.traffic,
                used_bytes: 200 * 1073741824,
                remaining_bytes: 0,
            },
        },
    };
if (preview === "offline") demo = { ...demo, sync_error: "账号服务连接失败" };
if (preview === "keychain")
    demo = { ...emptyView, platform: "macos", session_needs_unlock: true };
if (preview === "store-guest") demo = { ...emptyView, platform: "macos" };
let demoUpdate: UpdateView = {
    phase:
        preview === "update" || preview === "update-deb"
            ? "available"
            : "current",
    last_checked: Math.floor(Date.now() / 1000),
    release:
        preview === "update" || preview === "update-deb"
            ? {
                  version: "0.1.1",
                  notes: "优化连接体验。\n修复已知问题，提升稳定性。",
              }
            : null,
    prompt: preview === "update" || preview === "update-deb",
    downloaded: 0,
    total: null,
    error: null,
    manual_install: preview === "update-deb",
};
export async function command<T = View>(
    name: string,
    args?: Record<string, unknown>,
): Promise<T> {
    if (native) return invoke<T>(name, args);
    if (preview) {
        if (name === "store_request") {
            const { storePreview } = await import("./store-preview");
            return (await storePreview(
                preview,
                String(args?.action),
                args?.payload as Record<string, unknown>,
            )) as T;
        }
        if (
            [
                "update_snapshot",
                "check_updates",
                "dismiss_update",
                "show_update",
                "install_update",
            ].includes(name)
        ) {
            if (name === "dismiss_update") demoUpdate.prompt = false;
            if (name === "check_updates" || name === "show_update")
                demoUpdate.prompt = !!demoUpdate.release;
            if (name === "install_update")
                demoUpdate = {
                    ...demoUpdate,
                    phase: "error",
                    error: "这是模拟预览，不会下载或安装更新。",
                };
            return structuredClone(demoUpdate) as T;
        }
        if (name === "connect")
            demo = {
                ...demo,
                connection: "connected",
                routes: [
                    {
                        group: "卡皮巴拉",
                        selected: "自动选择",
                        choices: [
                            "自动选择",
                            "美国01｜2×｜家宽",
                            "日本01｜1×",
                            "香港01｜1×",
                        ],
                    },
                ],
            };
        if (name === "disconnect")
            demo = { ...demo, connection: "disconnected", routes: [] };
        if (name === "select_route")
            demo = {
                ...demo,
                routes: demo.routes.map((r) =>
                    r.group === args?.group
                        ? { ...r, selected: String(args?.name) }
                        : r,
                ),
            };
        if (name === "begin_browser_login")
            demo = {
                ...demo,
                browser_login: {
                    registration: args?.registration === true,
                    phase: "waiting",
                    expires_at: Math.floor(Date.now() / 1000) + 300,
                    error: null,
                },
            };
        if (name === "cancel_browser_login")
            demo = { ...demo, browser_login: null };
        if (name === "logout") demo = { ...emptyView };
        if (name === "restore_session")
            throw { message: "这是模拟预览，不会访问系统钥匙串。" };
        if (name === "open_link") return undefined as T;
        return structuredClone(demo) as T;
    }
    if (name === "snapshot") return { ...emptyView } as T;
    if (name === "open_link") {
        const urls: Record<string, string> = {
            account: "https://taige.us/#/dashboard",
            plans: "https://taige.us/#/plan",
            support: "https://taige.us/#/ticket",
            register: "https://taige.us/#/register",
            releases:
                "https://github.com/nanashiwang/Xboard/releases?q=capybara",
        };
        const url = urls[String(args?.target)];
        if (url) window.open(url, "_blank", "noopener,noreferrer");
        return undefined as T;
    }
    throw { message: "这是界面预览，请在卡皮巴拉桌面应用内登录和连接。" };
}
export function errorText(error: unknown) {
    return typeof error === "object" && error && "message" in error
        ? String(error.message)
        : "操作没有完成，请稍后重试";
}
