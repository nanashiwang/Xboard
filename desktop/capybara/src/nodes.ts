import { useEffect, useRef, useState } from "react";
import { command, errorText } from "./bridge";

export type NodeView = {
    revision: number;
    routes: { group: string; selected: string; choices: string[] }[];
    loading: boolean;
    error: string | null;
    testing: boolean;
    delays: Record<string, { status: string; ms: number | null }>;
    subscription_synced_at: number | null;
    subscription_interval_seconds: number;
};
export const emptyNodes: NodeView = {
    revision: 0,
    routes: [],
    loading: false,
    error: null,
    testing: false,
    delays: {},
    subscription_synced_at: null,
    subscription_interval_seconds: 3600,
};
export const subscriptionIntervals = [1800, 3600, 10800, 21600, 43200, 86400];
export function subscriptionIntervalLabel(seconds: number) {
    return seconds === 1800 ? "30 分钟" : `${seconds / 3600} 小时`;
}
export function subscriptionTime(value: number | null) {
    return value
        ? new Date(value * 1000).toLocaleString("zh-CN", {
              month: "2-digit",
              day: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
          })
        : "尚未更新";
}
export function latestNodes(current: NodeView, next: NodeView) {
    return next.revision >= current.revision ? next : current;
}
export function delayLabel(delay?: NodeView["delays"][string]) {
    if (!delay) return "未测速";
    if (delay.status === "pending") return "测速中";
    return delay.status === "ok" && delay.ms !== null
        ? `${delay.ms} ms`
        : delay.status;
}
export function useNodes() {
    const [view, setView] = useState(emptyNodes);
    const [pending, setPending] = useState<{
        group: string;
        name: string;
    } | null>(null);
    const [error, setError] = useState("");
    const [ready, setReady] = useState(false);
    const [subscriptionPending, setSubscriptionPending] = useState<
        "refresh" | "interval" | null
    >(null);
    const [subscriptionError, setSubscriptionError] = useState("");
    const [subscriptionMessage, setSubscriptionMessage] = useState("");
    const messageTimer = useRef<ReturnType<typeof setTimeout>>();
    const subscriptionMutation = useRef(false);
    const observed = useRef(emptyNodes);
    const failedSubscription = useRef<{
        kind: "refresh" | "interval";
        synced: number | null;
        interval: number;
    } | null>(null);
    const selecting = useRef(false),
        testing = useRef(false),
        alive = useRef(true);
    const merge = (next: NodeView) => {
        if (alive.current && typeof next.revision === "number") {
            if (next.revision < observed.current.revision) return;
            const previous = observed.current;
            observed.current = next;
            setView(next);
            setReady(true);
            if (
                previous.subscription_synced_at !== null &&
                next.subscription_synced_at === null
            ) {
                setSubscriptionMessage("");
                clearTimeout(messageTimer.current);
            }
            const failed = failedSubscription.current;
            if (
                failed &&
                ((failed.kind === "refresh" &&
                    ((next.error === null &&
                        next.subscription_synced_at !== null &&
                        next.subscription_synced_at > (failed.synced ?? 0)) ||
                        (previous.subscription_synced_at !== null &&
                            next.subscription_synced_at === null))) ||
                    (failed.kind === "interval" &&
                        next.subscription_interval_seconds !== failed.interval))
            ) {
                failedSubscription.current = null;
                setSubscriptionError("");
            }
        }
    };
    useEffect(() => {
        alive.current = true;
        let timer: ReturnType<typeof setTimeout>;
        let cancelled = false;
        const poll = async () => {
            let testing = false;
            try {
                const next = await command<NodeView>("nodes_snapshot");
                if (!cancelled) merge(next);
                testing = next.testing;
            } catch (e) {
                if (alive.current) setError(errorText(e));
            }
            if (!cancelled) timer = setTimeout(poll, testing ? 300 : 1000);
        };
        void poll();
        return () => {
            cancelled = true;
            alive.current = false;
            clearTimeout(timer);
            clearTimeout(messageTimer.current);
        };
    }, []);
    const select = async (group: string, name: string) => {
        if (selecting.current || subscriptionMutation.current || view.loading)
            return;
        selecting.current = true;
        setPending({ group, name });
        setError("");
        try {
            merge(await command<NodeView>("select_route", { group, name }));
        } catch (e) {
            if (alive.current) setError(errorText(e));
        } finally {
            selecting.current = false;
            if (alive.current) setPending(null);
        }
    };
    const test = async () => {
        if (
            testing.current ||
            view.testing ||
            view.loading ||
            subscriptionMutation.current
        )
            return;
        testing.current = true;
        setError("");
        try {
            merge(await command<NodeView>("test_nodes"));
        } catch (e) {
            if (alive.current) setError(errorText(e));
        } finally {
            testing.current = false;
        }
    };
    const refresh = async () => {
        try {
            merge(await command<NodeView>("nodes_snapshot"));
        } catch (e) {
            if (alive.current) setError(errorText(e));
        }
    };
    const updateSubscription = async (seconds?: number) => {
        if (
            subscriptionMutation.current ||
            selecting.current ||
            testing.current ||
            view.testing ||
            view.loading
        )
            return;
        subscriptionMutation.current = true;
        const previous = observed.current;
        failedSubscription.current = null;
        setSubscriptionPending(seconds === undefined ? "refresh" : "interval");
        setSubscriptionError("");
        setSubscriptionMessage("");
        clearTimeout(messageTimer.current);
        try {
            const next =
                seconds === undefined
                    ? await command<NodeView>("refresh_subscription")
                    : await command<NodeView>("set_subscription_interval", {
                          seconds,
                      });
            merge(next);
            if (
                alive.current &&
                seconds === undefined &&
                next.revision === observed.current.revision &&
                next.subscription_synced_at !== null
            ) {
                setSubscriptionMessage("订阅已更新");
                messageTimer.current = setTimeout(() => {
                    if (alive.current) setSubscriptionMessage("");
                }, 5000);
            }
        } catch (e) {
            if (alive.current) {
                failedSubscription.current = {
                    kind: seconds === undefined ? "refresh" : "interval",
                    synced: previous.subscription_synced_at,
                    interval: previous.subscription_interval_seconds,
                };
                setSubscriptionError(errorText(e));
            }
        } finally {
            subscriptionMutation.current = false;
            if (alive.current) setSubscriptionPending(null);
        }
    };
    return {
        view,
        pending,
        error,
        ready,
        select,
        test,
        refresh,
        subscriptionPending,
        subscriptionError,
        subscriptionMessage,
        refreshSubscription: () => updateSubscription(),
        setSubscriptionInterval: (seconds: number) =>
            updateSubscription(seconds),
    };
}
