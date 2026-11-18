import { createRoot } from "react-dom/client";
import Proxies, { type ProxyRequest } from "./Proxies";
const login = () => location.assign("/#/login?redirect=/proxies");
function token(): string {
    try {
        const v = JSON.parse(
            localStorage.getItem("VUE_NAIVE_ACCESS_TOKEN") || "null",
        );
        return v &&
            (!v.expire || v.expire > Date.now()) &&
            typeof v.value === "string"
            ? v.value
            : "";
    } catch {
        return "";
    }
}
async function api(path: string, payload?: Record<string, unknown>) {
    const auth = token();
    if (!auth) {
        login();
        throw new Error("请先登录");
    }
    const response = await fetch("/api/v1/user/" + path, {
        method: payload ? "POST" : "GET",
        headers: {
            Authorization: auth,
            "Content-Type": "application/json",
            Accept: "application/json",
        },
        body: payload ? JSON.stringify(payload) : undefined,
        cache: "no-store",
        redirect: "error",
    });
    const body = await response.json();
    if (!response.ok || body.status === "fail") {
        if (
            response.status === 401 ||
            (response.status === 403 && body.message === "未登录或登陆已过期")
        )
            login();
        throw new Error(body.message || "请求未完成，请重试");
    }
    return body;
}
const request: ProxyRequest = async <T,>(
    action: string,
    payload: Record<string, unknown> = {},
) => {
    if (action === "index") return (await api("proxies")).data as T;
    if (action === "detail")
        return (await api("proxies/detail?id=" + Number(payload.id))).data as T;
    if (action === "save" || action === "update")
        return (await api("proxies/" + action, payload)).data as T;
    if (action === "order")
        return (
            await api(
                "order/detail?trade_no=" +
                    encodeURIComponent(String(payload.trade_no)),
            )
        ).data as T;
    if (action === "store")
        return { methods: (await api("order/getPaymentMethod")).data } as T;
    if (action === "cancel")
        return (await api("order/cancel", payload)).data as T;
    if (action === "checkout") {
        const result = await api("order/checkout", payload);
        return {
            kind:
                result.type === -1
                    ? "submitted"
                    : result.type === 0
                      ? "qr"
                      : "url",
            data: result.data,
        } as T;
    }
    throw new Error("不支持的操作");
};
createRoot(document.getElementById("proxy-root")!).render(
    <Proxies request={request} loggedIn={!!token()} onLogin={login} />,
);
