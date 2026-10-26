import type { NoticePage, SystemNotice } from "./notice-model";
export async function noticePreview(
    mode: string,
    page: number,
): Promise<NoticePage> {
    await new Promise((resolve) => setTimeout(resolve, 180));
    if (mode === "notices-error")
        throw { message: "暂时无法同步系统通知，请检查网络后刷新" };
    const items: SystemNotice[] =
        mode === "notices-empty"
            ? []
            : [
                  {
                      id: 1,
                      title: "卡皮巴拉系统通知，现在与你同步",
                      content:
                          "## 每一次更新，都在这里\n\n官网发布的系统公告会同步到客户端，无需切换窗口。\n\n- 点击通知可以查看详情\n- 阅读后，未读标记会自动消除\n- 通知内容更新后，会再次提醒你\n\n[访问官网](https://taige.us/)",
                      published_at: "2026-10-26T04:00:00Z",
                      level: "info",
                      image_url: null,
                      fingerprint: "a".repeat(64),
                  },
                  {
                      id: 2,
                      title: "线路维护安排",
                      content:
                          "<p>为了提供更稳定的连接，我们将按计划进行线路维护。</p><p>维护期间可以从首页选择其他节点。<strong>感谢你的理解。</strong></p>",
                      published_at: "2026-10-25T12:00:00Z",
                      level: "critical",
                      image_url: null,
                      fingerprint: "b".repeat(64),
                  },
                  {
                      id: 3,
                      title: "邀请朋友，一起轻松出发",
                      content:
                          "打开侧栏的 **邀请好友**，复制自己的邀请链接。\n\n邀请奖励按官网当前规则计算。",
                      published_at: "2026-10-24T10:00:00Z",
                      level: "success",
                      image_url: null,
                      fingerprint: "c".repeat(64),
                  },
              ];
    return {
        items: page === 1 ? items : [],
        page,
        page_size: 20,
        total: items.length,
    };
}
