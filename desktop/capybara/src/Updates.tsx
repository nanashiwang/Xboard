import { useEffect, useRef, useState } from "react";
import { ArrowDownToLine, RefreshCw, X } from "lucide-react";
import { command, errorText, native, preview } from "./bridge";

export type UpdateView = {
    phase: string;
    last_checked: number | null;
    release: { version: string; notes: string } | null;
    prompt: boolean;
    downloaded: number;
    total: number | null;
    error: string | null;
    manual_install: boolean;
};
export const emptyUpdate: UpdateView = {
    phase: "idle",
    last_checked: null,
    release: null,
    prompt: false,
    downloaded: 0,
    total: null,
    error: null,
    manual_install: false,
};
export default function Updates({
    version,
    settings,
    blocked,
}: {
    version: string;
    settings: boolean;
    blocked: boolean;
}) {
    const [state, setState] = useState(emptyUpdate);
    const [action, setAction] = useState(false);
    const dialog = useRef<HTMLDialogElement>(null);
    const mutation = useRef(false);
    const revision = useRef(0);
    const running = ["downloading", "installing", "restarting"].includes(
        state.phase,
    );
    useEffect(() => {
        if (!native && !preview) return;
        let live = true,
            polling = false;
        const poll = async () => {
            if (polling || mutation.current) return;
            polling = true;
            const started = revision.current;
            try {
                const next = await command<UpdateView>("update_snapshot");
                if (live && !mutation.current && started === revision.current)
                    setState(next);
            } catch {
                /* A stopped app must not create repeated error popups. */
            } finally {
                polling = false;
            }
        };
        void poll();
        const timer = setInterval(poll, 1000);
        return () => {
            live = false;
            clearInterval(timer);
        };
    }, []);
    useEffect(() => {
        if (state.prompt && !blocked) {
            if (!dialog.current?.open) dialog.current?.showModal();
        } else dialog.current?.close();
    }, [state.prompt, blocked]);
    const run = async (name: string) => {
        if (mutation.current) return;
        mutation.current = true;
        revision.current++;
        setAction(true);
        // Keep progress polling active while the native download command is pending.
        if (name === "install_update") {
            setState((s) => ({ ...s, phase: "downloading", error: null }));
        }
        try {
            setState(await command<UpdateView>(name));
        } catch (e) {
            setState((s) => ({ ...s, phase: "error", error: errorText(e) }));
        } finally {
            mutation.current = false;
            setAction(false);
        }
    };
    // Native progress is fetched independently of account requests and of the pending install call.
    useEffect(() => {
        if (!running) return;
        let live = true;
        const timer = setInterval(() => {
            void command<UpdateView>("update_snapshot")
                .then((s) => {
                    if (live) setState(s);
                })
                .catch(() => {});
        }, 500);
        return () => {
            live = false;
            clearInterval(timer);
        };
    }, [running]);
    const label =
        state.phase === "checking" || (action && !running)
            ? "正在检查更新…"
            : state.error
              ? state.error
              : state.release
                ? `发现新版本 v${state.release.version}`
                : state.phase === "current"
                  ? "已是最新版本"
                  : "会在后台自动检查新版本";
    const percent =
        state.total && state.total > 0
            ? Math.min(100, Math.round((state.downloaded / state.total) * 100))
            : null;
    return (
        <>
            {settings && (
                <section className="update-settings" aria-label="应用更新">
                    <div>
                        <h3>应用更新</h3>
                        <p role="status">{label}</p>
                        <small>
                            每 6 小时自动检查，安装前需要你确认。
                            {state.last_checked &&
                                ` 上次检查：${new Date(state.last_checked * 1000).toLocaleString("zh-CN")}`}
                        </small>
                    </div>
                    {state.release && (
                        <button
                            className="primary-button"
                            disabled={
                                action || running || state.phase === "checking"
                            }
                            onClick={() => void run("show_update")}
                        >
                            <ArrowDownToLine size={17} />
                            查看更新
                        </button>
                    )}
                    <button
                        className="secondary-button"
                        disabled={
                            action ||
                            running ||
                            state.phase === "checking" ||
                            (!native && !preview)
                        }
                        onClick={() => void run("check_updates")}
                    >
                        <RefreshCw size={17} />
                        立即检查
                    </button>
                </section>
            )}
            <dialog
                ref={dialog}
                className="login-dialog update-dialog"
                aria-labelledby="update-title"
                onCancel={(e) => {
                    e.preventDefault();
                    if (!running && !action) void run("dismiss_update");
                }}
            >
                {!running && (
                    <button
                        className="icon-button modal-close"
                        aria-label="稍后更新"
                        disabled={action}
                        onClick={() => void run("dismiss_update")}
                    >
                        <X size={18} />
                    </button>
                )}
                <img className="update-icon" src="/capybara-icon.png" alt="" />
                <h2 id="update-title">
                    {running ? "正在更新卡皮巴拉" : "卡皮巴拉有新版本了"}
                </h2>
                <p>
                    v{version} → v{state.release?.version}
                </p>
                {state.release?.notes && (
                    <div className="update-notes">{state.release.notes}</div>
                )}
                {state.error && (
                    <p className="update-error" role="alert">
                        {state.error}
                    </p>
                )}
                {running ? (
                    <div role="status" className="update-progress">
                        <p>
                            {state.phase === "downloading"
                                ? `正在下载并校验更新${percent === null ? "…" : ` · ${percent}%`}`
                                : state.phase === "restarting"
                                  ? "更新完成，正在重新启动…"
                                  : "正在安装，请保持应用打开…"}
                        </p>
                        {state.phase === "downloading" && (
                            <progress
                                max={100}
                                value={percent ?? undefined}
                                aria-label="更新下载进度"
                            />
                        )}
                    </div>
                ) : (
                    <>
                        <p>
                            {state.manual_install
                                ? "此安装方式需要通过系统安装器更新。确认后将打开官网下载页，请下载新版 DEB 安装包。"
                                : "确认后下载更新，安装前会断开连接并恢复系统代理，完成后重新启动。"}
                        </p>
                        <div className="update-actions">
                            <button
                                className="secondary-button"
                                disabled={action}
                                onClick={() => void run("dismiss_update")}
                            >
                                稍后
                            </button>
                            <button
                                className="primary-button"
                                disabled={action}
                                onClick={() => void run("install_update")}
                            >
                                <ArrowDownToLine size={17} />
                                {state.manual_install
                                    ? "前往下载更新"
                                    : state.error
                                      ? "重试更新"
                                      : "更新并重启"}
                            </button>
                        </div>
                    </>
                )}
            </dialog>
        </>
    );
}
