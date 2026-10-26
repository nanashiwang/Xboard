import DOMPurify from "dompurify";
import { marked } from "marked";

export type SystemNotice = {
    id: number;
    title: string;
    content: string;
    level: string;
    image_url: string | null;
    published_at: string | null;
    fingerprint: string;
};
export type NoticePage = {
    items: SystemNotice[];
    page: number;
    page_size: number;
    total: number;
};
export type ReadMarks = Record<string, string>;
export const readKey = "capybara-notices-read-v1";
export function loadReadMarks(): ReadMarks {
    try {
        const value: unknown = JSON.parse(
            localStorage.getItem(readKey) || "{}",
        );
        if (!value || typeof value !== "object" || Array.isArray(value))
            return {};
        return Object.fromEntries(
            Object.entries(value)
                .filter(
                    ([id, fingerprint]) =>
                        /^\d+$/.test(id) &&
                        typeof fingerprint === "string" &&
                        /^[a-f0-9]{64}$/.test(fingerprint),
                )
                .slice(-1000),
        );
    } catch {
        return {};
    }
}
export function markNotices(
    marks: ReadMarks,
    items: SystemNotice[],
): ReadMarks {
    return Object.fromEntries(
        Object.entries({
            ...marks,
            ...Object.fromEntries(items.map((n) => [n.id, n.fingerprint])),
        }).slice(-1000),
    );
}
export function noticeLink(value: string): string | null {
    try {
        if (value.length > 4096 || /[\s\u0000-\u001f\u007f]/.test(value))
            return null;
        const url = new URL(value, "https://taige.us/");
        return ["https:", "http:"].includes(url.protocol) &&
            !url.username &&
            !url.password
            ? url.href
            : null;
    } catch {
        return null;
    }
}
export function noticeHtml(content: string): string {
    return DOMPurify.sanitize(
        marked.parse(content, { async: false, breaks: true }),
        {
            ALLOWED_TAGS: [
                "p",
                "br",
                "strong",
                "em",
                "b",
                "i",
                "s",
                "u",
                "ul",
                "ol",
                "li",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "blockquote",
                "pre",
                "code",
                "hr",
                "a",
                "table",
                "thead",
                "tbody",
                "tr",
                "th",
                "td",
            ],
            ALLOWED_ATTR: ["href", "title"],
            ALLOW_DATA_ATTR: false,
            ALLOW_ARIA_ATTR: false,
        },
    );
}
