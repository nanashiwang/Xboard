import type { Invitation, InviteHistory } from "./invite-model";
let data: Invitation = {
    codes: [{ code: "CAPY2026", created_at: 1792886400, visits: 32 }],
    stats: {
        registered: 12,
        total_commission: 12850,
        pending_commission: 1800,
        available_commission: 6850,
    },
    rules: {
        generation_limit: 5,
        can_generate: true,
        registration_open: true,
        reusable: true,
        commission_rates: [10],
    },
};
export function invitePreview(
    mode: string,
    action: string,
    page = 1,
): Invitation | InviteHistory {
    if (mode === "invite-error")
        throw new Error("邀请信息暂时无法读取，请稍后刷新。");
    if (action === "details")
        return {
            items:
                mode === "invite-empty"
                    ? []
                    : [
                          {
                              id: page,
                              order_amount: 10000,
                              commission: 1000,
                              created_at: 1792886400,
                          },
                      ],
            total: mode === "invite-empty" ? 0 : 12,
            page,
            page_size: 10,
        };
    if (mode === "invite-empty" && action === "index")
        return {
            ...data,
            codes: [],
            stats: {
                registered: 0,
                total_commission: 0,
                pending_commission: 0,
                available_commission: 0,
            },
        };
    if (action === "generate") {
        data = {
            ...data,
            codes: [
                ...data.codes,
                {
                    code: `CAPY00${data.codes.length}`,
                    created_at: Math.floor(Date.now() / 1000),
                    visits: 0,
                },
            ],
            rules: { ...data.rules, can_generate: data.codes.length + 1 < 5 },
        };
    }
    if (mode === "invite-closed")
        return {
            ...data,
            rules: {
                ...data.rules,
                registration_open: false,
                can_generate: false,
                reusable: false,
            },
        };
    return structuredClone(data);
}
