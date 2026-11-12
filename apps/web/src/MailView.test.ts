import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { EmailSummary, SyncedItem } from "./api";
import { countMail, filterMail, MailDetail, MailLine, type MailRow, mailTitle } from "./MailView";

function item(id: string, title: string, body = "原文内容"): SyncedItem {
  return {
    id,
    integration_id: "i",
    item_type: "email_message",
    external_id: id,
    title,
    body,
    location: "",
    url: "",
    starts_at: "2026-11-11T08:00:00Z",
    ends_at: null,
    all_day: false,
    data: { from_name: "Teacher", seen: false },
    created_at: "2026-11-11T08:00:00Z",
    updated_at: "2026-11-11T08:00:00Z",
    version: 1,
  } as SyncedItem;
}

function summary(over: Partial<EmailSummary> = {}): EmailSummary {
  return {
    id: "s",
    item_id: "a",
    status: "ok",
    gist: "CIS22A 实验5 周五截止",
    points: ["在 Canvas 提交 PDF", "迟交扣 10%"],
    low_value: false,
    importance: "high",
    action_needed: true,
    action: "提交实验5",
    deadline_text: "周五 23:59",
    deadline_date: "2026-11-13",
    error: "",
    prompt_version: 2,
    ...over,
  };
}

describe("邮件 page", () => {
  it("shows the AI title, never the subject, once a mail is summarised", () => {
    const row: MailRow = {
      item: item("a", "Re: [CIS 22A] Reminder: Lab 5 submission window closes Friday"),
      source: "163",
      summary: summary(),
    };
    expect(mailTitle(row)).toBe("CIS22A 实验5 周五截止");
    const html = renderToStaticMarkup(createElement(MailLine, { row }));
    expect(html).toContain("CIS22A 实验5 周五截止");
    expect(html).toContain("重要");
    expect(html).not.toContain("Reminder: Lab 5"); // closed: the subject is not shown
  });

  it("falls back to the subject while a mail has no summary", () => {
    expect(mailTitle({ item: item("b", "Lab 6"), source: "163" })).toBe("Lab 6");
    expect(mailTitle({ item: item("c", ""), source: "163" })).toBe("（无主题）");
    const skipped = { item: item("d", "验证码"), source: "163", summary: summary({ status: "skipped_sensitive", gist: "" }) };
    expect(mailTitle(skipped)).toBe("验证码");
    expect(renderToStaticMarkup(createElement(MailLine, { row: skipped }))).toContain("未发送给 AI");
  });

  it("lists low-value mail like any other, only marked 次要", () => {
    const row: MailRow = {
      item: item("b", "Sale"),
      source: "163",
      summary: summary({ low_value: true, importance: "normal", gist: "商店促销 无需处理" }),
    };
    const html = renderToStaticMarkup(createElement(MailLine, { row }));
    expect(html).toContain("商店促销 无需处理");
    expect(html).toContain("次要");
    expect(html).not.toContain("重要");
  });

  it("renders mail text as text, never as HTML", () => {
    const row: MailRow = {
      item: item("a", "x", "<img src=x onerror=alert(1)>"),
      source: "163",
      summary: summary({ gist: "<script>bad()</script>", points: ["<b>p</b>"] }),
    };
    const html = renderToStaticMarkup(createElement(MailLine, { row, initiallyOpen: true }));
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<b>p</b>");
  });

  it("opens with the points first, then what to do, then the original", () => {
    const row: MailRow = { item: item("a", "Subject", "完整原文在这里"), source: "163", summary: summary() };
    const html = renderToStaticMarkup(createElement(MailDetail, { row }));
    const points = html.indexOf("在 Canvas 提交 PDF");
    const todo = html.indexOf("要做：");
    const original = html.indexOf("原文 ·");
    expect(points).toBeGreaterThan(-1);
    expect(points).toBeLessThan(todo);
    expect(todo).toBeLessThan(original);
    expect(html).toContain("完整原文在这里");
  });

  it("never shows an older prompt's long sentence as the title", () => {
    const old = summary({ gist: "这是一封很长很长的旧版本摘要句子，超过二十个字的那种", prompt_version: 1 });
    expect(mailTitle({ item: item("a", "Lab 5"), source: "163", summary: old })).toBe("Lab 5");
  });

  it("filters all, unread and needs-action, newest first kept", () => {
    const read = (id: string) => ({ ...item(id, id), data: { seen: true } });
    const rows: MailRow[] = [
      { item: item("a", "A"), source: "163", summary: summary({ action_needed: true }) },
      { item: read("b"), source: "163", summary: summary({ action_needed: true }) },
      { item: item("c", "C"), source: "163", summary: summary({ action_needed: true, low_value: true }) },
      { item: read("d"), source: "163" },
    ];
    expect(filterMail(rows, "all").map((r) => r.item.id)).toEqual(["a", "b", "c", "d"]);
    expect(filterMail(rows, "unread").map((r) => r.item.id)).toEqual(["a", "c"]);
    expect(filterMail(rows, "action").map((r) => r.item.id)).toEqual(["a", "b"]);
    expect(countMail(rows)).toEqual({ all: 4, unread: 2, action: 2 });
  });
});
