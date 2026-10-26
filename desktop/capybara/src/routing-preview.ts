import type { NodeView } from "./nodes";
import type { RoutingSettings, RoutingView } from "./routing-model";

let settings: RoutingSettings = {
    mode: "rule",
    rules: [],
    global_target: null,
};

export function routingPreview(
    name: string,
    args: Record<string, unknown> | undefined,
    ready: boolean,
    routes: NodeView["routes"],
): RoutingView {
    const targets = [
        ...new Set(routes.flatMap((r) => [r.group, ...r.choices])),
    ].filter((name) => !["DIRECT", "REJECT", "GLOBAL"].includes(name));
    if (name === "save_routing") {
        settings = {
            ...structuredClone(args?.settings as RoutingSettings),
            global_target: settings.global_target,
        };
        if (settings.mode === "global" && !settings.global_target) {
            settings.global_target =
                routes
                    .flatMap((r) => r.choices)
                    .find(
                        (name) =>
                            !["DIRECT", "REJECT", "自动选择"].includes(name),
                    ) || null;
        }
    }
    return structuredClone({ settings, targets, ready, error: null });
}

export function selectPreviewGlobal(target: string) {
    settings.global_target = target;
}

export function routingPreviewRoutes(
    routes: NodeView["routes"],
): NodeView["routes"] {
    if (settings.mode === "direct") return [];
    if (settings.mode === "rule" || !routes.length) return routes;
    const choices = [...new Set(routes.flatMap((r) => r.choices))].filter(
        (name) => !["DIRECT", "REJECT", "GLOBAL", "自动选择"].includes(name),
    );
    return [
        {
            group: "GLOBAL",
            selected: settings.global_target || choices[0],
            choices,
        },
    ];
}
