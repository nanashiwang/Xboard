export type Subscription = {
    status: "active" | "traffic_exhausted" | "expired" | "no_plan" | "banned";
    plan_name: string | null;
    expires_at: string | null;
    traffic: {
        total_bytes: number;
        used_bytes: number;
        remaining_bytes: number;
        reset_at: string | null;
    };
    registered_device_count: number;
    registered_device_limit: number | null;
};
export type View = {
    logged_in: boolean;
    session_needs_unlock: boolean;
    browser_login: {
        registration?: boolean;
        phase: "starting" | "waiting" | "error";
        expires_at: number | null;
        error: string | null;
    } | null;
    profile: { name: string; email: string } | null;
    subscription: Subscription | null;
    synced_at: number | null;
    sync_error: string | null;
    connection: "connected" | "disconnected";
    connection_error: string | null;
    routes: { group: string; selected: string; choices: string[] }[];
    version: string;
    platform: string;
};
export const emptyView: View = {
    logged_in: false,
    session_needs_unlock: false,
    browser_login: null,
    profile: null,
    subscription: null,
    synced_at: null,
    sync_error: null,
    connection: "disconnected",
    connection_error: null,
    routes: [],
    version: "0.1.0-alpha.9",
    platform: "",
};
export function quotaPercent(s: Subscription | null) {
    return s && s.traffic.total_bytes > 0
        ? Math.max(
              0,
              Math.min(
                  100,
                  (s.traffic.used_bytes / s.traffic.total_bytes) * 100,
              ),
          )
        : 0;
}
export function bytes(n: number | undefined) {
    if (n === undefined) return "—";
    return `${(Math.max(0, n) / 1073741824).toLocaleString("zh-CN", { maximumFractionDigits: 1 })} GB`;
}
export function date(value: string | null | undefined) {
    return value
        ? new Date(value).toLocaleDateString("zh-CN", {
              year: "numeric",
              month: "2-digit",
              day: "2-digit",
          })
        : "—";
}
export function statusMessage(view: View) {
    if (!view.logged_in && view.connection_error)
        return {
            tone: "warning",
            title: "系统代理需要恢复",
            text: view.connection_error,
        };
    if (!view.logged_in && view.session_needs_unlock)
        return {
            tone: "warning",
            title: "登录记录等待授权",
            text:
                view.platform === "macos"
                    ? "打开应用不会自动请求钥匙串密码。点击“恢复登录”后，macOS 可能请你授权读取已保存的登录记录；也可以通过浏览器重新登录。"
                    : "点击“恢复登录”允许访问系统凭据库，或通过浏览器重新登录。",
        };
    if (!view.logged_in && view.sync_error)
        return {
            tone: "warning",
            title: "无法恢复登录",
            text: view.sync_error,
        };
    if (!view.logged_in)
        return {
            tone: "neutral",
            title: "你好，欢迎来到卡皮巴拉",
            text: "登录账号，流量、套餐和连接状态都在这里。",
        };
    if (view.sync_error)
        return {
            tone: "warning",
            title: "暂时无法同步账号",
            text: "当前流量可能已过期，暂时无法确认套餐状态。网络恢复后会自动重试。",
        };
    if (!view.subscription)
        return {
            tone: "neutral",
            title: "正在同步账号",
            text: "请稍候，正在读取套餐与流量。",
        };
    switch (view.subscription?.status) {
        case "traffic_exhausted":
            return {
                tone: "danger",
                title: "本期流量已用完",
                text: "连接已暂停。可以前往账户中心续费，或等待下次流量重置。",
            };
        case "expired":
            return {
                tone: "danger",
                title: "套餐已到期",
                text: "连接已暂停。续费后会自动同步权益，再点击连接即可。",
            };
        case "no_plan":
            return {
                tone: "warning",
                title: "还没有可用套餐",
                text: "前往账户中心选择套餐，即可开始连接。",
            };
        case "banned":
            return {
                tone: "danger",
                title: "账号已停用",
                text: "请联系客服了解详情。",
            };
    }
    if (view.connection_error)
        return {
            tone: "warning",
            title: "连接需要检查",
            text: view.connection_error,
        };
    if (quotaPercent(view.subscription) >= 90)
        return {
            tone: "warning",
            title: "本期流量快用完了",
            text: "剩余不到 10%，可以提前安排续费。",
        };
    return {
        tone: "good",
        title:
            view.connection === "connected"
                ? "已经连接，放轻松一点"
                : "准备好了，随时出发",
        text:
            view.connection === "connected"
                ? "系统代理已开启，线路连通检测已通过。"
                : "点击连接，卡皮巴拉为你打理接下来的连接。",
    };
}
