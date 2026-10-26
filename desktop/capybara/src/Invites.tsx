import { useEffect, useRef, useState } from "react";
import { ArrowUpRight, Copy, Plus, RefreshCw, Users } from "lucide-react";
import QRCode from "qrcode";
import { command, errorText } from "./bridge";
import type { View } from "./model";
import { money } from "./store-model";
import {
    invitationDate,
    invitationLink,
    type Invitation,
    type InviteHistory,
} from "./invite-model";
import "./invite.css";

export default function Invites({
    view,
    onLogin,
}: {
    view: View;
    onLogin: () => void;
}) {
    const [data, setData] = useState<Invitation | null>(null);
    const [history, setHistory] = useState<InviteHistory | null>(null);
    const [loading, setLoading] = useState(false),
        [historyLoading, setHistoryLoading] = useState(false);
    const [busy, setBusy] = useState(false),
        [error, setError] = useState(""),
        [historyError, setHistoryError] = useState("");
    const [selected, setSelected] = useState(""),
        [qr, setQr] = useState(""),
        [qrFailed, setQrFailed] = useState(false);
    const [message, setMessage] = useState(""),
        [shareError, setShareError] = useState("");
    const generation = useRef(0),
        shareVersion = useRef(0),
        readVersion = useRef(0),
        historyVersion = useRef(0),
        changing = useRef(false);
    const request = <T,>(action: string, page?: number) =>
        command<T>("invite_request", {
            action,
            ...(page === undefined ? {} : { page }),
        });
    const code =
        data?.codes.find((item) => item.code === selected) || data?.codes[0];
    const link = code ? invitationLink(code.code) : "";

    async function load() {
        const run = generation.current,
            read = ++readVersion.current;
        setLoading(true);
        setError("");
        try {
            const next = await request<Invitation>("index");
            if (run === generation.current && read === readVersion.current)
                setData(next);
        } catch (e) {
            if (run === generation.current && read === readVersion.current) {
                setData(null);
                setError(errorText(e));
            }
        } finally {
            if (run === generation.current && read === readVersion.current)
                setLoading(false);
        }
    }
    async function loadHistory(page = 1) {
        const run = generation.current,
            read = ++historyVersion.current;
        setHistoryLoading(true);
        setHistoryError("");
        try {
            const next = await request<InviteHistory>("details", page);
            if (run === generation.current && read === historyVersion.current)
                setHistory(next);
        } catch (e) {
            if (run === generation.current && read === historyVersion.current) {
                setHistory(null);
                setHistoryError(errorText(e));
            }
        } finally {
            if (run === generation.current && read === historyVersion.current)
                setHistoryLoading(false);
        }
    }
    useEffect(() => {
        generation.current++;
        changing.current = false;
        setData(null);
        setHistory(null);
        setSelected("");
        setQr("");
        setBusy(false);
        setMessage("");
        setShareError("");
        setError("");
        setHistoryError("");
        if (view.logged_in) {
            void load();
            void loadHistory();
        }
        return () => {
            generation.current++;
        };
    }, [view.logged_in, view.profile?.email]);
    useEffect(() => {
        let cancelled = false;
        shareVersion.current++;
        setQrFailed(false);
        setQr("");
        setShareError("");
        setMessage("");
        if (link)
            void QRCode.toDataURL(link, { width: 220, margin: 2 }).then(
                (image) => {
                    if (!cancelled) setQr(image);
                },
                () => {
                    if (!cancelled) {
                        setQrFailed(true);
                        setShareError("二维码暂时无法生成，仍可复制邀请链接。");
                    }
                },
            );
        return () => {
            cancelled = true;
        };
    }, [link, view.logged_in, view.profile?.email]);

    async function generate() {
        if (changing.current || loading || !data?.rules.can_generate) return;
        const run = generation.current;
        changing.current = true;
        readVersion.current++;
        setBusy(true);
        setError("");
        setMessage("");
        try {
            const next = await request<Invitation>("generate");
            if (run !== generation.current) return;
            const created = next.codes.find(
                (item) => !data.codes.some((old) => old.code === item.code),
            );
            setData(next);
            if (created) setSelected(created.code);
        } catch (e) {
            if (run !== generation.current) return;
            // A timed-out write may have succeeded. Read back; never replay generation.
            await load();
            if (run === generation.current)
                setError(
                    `${errorText(e)}。请先查看已有邀请码，再决定是否重新生成。`,
                );
        } finally {
            if (run === generation.current) {
                changing.current = false;
                setBusy(false);
            }
        }
    }
    async function copy() {
        const run = generation.current;
        const share = shareVersion.current;
        try {
            await navigator.clipboard.writeText(link);
            if (run === generation.current && share === shareVersion.current) {
                setMessage("邀请链接已复制，可以发给朋友了。");
                setShareError("");
            }
        } catch {
            if (run === generation.current && share === shareVersion.current)
                setShareError("复制失败，请选中下方链接手动复制。");
        }
    }
    async function website() {
        const run = generation.current;
        try {
            await command("open_link", { target: "invite" });
        } catch (e) {
            if (run === generation.current) setShareError(errorText(e));
        }
    }

    return (
        <div className="invite-page">
            <header className="invite-heading">
                <div>
                    <p className="eyebrow">SHARE A LITTLE JOY</p>
                    <h2>邀请好友</h2>
                    <p>把卡皮巴拉分享给朋友，从一份邀请开始。</p>
                </div>
                <Users size={42} aria-hidden="true" />
            </header>
            {!view.logged_in ? (
                <section className="invite-panel invite-empty">
                    <Users size={36} />
                    <h3>登录后，获取你的专属邀请链接</h3>
                    <p>在这里查看邀请码、邀请人数和佣金记录。</p>
                    <button className="primary-button" onClick={onLogin}>
                        账号登录
                    </button>
                </section>
            ) : (
                <>
                    <div className="invite-toolbar">
                        <span>分享链接中的邀请码会在官网注册时自动填写。</span>
                        <button
                            className="secondary-button"
                            disabled={busy || loading || historyLoading}
                            onClick={() => {
                                void load();
                                void loadHistory();
                            }}
                        >
                            <RefreshCw size={16} />
                            刷新
                        </button>
                    </div>
                    {error && (
                        <p className="invite-error" role="alert">
                            {error}
                        </p>
                    )}
                    {loading && !data && <p role="status">正在读取邀请信息…</p>}
                    {data && (
                        <>
                            <section
                                className="invite-stats"
                                aria-label="邀请统计"
                            >
                                <article>
                                    <span>已邀请注册</span>
                                    <strong>
                                        {data.stats.registered}
                                        <small> 人</small>
                                    </strong>
                                </article>
                                <article>
                                    <span>累计佣金</span>
                                    <strong>
                                        {money(data.stats.total_commission)}
                                    </strong>
                                </article>
                                <article>
                                    <span>确认中佣金</span>
                                    <strong>
                                        {money(data.stats.pending_commission)}
                                    </strong>
                                </article>
                                <article>
                                    <span>可用佣金</span>
                                    <strong>
                                        {money(data.stats.available_commission)}
                                    </strong>
                                </article>
                            </section>
                            {!data.rules.registration_open && (
                                <p className="invite-notice" role="status">
                                    网站暂未开放注册，请等恢复后再邀请好友。
                                </p>
                            )}
                            <section className="invite-panel invite-share">
                                <div className="invite-share-main">
                                    <div className="invite-section-title">
                                        <h3>我的邀请链接</h3>
                                        <button
                                            className="secondary-button"
                                            disabled={
                                                busy ||
                                                loading ||
                                                !data.rules.can_generate
                                            }
                                            onClick={() => void generate()}
                                        >
                                            <Plus size={16} />
                                            {busy ? "正在生成…" : "生成邀请码"}
                                        </button>
                                    </div>
                                    <p>
                                        {data.rules.reusable
                                            ? "邀请码可重复使用，朋友通过链接注册即可建立邀请关系。"
                                            : "每个邀请码仅可成功注册一次，使用后请刷新并生成新码。"}
                                    </p>
                                    {code ? (
                                        <>
                                            <label className="invite-code-label">
                                                邀请码
                                                <select
                                                    value={code.code}
                                                    disabled={busy}
                                                    onChange={(e) =>
                                                        setSelected(
                                                            e.target.value,
                                                        )
                                                    }
                                                >
                                                    {data.codes.map((item) => (
                                                        <option
                                                            key={item.code}
                                                            value={item.code}
                                                        >
                                                            {item.code}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                            <p className="invite-meta">
                                                创建于{" "}
                                                {invitationDate(
                                                    code.created_at,
                                                )}{" "}
                                                · 访问 {code.visits} 次
                                            </p>
                                            <input
                                                className="invite-link"
                                                aria-label="邀请链接"
                                                readOnly
                                                value={link}
                                                onFocus={(e) =>
                                                    e.currentTarget.select()
                                                }
                                            />
                                            <button
                                                className="primary-button"
                                                disabled={
                                                    !data.rules
                                                        .registration_open ||
                                                    busy
                                                }
                                                onClick={() => void copy()}
                                            >
                                                <Copy size={17} />
                                                复制邀请链接
                                            </button>
                                        </>
                                    ) : (
                                        <p className="invite-empty-code">
                                            {data.rules.can_generate
                                                ? "还没有可用的邀请码，点击“生成邀请码”开始邀请。"
                                                : "暂无可用的邀请码。网站恢复注册或开放生成额度后，可在这里获取。"}
                                        </p>
                                    )}
                                    {message && (
                                        <p
                                            className="invite-success"
                                            role="status"
                                        >
                                            {message}
                                        </p>
                                    )}
                                    {shareError && (
                                        <p
                                            className="invite-error"
                                            role="alert"
                                        >
                                            {shareError}
                                        </p>
                                    )}
                                    <p className="invite-meta">
                                        可用邀请码 {data.codes.length} /{" "}
                                        {data.rules.generation_limit}
                                        {!data.rules.can_generate &&
                                        data.rules.registration_open
                                            ? " · 已达上限，请使用已有邀请码"
                                            : ""}
                                    </p>
                                </div>
                                {code && (
                                    <figure className="invite-qr">
                                        {qr ? (
                                            <img
                                                src={qr}
                                                alt="邀请注册链接二维码"
                                                width="220"
                                                height="220"
                                            />
                                        ) : (
                                            <span>
                                                {qrFailed
                                                    ? "二维码暂不可用"
                                                    : "二维码加载中…"}
                                            </span>
                                        )}
                                        <figcaption>
                                            朋友扫码即可前往官网注册
                                        </figcaption>
                                    </figure>
                                )}
                            </section>
                            <section className="invite-panel invite-rules">
                                <div>
                                    <h3>邀请奖励</h3>
                                    <p>
                                        {data.rules.commission_rates.length ===
                                        1
                                            ? `佣金比例 ${data.rules.commission_rates[0]}%`
                                            : `分级佣金比例 ${data.rules.commission_rates.map((rate, i) => `${i + 1}级 ${rate}%`).join(" · ")}`}
                                    </p>
                                    <p>
                                        奖励以实际订单与审核结算为准。提现和余额划转可前往官网邀请中心办理。
                                    </p>
                                </div>
                                <button
                                    className="secondary-button"
                                    onClick={() => void website()}
                                >
                                    官网邀请中心
                                    <ArrowUpRight size={16} />
                                </button>
                            </section>
                        </>
                    )}
                    <section className="invite-panel invite-history">
                        <h3>佣金明细</h3>
                        {historyLoading ? (
                            <p role="status">正在读取佣金明细…</p>
                        ) : historyError ? (
                            <div>
                                <p role="alert" className="invite-error">
                                    {historyError}
                                </p>
                                <button
                                    className="secondary-button"
                                    onClick={() => void loadHistory()}
                                >
                                    重试明细
                                </button>
                            </div>
                        ) : (
                            history && (
                                <>
                                    {!history.items.length ? (
                                        <p>
                                            暂无佣金记录。朋友通过邀请注册并产生有效订单后，已结算记录会显示在这里。
                                        </p>
                                    ) : (
                                        <div className="invite-table-wrap">
                                            <table>
                                                <thead>
                                                    <tr>
                                                        <th>发放时间</th>
                                                        <th>订单金额</th>
                                                        <th>佣金</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {history.items.map(
                                                        (item) => (
                                                            <tr key={item.id}>
                                                                <td>
                                                                    {invitationDate(
                                                                        item.created_at,
                                                                    )}
                                                                </td>
                                                                <td>
                                                                    {money(
                                                                        item.order_amount,
                                                                    )}
                                                                </td>
                                                                <td>
                                                                    {money(
                                                                        item.commission,
                                                                    )}
                                                                </td>
                                                            </tr>
                                                        ),
                                                    )}
                                                </tbody>
                                            </table>
                                        </div>
                                    )}
                                    {history.total > history.page_size && (
                                        <nav
                                            className="invite-pagination"
                                            aria-label="佣金明细分页"
                                        >
                                            <button
                                                className="secondary-button"
                                                disabled={history.page <= 1}
                                                onClick={() =>
                                                    void loadHistory(
                                                        history.page - 1,
                                                    )
                                                }
                                            >
                                                上一页
                                            </button>
                                            <span>
                                                第 {history.page} /{" "}
                                                {Math.ceil(
                                                    history.total /
                                                        history.page_size,
                                                )}{" "}
                                                页
                                            </span>
                                            <button
                                                className="secondary-button"
                                                disabled={
                                                    history.page *
                                                        history.page_size >=
                                                    history.total
                                                }
                                                onClick={() =>
                                                    void loadHistory(
                                                        history.page + 1,
                                                    )
                                                }
                                            >
                                                下一页
                                            </button>
                                        </nav>
                                    )}
                                </>
                            )
                        )}
                    </section>
                </>
            )}
        </div>
    );
}
