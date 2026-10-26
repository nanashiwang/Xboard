import { useEffect, useRef, useState } from "react";
import {
    ArrowDown,
    ArrowUp,
    LoaderCircle,
    Plus,
    Settings2,
    Trash2,
    X,
} from "lucide-react";
import { command, errorText } from "./bridge";
import {
    emptyRouting,
    routingModes,
    ruleKinds,
    validateRules,
    type CustomRule,
    type RoutingSettings,
    type RoutingView,
} from "./routing-model";
import "./routing.css";

export function useRouting(onSaved?: () => void | Promise<void>) {
    const [view, setView] = useState<RoutingView>(emptyRouting);
    const [loading, setLoading] = useState(true);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [pollError, setPollError] = useState("");
    const alive = useRef(true),
        saving = useRef(false),
        generation = useRef(0);
    const onSavedRef = useRef(onSaved);
    onSavedRef.current = onSaved;
    useEffect(() => {
        alive.current = true;
        let cancelled = false;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            const revision = generation.current;
            if (!saving.current) {
                try {
                    const next = await command<RoutingView>("routing_snapshot");
                    if (!cancelled && revision === generation.current) {
                        setView(next);
                        setLoading(false);
                        setPollError("");
                    }
                } catch (e) {
                    if (!cancelled && revision === generation.current) {
                        setPollError(errorText(e));
                    }
                }
            }
            if (!cancelled) timer = setTimeout(poll, 2000);
        };
        void poll();
        return () => {
            cancelled = true;
            alive.current = false;
            clearTimeout(timer);
        };
    }, []);
    const save = async (settings: RoutingSettings): Promise<boolean> => {
        if (saving.current) return false;
        saving.current = true;
        generation.current++;
        setBusy(true);
        setError("");
        try {
            const next = await command<RoutingView>("save_routing", {
                settings,
            });
            if (!alive.current) return false;
            setView(next);
            setLoading(false);
            await onSavedRef.current?.();
            return true;
        } catch (e) {
            if (alive.current) setError(errorText(e));
            return false;
        } finally {
            saving.current = false;
            if (alive.current) setBusy(false);
        }
    };
    return { view, loading, busy, error: error || pollError, save };
}
export type RoutingState = ReturnType<typeof useRouting>;

