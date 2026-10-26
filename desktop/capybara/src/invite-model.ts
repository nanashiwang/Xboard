export type Invitation = {
    codes: { code: string; created_at: number; visits: number }[];
    stats: {
        registered: number;
        total_commission: number;
        pending_commission: number;
        available_commission: number;
    };
    rules: {
        generation_limit: number;
        can_generate: boolean;
        registration_open: boolean;
        reusable: boolean;
        commission_rates: number[];
    };
};
export type InviteHistory = {
    items: {
        id: number;
        order_amount: number;
        commission: number;
        created_at: number;
    }[];
    total: number;
    page: number;
    page_size: number;
};
export const invitationLink = (code: string) =>
    `https://taige.us/#/register?code=${encodeURIComponent(code)}`;
export const invitationDate = (timestamp: number) =>
    new Date(timestamp * 1000).toLocaleDateString("zh-CN");
