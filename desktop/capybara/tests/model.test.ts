import { describe, it, expect } from "vitest";
import {
    emptyView,
    quotaPercent,
    statusMessage,
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
    it("离线时不把缓存流量当成当前可用资格", () => {
        expect(statusMessage({ ...v, sync_error: "offline" }).title).toBe(
            "暂时无法同步账号",
        );
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
