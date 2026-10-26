import {
    subscriptionIntervalLabel,
    subscriptionIntervals,
    subscriptionTime,
    type useNodes,
} from "./nodes";

type Props = {
    nodes: ReturnType<typeof useNodes>;
    disabled?: boolean;
};

export default function SubscriptionSettings({ nodes, disabled }: Props) {
    const saving = nodes.subscriptionPending === "interval";
    const blocked =
        disabled ||
        !nodes.ready ||
        !!nodes.subscriptionPending ||
        nodes.view.loading ||
        nodes.view.testing ||
        !!nodes.pending;
    return (
        <section
            className="startup-settings subscription-settings"
            aria-label="订阅更新设置"
        >
            <h3>订阅更新</h3>
            <div className="startup-row">
                <div>
                    <h4>
                        <label htmlFor="subscription-interval">
                            自动更新周期
                        </label>
                    </h4>
                    <p id="subscription-interval-description">
                        默认每 1
                        小时更新节点配置。应用运行期间生效，也可在首页立即更新。
                    </p>
                </div>
                <div className="subscription-settings-control">
                    <select
                        id="subscription-interval"
                        aria-describedby="subscription-interval-description"
                        value={nodes.view.subscription_interval_seconds}
                        disabled={blocked}
                        onChange={(e) =>
                            void nodes.setSubscriptionInterval(
                                Number(e.target.value),
                            )
                        }
                    >
                        {subscriptionIntervals.map((seconds) => (
                            <option key={seconds} value={seconds}>
                                {subscriptionIntervalLabel(seconds)}
                            </option>
                        ))}
                    </select>
                    <span role="status">
                        {saving
                            ? "正在保存…"
                            : !nodes.ready
                              ? "正在读取设置…"
                              : "仅保存在此设备"}
                    </span>
                </div>
            </div>
            <p className="background-hint">
                上次订阅更新：
                {subscriptionTime(nodes.view.subscription_synced_at)}。
                更新订阅同步节点配置，线路能否连接仍以实际检测为准。
            </p>
            {nodes.subscriptionError && (
                <p className="startup-error" role="alert">
                    {nodes.subscriptionError}
                </p>
            )}
            {!nodes.ready && nodes.error && (
                <p className="startup-error" role="alert">
                    {nodes.error}
                </p>
            )}
        </section>
    );
}
