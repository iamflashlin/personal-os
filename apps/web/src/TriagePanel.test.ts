import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { type TriageView, createApi } from "./api";
import { groupHint, TriagePanel } from "./TriagePanel";

const view: TriageView = {
  open_count: 7,
  unread_count: 8,
  unsummarised: 0,
  groups: [
    { key: "due_soon", kind: "due_soon", label: "马上要做", count: 1, item_ids: ["a"], rule: null, rule_description: "" },
    {
      key: "sender:joinhandshake.com",
      kind: "sender",
      label: "joinhandshake.com 的推送",
      count: 6,
      item_ids: ["b", "c", "d", "e", "f", "g"],
      rule: { all_of: [] },
      rule_description: "发件域名是「joinhandshake.com」并且次要邮件",
    },
  ],
  handled: [],
  recent: [
    {
      id: "B1",
      kind: "group",
      status: "applied",
      label: "成绩通知",
      description: "标记 2 封为已处理",
      count: 2,
      item_ids: ["x", "y"],
      rule_id: null,
      applied_at: null,
      undone_at: null,
      version: 1,
    },
  ],
  rules: [],
};

describe("TriagePanel", () => {
  it("shows the open count and the undo for the last batch", () => {
    const html = renderToStaticMarkup(
      createElement(TriagePanel, {
        view,
        titles: new Map(),
        busy: false,
        onHandle: () => {},
        onUndo: () => {},
        onRule: () => {},
      }),
    );
    expect(html).toContain("未处理 7 封");
    expect(html).toContain("撤销「成绩通知」（2 封）");
    expect(html).toContain("帮我整理");
  });

  it("hints what to do with the groups that ask something", () => {
    expect(groupHint(view.groups[0])).toContain("先处理");
    expect(groupHint(view.groups[1])).toBe("");
  });
});

describe("triage api", () => {
  it("sends the group key and save_rule with the ids", async () => {
    const sent: unknown[] = [];
    const api = createApi(async (_path, init) => {
      sent.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({}), { status: 200 });
    });
    await api.handleMail(["b", "c"], "sender:joinhandshake.com", true);
    await api.setMailHandled("b", false);
    expect(sent).toEqual([
      { item_ids: ["b", "c"], group_key: "sender:joinhandshake.com", save_rule: true },
      { handled: false },
    ]);
  });
});
