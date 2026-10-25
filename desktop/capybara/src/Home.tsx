import { useEffect, useRef, useState, type ReactNode } from "react";
import {
    ArrowUpRight,
    Check,
    ChevronRight,
    Compass,
    Globe2,
    LoaderCircle,
    Power,
    RefreshCw,
    Search,
    ShieldCheck,
    Signal,
    Wifi,
} from "lucide-react";
import { bytes, quotaPercent, type View } from "./model";
import "./home.css";

const regions = ["全部", "亚洲", "美洲", "欧洲", "其他"] as const;
const locations = [
    ["新加坡|Singapore|🇸🇬", "🇸🇬", "亚洲"],
    ["日本|Japan|🇯🇵", "🇯🇵", "亚洲"],
    ["香港|Hong Kong|🇭🇰", "🇭🇰", "亚洲"],
    ["台湾|Taiwan|🇹🇼", "🇹🇼", "亚洲"],
    ["韩国|Korea|🇰🇷", "🇰🇷", "亚洲"],
    ["美国|United States|🇺🇸", "🇺🇸", "美洲"],
    ["加拿大|Canada|🇨🇦", "🇨🇦", "美洲"],
    ["英国|United Kingdom|🇬🇧", "🇬🇧", "欧洲"],
    ["德国|Germany|🇩🇪", "🇩🇪", "欧洲"],
    ["法国|France|🇫🇷", "🇫🇷", "欧洲"],
    ["荷兰|Netherlands|🇳🇱", "🇳🇱", "欧洲"],
    ["罗马尼亚|Romania|🇷🇴", "🇷🇴", "欧洲"],
    ["澳大利亚|Australia|🇦🇺", "🇦🇺", "其他"],
];
export function nodeLocation(name: string) {
    const match = locations.find(([pattern]) =>
        new RegExp(pattern, "i").test(name),
    );
    return { flag: match?.[1] || "", region: match?.[2] || "其他" };
}
function NodeSymbol({ name }: { name: string }) {
    const { flag } = nodeLocation(name);
    return (
        <span className="node-symbol" aria-hidden="true">
            {flag || <Globe2 size={21} />}
        </span>
    );
}
type Props = {
    view: View;
    busy: string;
    eligible: boolean;
    primaryText: string;
    onPrimary: () => void;
    onAction: (name: string, args?: Record<string, unknown>) => Promise<void>;
    onPlans: () => void;
    notice: ReactNode;
};
export default function Home({
    view,
    busy,
    eligible,
    primaryText,
    onPrimary,
    onAction,
    onPlans,
    notice,
}: Props) {
    const [query, setQuery] = useState("");
    const [region, setRegion] = useState<string>("全部");
    const [group, setGroup] = useState("");
    const search = useRef<HTMLInputElement>(null);
    const connected = view.connection === "connected";
    const routes = connected ? view.routes : [];
    const route = routes.find((r) => r.group === group) || routes[0];
    const selected = route?.selected;
    const percent = quotaPercent(view.subscription);
    const choices = (route?.choices || []).filter(
        (name) =>
            name
                .toLocaleLowerCase()
                .includes(query.trim().toLocaleLowerCase()) &&
            (region === "全部" || nodeLocation(name).region === region),
    );
    useEffect(() => {
        setQuery("");
        setRegion("全部");
        setGroup("");
    }, [view.logged_in, view.profile?.email, connected]);
    const showNodes = () => {
        search.current?.scrollIntoView({ block: "nearest" });
        search.current?.focus();
    };
    const connectionLabel = connected
        ? view.connection_error
            ? "连接待检查"
            : "已连接"
        : busy === "connect"
          ? "正在连接"
          : "未连接";
    return (
        <div className="scenic-home">
            {notice && <div className="home-notice">{notice}</div>}
            <div className="home-layout">
                <div className="home-center">
                    <section className="journey-hero" aria-label="我的连接">
                        <img
                            className="journey-art"
                            src="/capybara-journey.png"
                            alt="蓝色山水间，戴蓝围巾和旅行背包的卡皮巴拉"
                        />
                        <div className="journey-shade" />
                        <div className="journey-copy">
                            <span
                                className={
                                    "connection-state " +
                                    (connected && !view.connection_error
                                        ? "is-online"
                                        : "")
                                }
                            >
                                <i />
                                {connectionLabel}
                            </span>
                            <h2>
                                {connected
                                    ? selected || "轻松连接"
                                    : "世界很大，\n一起出发。"}
                            </h2>
                            <p>慢下来，也能和世界靠得很近。</p>
                            <div className="journey-power-wrap">
                                <button
                                    className={
                                        "journey-power " +
                                        (connected ? "is-on" : "")
                                    }
                                    disabled={!!busy || !eligible}
                                    onClick={onPrimary}
                                    aria-label={primaryText}
                                >
                                    {busy === "connect" ||
                                    busy === "disconnect" ? (
                                        <LoaderCircle
                                            size={48}
                                            className="spin"
                                        />
                                    ) : (
                                        <Power size={48} strokeWidth={2.2} />
                                    )}
                                </button>
                                <span>{primaryText}</span>
                                {!view.logged_in && (
                                    <button
                                        className="journey-register"
                                        disabled={!!busy}
                                        onClick={() =>
                                            void onAction(
                                                "begin_browser_login",
                                                { registration: true },
                                            )
                                        }
                                    >
                                        注册账号 <ArrowUpRight size={14} />
                                    </button>
                                )}
                            </div>
                        </div>
                    </section>
                    <button
                        className="current-node glass-card"
                        onClick={showNodes}
                        aria-label="查看首页节点列表"
                    >
                        <NodeSymbol name={selected || ""} />
                        <span className="current-node-copy">
                            <strong>
                                {selected ||
                                    (connected
                                        ? "按规则自动分流"
                                        : "连接后选择节点")}
                            </strong>
                            <small>
                                <Wifi size={14} />
                                {connected
                                    ? view.connection_error
                                        ? "请检测当前连接"
                                        : "系统代理已开启"
                                    : "连接前自动检查套餐状态"}
                            </small>
                        </span>
                        <ChevronRight size={20} />
                    </button>
                    <div className="home-shortcuts">
                        <div className="home-shortcut glass-card">
                            <span className="shortcut-icon">
                                <ShieldCheck size={25} />
                            </span>
                            <span>
                                <strong>规则分流</strong>
                                <small>跟随套餐连接规则</small>
                            </span>
                        </div>
                        <button
                            className="home-shortcut glass-card"
                            onClick={onPlans}
                        >
                            <span className="shortcut-icon">
                                <Signal size={25} />
                            </span>
                            <span>
                                <strong>
                                    {view.subscription
                                        ? bytes(
                                              view.subscription.traffic
                                                  .remaining_bytes,
                                          )
                                        : "查看套餐"}
                                </strong>
                                <small>
                                    {view.subscription
                                        ? "本期剩余流量"
                                        : "找到适合你的连接"}
                                </small>
                            </span>
                            <ChevronRight size={16} />
                        </button>
                        <button
                            className="home-shortcut glass-card"
                            disabled={!connected || !!busy}
                            onClick={() => void onAction("check_connection")}
                        >
                            <span className="shortcut-icon">
                                <RefreshCw
                                    size={25}
                                    className={
                                        busy === "check_connection"
                                            ? "spin"
                                            : ""
                                    }
                                />
                            </span>
                            <span>
                                <strong>
                                    {busy === "check_connection"
                                        ? "正在检测"
                                        : "连接检测"}
                                </strong>
                                <small>检查当前网络连通</small>
                            </span>
                        </button>
                    </div>
                    <div className="home-usage glass-card">
                        <div>
                            <span>本期流量</span>
                            <span>
                                {view.subscription
                                    ? `已用 ${bytes(view.subscription.traffic.used_bytes)} / ${bytes(view.subscription.traffic.total_bytes)}`
                                    : "登录后自动同步"}
                            </span>
                            {view.logged_in && view.synced_at && (
                                <span className="home-sync">
                                    同步于{" "}
                                    {new Date(
                                        view.synced_at * 1000,
                                    ).toLocaleTimeString("zh-CN", {
                                        hour: "2-digit",
                                        minute: "2-digit",
                                    })}
                                </span>
                            )}
                            <button
                                aria-label="立即同步流量"
                                disabled={!view.logged_in || !!busy}
                                onClick={() => void onAction("refresh")}
                            >
                                <RefreshCw
                                    size={14}
                                    className={busy === "refresh" ? "spin" : ""}
                                />
                            </button>
                        </div>
                        <div
                            className={
                                "home-usage-track " +
                                (percent >= 90 ? "low" : "")
                            }
                            role="progressbar"
                            aria-label="本期流量已使用"
                            aria-valuenow={Math.round(percent)}
                            aria-valuemin={0}
                            aria-valuemax={100}
                        >
                            <span style={{ width: `${percent}%` }} />
                        </div>
                    </div>
                </div>
                <section
                    className="home-nodes glass-card"
                    aria-label="首页节点列表"
                >
                    <div className="node-panel-title">
                        <h2>选择节点</h2>
                        <span>
                            {route
                                ? `${route.choices.length} 个选项`
                                : "随套餐同步"}
                        </span>
                    </div>
                    <label className="node-search">
                        <Search size={18} />
                        <input
                            ref={search}
                            aria-label="搜索节点"
                            placeholder="搜索国家、地区或节点"
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                        />
                    </label>
                    {routes.length > 1 && (
                        <label className="node-group-picker">
                            选择分流组
                            <select
                                aria-label="选择分流组"
                                value={route?.group || ""}
                                onChange={(e) => {
                                    setGroup(e.target.value);
                                    setQuery("");
                                    setRegion("全部");
                                }}
                            >
                                {routes.map((r) => (
                                    <option key={r.group}>{r.group}</option>
                                ))}
                            </select>
                        </label>
                    )}
                    <div className="node-regions" aria-label="节点地区筛选">
                        {regions.map((name) => (
                            <button
                                key={name}
                                aria-pressed={region === name}
                                onClick={() => setRegion(name)}
                            >
                                {name}
                            </button>
                        ))}
                    </div>
                    <div className="home-node-list">
                        {!connected ? (
                            <div className="node-empty">
                                <Compass size={38} strokeWidth={1.4} />
                                <h3>
                                    {view.logged_in
                                        ? "连接后，选择你的目的地"
                                        : "登录，开启下一段旅程"}
                                </h3>
                                <p>
                                    {view.logged_in
                                        ? "建立连接后，这里会显示当前套餐的可选节点。"
                                        : "真实节点会随你的套餐同步，登录后即可开始连接。"}
                                </p>
                            </div>
                        ) : !route ? (
                            <div className="node-empty">
                                <ShieldCheck size={36} />
                                <h3>正在按规则连接</h3>
                                <p>当前配置没有可手动选择的节点组。</p>
                            </div>
                        ) : choices.length === 0 ? (
                            <div className="node-empty">
                                <Search size={32} />
                                <h3>没有找到匹配节点</h3>
                                <button
                                    onClick={() => {
                                        setQuery("");
                                        setRegion("全部");
                                    }}
                                >
                                    清除筛选
                                </button>
                            </div>
                        ) : (
                            choices.map((name) => (
                                <button
                                    className={
                                        "home-node " +
                                        (name === selected ? "selected" : "")
                                    }
                                    key={name}
                                    aria-label={`选择节点 ${name}`}
                                    aria-pressed={name === selected}
                                    disabled={!!busy}
                                    onClick={() =>
                                        void onAction("select_route", {
                                            group: route!.group,
                                            name,
                                        })
                                    }
                                >
                                    <NodeSymbol name={name} />
                                    <span>{name}</span>
                                    {name === selected ? (
                                        <Check
                                            size={18}
                                            aria-label="当前节点"
                                        />
                                    ) : (
                                        <ChevronRight size={16} />
                                    )}
                                </button>
                            ))
                        )}
                    </div>
                    <div className="node-panel-footer">
                        <ShieldCheck size={16} />
                        <span>
                            {connected
                                ? "切换节点后会自动检查连接"
                                : "你的连接，由你选择"}
                        </span>
                    </div>
                </section>
            </div>
        </div>
    );
}
