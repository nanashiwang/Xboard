import { describe, it, expect } from "vitest";
import {
    emptyView,
    quotaPercent,
    statusMessage,
    syncNeedsAttention,
    type Subscription,
    type View,
} from "../src/model";
const s: Subscription = {
    status: "active",
    plan_name: "测试",
    expires_at: null,
    traffic: {
        total_bytes: 100,
        used_bytes: 50,
        remaining_bytes: 50,
        reset_at: null,
    },
    registered_device_count: 1,
    registered_device_limit: 3,
};
const v: View = { ...emptyView, logged_in: true, subscription: s };
describe("套餐提示优先级", () => {
    it("无需刷新配置也能展示耗尽原因", () => {
        expect(
            statusMessage({
                ...v,
                connection: "connected",
                subscription: { ...s, status: "traffic_exhausted" },
            }).title,
        ).toBe("本期流量已用完");
    });
    it.each(["no_plan", "expired", "traffic_exhausted"] as const)(
        "家宽连接独立于普通套餐 %s",
        (status) => {
            const active: View = {
                ...v,
                proxy_id: 1,
                proxy_address: "216.36.108.173",
                connection: "connected",
                subscription: { ...s, status },
            };
            expect(statusMessage(active).title).toBe("家宽代理已连接");
            expect(
                statusMessage({ ...active, connection_error: "出口检测超时" })
                    .text,
            ).toBe("出口检测超时");
        },
    );
    it("离线时不把缓存流量当成当前可用资格", () => {
        expect(statusMessage({ ...v, sync_error: "offline" }).title).toBe(
            "暂时无法同步账号",
        );
    });
    it("短暂网络失败继续显示最近一次状态，超过宽限再提示", () => {
        const synced = Math.floor(Date.now() / 1000);
        const failed: View = {
            ...v,
            synced_at: synced,
            sync_error: "超时",
            sync_error_code: "NETWORK_TIMEOUT",
        };
        expect(syncNeedsAttention(failed, synced * 1000 + 89_999)).toBe(false);
        expect(syncNeedsAttention(failed, synced * 1000 + 90_000)).toBe(true);
        expect(syncNeedsAttention(failed, synced * 1000 - 1)).toBe(true);
        expect(statusMessage(failed).title).toBe("准备好了，随时出发");
        expect(
            statusMessage({ ...failed, connection_error: "线路异常" }).text,
        ).toBe("线路异常");
        expect(
            syncNeedsAttention(
                { ...failed, sync_error: null },
                synced * 1000 + 91_000,
            ),
        ).toBe(false);
    });
    it("无近期快照、已过有效期或明确服务错误立即提示", () => {
        const failure: View = {
            ...v,
            synced_at: Math.floor(Date.now() / 1000),
            sync_error: "失败",
            sync_error_code: "NETWORK_UNAVAILABLE",
        };
        for (const change of [
            { subscription: null },
            { synced_at: null },
            {
                subscription: {
                    ...s,
                    expires_at: new Date(Date.now() - 1000).toISOString(),
                },
            },
            { sync_error_code: "AUTH_REQUIRED" },
            { sync_error_code: "SUBSCRIPTION_UNAVAILABLE" },
            { sync_error_code: "NETWORK_DENIED" },
        ])
            expect(syncNeedsAttention({ ...failure, ...change })).toBe(true);
        expect(
            statusMessage({
                ...failure,
                subscription: { ...s, status: "expired" },
            }).title,
        ).toBe("套餐已到期");
    });
    it("区分套餐到期与线路错误", () => {
        expect(
            statusMessage({
                ...v,
                connection_error: "timeout",
                subscription: { ...s, status: "expired" },
            }).title,
        ).toBe("套餐已到期");
        expect(statusMessage({ ...v, connection_error: "timeout" }).text).toBe(
            "timeout",
        );
    });
    it("无状态时等待同步，不显示正常", () => {
        expect(statusMessage({ ...v, subscription: null }).title).toBe(
            "正在同步账号",
        );
    });
    it("提前提醒流量不足并限制进度在有效范围", () => {
        expect(
            statusMessage({
                ...v,
                subscription: {
                    ...s,
                    traffic: { ...s.traffic, used_bytes: 91 },
                },
            }).title,
        ).toBe("本期流量快用完了");
        expect(
            quotaPercent({ ...s, traffic: { ...s.traffic, used_bytes: 150 } }),
        ).toBe(100);
        expect(
            quotaPercent({ ...s, traffic: { ...s.traffic, total_bytes: 0 } }),
        ).toBe(0);
    });
    it("未登录不展示虚构套餐", () => {
        expect(emptyView.subscription).toBeNull();
        expect(emptyView.synced_at).toBeNull();
    });
});