export default function Routing({
    routing,
    disabled = false,
}: {
    routing: RoutingState;
    disabled?: boolean;
}) {
    const [open, setOpen] = useState(false);
    const [draft, setDraft] = useState<CustomRule[]>([]);
    const [validation, setValidation] = useState("");
    const [saved, setSaved] = useState(false);
    const dialog = useRef<HTMLDialogElement>(null);
    const { view, busy, loading, error } = routing;
    const locked = busy || loading || disabled;
    useEffect(() => {
        if (open) dialog.current?.showModal?.();
        else dialog.current?.close?.();
    }, [open]);
    const startEdit = () => {
        setDraft(view.settings.rules.map((rule) => ({ ...rule })));
        setValidation("");
        setSaved(false);
        setOpen(true);
    };
    const updateRule = (index: number, patch: Partial<CustomRule>) => {
        setDraft((old) =>
            old.map((rule, i) => (i === index ? { ...rule, ...patch } : rule)),
        );
        setValidation("");
    };
    const move = (index: number, direction: number) => {
        setDraft((old) => {
            const next = [...old];
            [next[index], next[index + direction]] = [
                next[index + direction],
                next[index],
            ];
            return next;
        });
    };
    const saveRules = async () => {
        const message = validateRules(draft);
        setValidation(message);
        if (message) return;
        const rules = draft.map((rule) => ({
            ...rule,
            value: rule.value.trim(),
        }));
        if (await routing.save({ ...view.settings, rules })) {
            setOpen(false);
            setSaved(true);
        }
    };
    const targets = [
        ...new Set([
            "DIRECT",
            "REJECT",
            ...view.targets.filter((target) => target !== "GLOBAL"),
        ]),
    ];
    return (
        <section className="routing-control glass-card" aria-label="分流设置">
            <div className="routing-heading">
                <span>
                    <Settings2 size={18} />
                    <strong>分流模式</strong>
                </span>
                <button
                    className="routing-manage"
                    disabled={locked}
                    onClick={startEdit}
                >
                    管理规则
                    {view.settings.rules.length > 0 && (
                        <span>{view.settings.rules.length}</span>
                    )}
                </button>
            </div>
            <div className="routing-modes" aria-label="选择分流模式">
                {routingModes.map((mode) => (
                    <button
                        key={mode.id}
                        disabled={locked}
                        aria-pressed={
                            !loading && view.settings.mode === mode.id
                        }
                        onClick={() => {
                            setSaved(false);
                            void routing.save({
                                ...view.settings,
                                mode: mode.id,
                            });
                        }}
                    >
                        {mode.label}
                    </button>
                ))}
            </div>
            <p className="routing-description">
                {loading
                    ? "正在读取分流设置…"
                    : routingModes.find(
                          (mode) => mode.id === view.settings.mode,
                      )?.description}
            </p>
            <p className="routing-scope">
                仅影响交给客户端的流量；不使用系统代理的应用不会跟随切换。
            </p>
            {busy && (
                <p className="routing-feedback" role="status">
                    <LoaderCircle size={14} className="spin" />
                    正在保存并确认…
                </p>
            )}
            {(error || view.error) && !open && (
                <p className="routing-feedback routing-error" role="alert">
                    {error || view.error}
                </p>
            )}
            {saved && (
                <p className="routing-feedback" role="status">
                    {view.settings.mode !== "rule"
                        ? "分流规则已保存，切回规则模式后生效。"
                        : view.ready
                          ? "分流规则已保存并应用。"
                          : "分流规则已保存，准备节点时自动应用。"}
                </p>
            )}
            {open && (
                <dialog
                    ref={dialog}
                    className="routing-dialog"
                    aria-labelledby="routing-dialog-title"
                    onCancel={(event) => {
                        if (busy) event.preventDefault();
                        else setOpen(false);
                    }}
                >
                    <div className="routing-dialog-heading">
                        <div>
                            <h2 id="routing-dialog-title">自定义分流规则</h2>
                            <p>
                                从上往下匹配，优先于套餐规则；仅在规则模式生效。
                            </p>
                        </div>
                        <button
                            aria-label="关闭规则设置"
                            disabled={busy}
                            onClick={() => setOpen(false)}
                        >
                            <X size={20} />
                        </button>
                    </div>
                    <div className="routing-rule-list">
                        {!draft.length && (
                            <div className="routing-empty">
                                <Settings2 size={28} />
                                <strong>正在使用套餐规则</strong>
                                <p>
                                    添加域名或 IP
                                    网段，指定直连、拦截或使用某个节点。
                                </p>
                            </div>
                        )}
                        {draft.map((rule, index) => (
                            <fieldset
                                className="routing-rule"
                                key={index}
                                disabled={busy}
                            >
                                <legend>规则 {index + 1}</legend>
                                <div className="routing-rule-fields">
                                    <label>
                                        匹配类型
                                        <select
                                            aria-label={`规则 ${index + 1} 匹配类型`}
                                            value={rule.kind}
                                            onChange={(e) =>
                                                updateRule(index, {
                                                    kind: e.target
                                                        .value as CustomRule["kind"],
                                                })
                                            }
                                        >
                                            {ruleKinds.map((kind) => (
                                                <option
                                                    key={kind.id}
                                                    value={kind.id}
                                                >
                                                    {kind.label}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                    <label className="routing-value">
                                        匹配内容
                                        <input
                                            aria-label={`规则 ${index + 1} 匹配内容`}
                                            autoCapitalize="none"
                                            autoCorrect="off"
                                            spellCheck={false}
                                            value={rule.value}
                                            placeholder={
                                                ruleKinds.find(
                                                    (kind) =>
                                                        kind.id === rule.kind,
                                                )?.example
                                            }
                                            onChange={(e) =>
                                                updateRule(index, {
                                                    value: e.target.value,
                                                })
                                            }
                                        />
                                    </label>
                                    <label>
                                        处理方式
                                        <select
                                            aria-label={`规则 ${index + 1} 处理方式`}
                                            value={rule.target}
                                            onChange={(e) =>
                                                updateRule(index, {
                                                    target: e.target.value,
                                                })
                                            }
                                        >
                                            {!targets.includes(rule.target) && (
                                                <option value={rule.target}>
                                                    {rule.target}（暂不可用）
                                                </option>
                                            )}
                                            {targets.map((target) => (
                                                <option
                                                    key={target}
                                                    value={target}
                                                >
                                                    {target === "DIRECT"
                                                        ? "直连"
                                                        : target === "REJECT"
                                                          ? "拦截"
                                                          : target}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                </div>
                                <div className="routing-rule-actions">
                                    <span>优先级 {index + 1}</span>
                                    <button
                                        aria-label={`上移规则 ${index + 1}`}
                                        disabled={index === 0 || busy}
                                        onClick={() => move(index, -1)}
                                    >
                                        <ArrowUp size={15} />
                                        上移
                                    </button>
                                    <button
                                        aria-label={`下移规则 ${index + 1}`}
                                        disabled={
                                            index === draft.length - 1 || busy
                                        }
                                        onClick={() => move(index, 1)}
                                    >
                                        <ArrowDown size={15} />
                                        下移
                                    </button>
                                    <button
                                        className="routing-delete"
                                        aria-label={`删除规则 ${index + 1}`}
                                        onClick={() =>
                                            setDraft((old) =>
                                                old.filter(
                                                    (_, i) => i !== index,
                                                ),
                                            )
                                        }
                                    >
                                        <Trash2 size={15} />
                                        删除
                                    </button>
                                </div>
                            </fieldset>
                        ))}
                        <button
                            className="routing-add"
                            disabled={busy}
                            onClick={() =>
                                setDraft((old) => [
                                    ...old,
                                    {
                                        kind: "DOMAIN-SUFFIX",
                                        value: "",
                                        target: "DIRECT",
                                    },
                                ])
                            }
                        >
                            <Plus size={17} />
                            添加规则
                        </button>
                        {!view.ready && !view.targets.length && (
                            <p className="routing-hint">
                                当前可以保存直连和拦截规则。登录并加载套餐节点后，可选择代理组或节点。
                            </p>
                        )}
                        {!view.ready && view.targets.length > 0 && (
                            <p className="routing-hint">
                                保存有效规则后会重新准备节点。
                            </p>
                        )}
                        {view.settings.mode !== "rule" && (
                            <p className="routing-hint">
                                当前为
                                {view.settings.mode === "global"
                                    ? "全局"
                                    : "直连"}
                                模式。保存后切回“规则”模式才会使用这些规则。
                            </p>
                        )}
                    </div>
                    {(validation || error || view.error) && (
                        <p
                            className="routing-feedback routing-error"
                            role="alert"
                        >
                            {validation || error || view.error}
                        </p>
                    )}
                    <div className="routing-dialog-footer">
                        <span>规则保存在这台设备，刷新套餐配置后仍保留。</span>
                        <button disabled={busy} onClick={() => setOpen(false)}>
                            取消
                        </button>
                        <button
                            className="routing-save"
                            disabled={busy}
                            onClick={() => void saveRules()}
                        >
                            {busy && (
                                <LoaderCircle size={15} className="spin" />
                            )}
                            {busy ? "正在保存…" : "保存规则"}
                        </button>
                    </div>
                </dialog>
            )}
        </section>
    );
}
