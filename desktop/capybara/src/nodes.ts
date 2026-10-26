import { useEffect, useRef, useState } from "react";
import { command, errorText } from "./bridge";

export type NodeView = {
    revision: number;
    routes: { group: string; selected: string; choices: string[] }[];
    loading: boolean;
    error: string | null;
    testing: boolean;
    delays: Record<string, { status: string; ms: number | null }>;
};
export const emptyNodes: NodeView = {
    revision: 0,
    routes: [],
    loading: false,
    error: null,
    testing: false,
    delays: {},
};
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
    const selecting = useRef(false),
        testing = useRef(false),
        alive = useRef(true);
    const merge = (next: NodeView) => {
        if (alive.current) setView((old) => latestNodes(old, next));
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
        };
    }, []);
    const select = async (group: string, name: string) => {
        if (selecting.current) return;
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
        if (testing.current || view.testing) return;
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
    return { view, pending, error, select, test };
}
