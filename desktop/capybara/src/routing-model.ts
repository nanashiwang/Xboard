export type RoutingMode = "rule" | "global" | "direct";
export type RuleKind = "DOMAIN" | "DOMAIN-SUFFIX" | "IP-CIDR" | "IP-CIDR6";
export type CustomRule = { kind: RuleKind; value: string; target: string };
export type RoutingSettings = {
    mode: RoutingMode;
    rules: CustomRule[];
    global_target: string | null;
};
export type RoutingView = {
    settings: RoutingSettings;
    targets: string[];
    ready: boolean;
    error: string | null;
};
export const emptyRouting: RoutingView = {
    settings: { mode: "rule", rules: [], global_target: null },
    targets: [],
    ready: false,
    error: null,
};
export const routingModes: {
    id: RoutingMode;
    label: string;
    description: string;
}[] = [
    {
        id: "rule",
        label: "规则",
        description: "按自定义规则和套餐规则决定直连或代理。",
    },
    {
        id: "global",
        label: "全局",
        description: "进入客户端的流量统一走右侧选择的全局节点。",
    },
    {
        id: "direct",
        label: "直连",
        description: "进入客户端的流量直接访问，不经过代理节点。",
    },
];
export const ruleKinds: { id: RuleKind; label: string; example: string }[] = [
    { id: "DOMAIN", label: "完整域名", example: "www.example.com" },
    { id: "DOMAIN-SUFFIX", label: "域名及子域名", example: "example.com" },
    { id: "IP-CIDR", label: "IPv4 网段", example: "192.168.0.0/16" },
    { id: "IP-CIDR6", label: "IPv6 网段", example: "2001:db8::/32" },
];
export function routingLabel(mode: RoutingMode) {
    return routingModes.find((item) => item.id === mode)!.label;
}
export function validateRules(rules: CustomRule[]) {
    for (let i = 0; i < rules.length; i++) {
        const rule = rules[i];
        if (!rule.value.trim()) return `请填写第 ${i + 1} 条规则的匹配内容。`;
        if (/[\s,\r\n]/.test(rule.value.trim()))
            return `第 ${i + 1} 条规则不能包含空格或逗号。`;
        if (!rule.target) return `请选择第 ${i + 1} 条规则的处理方式。`;
        if (
            (rule.kind === "DOMAIN" || rule.kind === "DOMAIN-SUFFIX") &&
            (/[:/\\*]/.test(rule.value) || rule.value.startsWith("."))
        )
            return `第 ${i + 1} 条规则只填写域名，例如 example.com，不包含网址前缀或通配符。`;
        if (
            (rule.kind === "IP-CIDR" || rule.kind === "IP-CIDR6") &&
            !rule.value.includes("/")
        )
            return `第 ${i + 1} 条规则需要网段前缀，例如 ${rule.kind === "IP-CIDR" ? "192.168.0.0/16" : "2001:db8::/32"}。`;
    }
    return "";
}
