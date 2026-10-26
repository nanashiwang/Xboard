import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    Bell,
    CheckCheck,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    ExternalLink,
    RefreshCw,
    X,
} from "lucide-react";
import { command, errorText, native, preview } from "./bridge";
import { date } from "./model";
import {
    loadReadMarks,
    markNotices,
    noticeHtml,
    noticeLink,
    readKey,
    type NoticePage,
    type SystemNotice,
} from "./notice-model";
import "./notices.css";

function NoticeBody({
    notice,
    onLink,
}: {
    notice: SystemNotice;
    onLink: (url: string) => void;
}) {
    const html = useMemo(() => noticeHtml(notice.content), [notice.content]);
    return (
        <div
            className="notice-body"
            onClick={(e) => {
                const link = (e.target as Element).closest("a");
                if (link) {
                    e.preventDefault();
                    const href = link.getAttribute("href");
                    const url = href ? noticeLink(href) : null;
                    if (url) onLink(url);
                }
            }}
            onAuxClick={(e) => e.preventDefault()}
            dangerouslySetInnerHTML={{ __html: html }}
        />
    );
}
export default function Notifications() {
    const [open, setOpen] = useState(false);
    const [page, setPage] = useState(1);
    const [data, setData] = useState<NoticePage | null>(null);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [readError, setReadError] = useState("");
    const [marks, setMarks] = useState(loadReadMarks);
    const [expanded, setExpanded] = useState<number | null>(null);
    const dialog = useRef<HTMLDialogElement>(null);
    const mounted = useRef(false),
        sequence = useRef(0),
        pending = useRef(false);
    const available = native || !!preview;
    const refresh = useCallback(
        async (force = false) => {
            if (!available || (pending.current && !force)) return;
            const ticket = ++sequence.current;
            pending.current = true;
            setLoading(true);
            setError("");
            try {
                const next = await command<NoticePage>("fetch_notices", {
                    page,
                });
                if (mounted.current && ticket === sequence.current) {
                    setData(next);
                    setExpanded((id) =>
                        next.items.some((n) => n.id === id) ? id : null,
                    );
                }
            } catch (e) {
                if (mounted.current && ticket === sequence.current)
                    setError(errorText(e));
            } finally {
                if (mounted.current && ticket === sequence.current) {
                    pending.current = false;
                    setLoading(false);
                }
            }
        },
        [available, page],
    );
    useEffect(() => {
        mounted.current = true;
        void refresh(true);
        const timer = setInterval(() => void refresh(), 5 * 60_000);
        const focus = () => void refresh();
        window.addEventListener("focus", focus);
        return () => {
            mounted.current = false;
            sequence.current++;
            pending.current = false;
            clearInterval(timer);
            window.removeEventListener("focus", focus);
        };
    }, [refresh]);
    useEffect(() => {
        if (open) dialog.current?.showModal();
        else dialog.current?.close();
    }, [open]);
    const read = (items: SystemNotice[]) => {
        const next = markNotices(marks, items);
        setMarks(next);
        try {
            localStorage.setItem(readKey, JSON.stringify(next));
            setReadError("");
        } catch {
            setReadError("已读状态暂时无法保存，重启后可能再次提醒。");
        }
    };
    const follow = async (url: string) => {
        try {
            await command("open_notice_link", { url });
        } catch (e) {
            setError(errorText(e));
        }
    };
    const close = () => {
        setOpen(false);
        setPage(1);
        setExpanded(null);
    };
    const items = data?.page === page ? data.items : [];
    const unread = items.filter((n) => marks[n.id] !== n.fingerprint);
    const pages = Math.max(1, Math.ceil((data?.total || 0) / 20));
    return (
        <>
            <button
                className="notification-bell icon-button"
                aria-label="系统通知"
                title={unread.length ? "系统通知 · 有未读通知" : "系统通知"}
                aria-haspopup="dialog"
                onClick={() => {
                    setOpen(true);
                    void refresh();
                }}
            >
                <Bell size={19} />
                {unread.length > 0 && (
                    <span
                        className="notification-dot"
                        aria-label="有未读通知"
                    />
                )}
            </button>
            <dialog
                className="notifications-dialog"
                ref={dialog}
                aria-labelledby="notifications-title"
                onCancel={(e) => {
                    e.preventDefault();
                    close();
                }}
                onClick={(e) => {
                    if (e.target === e.currentTarget) close();
                }}
            >
                <div className="notifications-panel">
                    <header className="notifications-heading">
                        <span className="notifications-symbol">
                            <Bell size={24} />
                        </span>
                        <div>
                            <span className="eyebrow">STAY IN THE KNOW</span>
                            <h2 id="notifications-title">系统通知</h2>
                            <p>官网公告，随时查看。</p>
                        </div>
                        <button
                            className="icon-button"
                            aria-label="关闭系统通知"
                            onClick={close}
                        >
                            <X size={21} />
                        </button>
                    </header>
                    <div className="notifications-toolbar">
                        <span>
                            {data ? `共 ${data.total} 条通知` : "同步官网通知"}
                        </span>
                        <button
                            disabled={!unread.length || loading}
                            onClick={() => read(items)}
                        >
                            <CheckCheck size={16} />
                            本页已读
                        </button>
                        <button
                            aria-label="刷新系统通知"
                            disabled={!available || loading}
                            onClick={() => void refresh()}
                        >
                            <RefreshCw
                                size={16}
                                className={loading ? "spin" : ""}
                            />
                            刷新
                        </button>
                    </div>
                    <div className="notifications-scroll" aria-busy={loading}>
                        {error && (
                            <div className="notifications-error" role="alert">
                                {error}
                                {items.length > 0 &&
                                    "；当前显示上次同步的内容。"}
                            </div>
                        )}
                        {readError && (
                            <p className="notifications-error" role="status">
                                {readError}
                            </p>
                        )}
                        {!available && (
                            <p className="notifications-empty">
                                请在卡皮巴拉客户端查看系统通知。
                            </p>
                        )}
                        {available && loading && !items.length && (
                            <p className="notifications-empty" role="status">
                                正在同步通知…
                            </p>
                        )}
                        {available &&
                            !loading &&
                            !error &&
                            data &&
                            !items.length && (
                                <div className="notifications-empty">
                                    <Bell size={36} />
                                    <h3>暂时没有系统通知</h3>
                                    <p>有新公告时，会在这里与你见面。</p>
                                </div>
                            )}
                        {items.map((notice) => {
                            const isRead =
                                marks[notice.id] === notice.fingerprint;
                            const active = expanded === notice.id;
                            return (
                                <article
                                    className={
                                        "notice-card" +
                                        (active ? " expanded" : "")
                                    }
                                    key={notice.id}
                                >
                                    <button
                                        className="notice-summary"
                                        aria-expanded={active}
                                        aria-controls={`notice-${notice.id}`}
                                        onClick={() => {
                                            setExpanded(
                                                active ? null : notice.id,
                                            );
                                            if (!active) read([notice]);
                                        }}
                                    >
                                        <span
                                            className={
                                                "notice-read-dot" +
                                                (isRead ? " read" : "")
                                            }
                                        />
                                        <span className="notice-caption">
                                            <span className="notice-meta">
                                                <time
                                                    dateTime={
                                                        notice.published_at ||
                                                        undefined
                                                    }
                                                >
                                                    {date(notice.published_at)}
                                                </time>
                                                {!isRead && <b>未读</b>}
                                                {notice.level ===
                                                    "critical" && (
                                                    <b>重要通知</b>
                                                )}
                                            </span>
                                            <strong>{notice.title}</strong>
                                        </span>
                                        <ChevronDown
                                            size={18}
                                            className={active ? "turned" : ""}
                                        />
                                    </button>
                                    {active && (
                                        <section
                                            id={`notice-${notice.id}`}
                                            className="notice-detail"
                                        >
                                            <NoticeBody
                                                notice={notice}
                                                onLink={(url) =>
                                                    void follow(url)
                                                }
                                            />
                                            {notice.image_url &&
                                                noticeLink(
                                                    notice.image_url,
                                                ) && (
                                                    <button
                                                        className="notice-image-link"
                                                        onClick={() =>
                                                            void follow(
                                                                noticeLink(
                                                                    notice.image_url!,
                                                                )!,
                                                            )
                                                        }
                                                    >
                                                        <ExternalLink
                                                            size={15}
                                                        />
                                                        查看公告图片
                                                    </button>
                                                )}
                                        </section>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                    <footer className="notifications-footer">
                        <span>已读状态保存在本机</span>
                        <div>
                            <button
                                aria-label="上一页通知"
                                disabled={page <= 1 || loading}
                                onClick={() => {
                                    setExpanded(null);
                                    setPage(page - 1);
                                }}
                            >
                                <ChevronLeft size={18} />
                            </button>
                            <span>
                                {page} / {pages}
                            </span>
                            <button
                                aria-label="下一页通知"
                                disabled={page >= pages || loading}
                                onClick={() => {
                                    setExpanded(null);
                                    setPage(page + 1);
                                }}
                            >
                                <ChevronRight size={18} />
                            </button>
                        </div>
                    </footer>
                </div>
            </dialog>
        </>
    );
}
