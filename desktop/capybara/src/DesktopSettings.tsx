import { useEffect, useRef, useState } from "react";
import { command, errorText, native, preview } from "./bridge";

export type DesktopSettingsView = {
    autostart_enabled: boolean;
    background_available: boolean;
};

export default function DesktopSettings() {
    const [settings, setSettings] = useState<DesktopSettingsView | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const changing = useRef(false);
    const revision = useRef(0);
    const mounted = useRef(false);
    const available = native || !!preview;

    const refresh = async () => {
        if (!available || changing.current) return;
        const request = ++revision.current;
        try {
            const next = await command<DesktopSettingsView>("desktop_settings");
            if (mounted.current && request === revision.current) {
                setSettings(next);
                setError("");
            }
        } catch (e) {
            if (mounted.current && request === revision.current) {
                setSettings(null);
                setError(errorText(e));
            }
        }
    };
    useEffect(() => {
        mounted.current = true;
        void refresh();
        window.addEventListener("focus", refresh);
        return () => {
            mounted.current = false;
            window.removeEventListener("focus", refresh);
        };
    }, []);

    const toggle = async () => {
        if (!settings || changing.current) return;
        changing.current = true;
        revision.current++;
        setBusy(true);
        setError("");
        try {
            const next = await command<DesktopSettingsView>("set_autostart", {
                enabled: !settings.autostart_enabled,
            });
            if (mounted.current) setSettings(next);
        } catch (e) {
            // Re-read in case the OS changed the setting before reporting failure.
            let actual: DesktopSettingsView | null = null;
            try {
                actual = await command<DesktopSettingsView>("desktop_settings");
            } catch {
                /* Unknown is not the same as disabled. */
            }
            if (mounted.current) {
                setSettings(actual);
                setError(errorText(e));
            }
        } finally {
            changing.current = false;
            if (mounted.current) setBusy(false);
        }
    };

    return (
        <section className="startup-settings" aria-label="启动与后台">
            <h3>启动与后台</h3>
            <div className="startup-row">
                <div>
                    <h4 id="autostart-label">开机自启</h4>
                    <p id="autostart-description">
                        登录电脑后在后台启动卡皮巴拉，需要连接时再打开应用。
                    </p>
                </div>
                <div className="startup-control">
                    <span role="status">
                        {busy
                            ? "正在保存…"
                            : !available
                              ? "请在客户端设置"
                              : !settings
                                ? error
                                    ? "读取失败"
                                    : "读取中…"
                                : settings.autostart_enabled
                                  ? "已开启"
                                  : "已关闭"}
                    </span>
                    <button
                        className="startup-switch"
                        role="switch"
                        aria-labelledby="autostart-label"
                        aria-describedby="autostart-description"
                        aria-checked={settings?.autostart_enabled ?? false}
                        disabled={!available || !settings || busy}
                        onClick={() => void toggle()}
                    >
                        <span />
                    </button>
                </div>
            </div>
            <p className="background-hint">
                {settings?.background_available === false
                    ? "当前系统托盘不可用，关闭窗口会退出应用。"
                    : "关闭窗口后继续在后台运行，当前连接保持开启。点击系统托盘图标可重新打开，选择“退出卡皮巴拉”才会断开并退出。"}
            </p>
            {error && (
                <div className="startup-error">
                    <span role="alert">{error}</span>
                    <button
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => void refresh()}
                    >
                        重新读取
                    </button>
                </div>
            )}
        </section>
    );
}
