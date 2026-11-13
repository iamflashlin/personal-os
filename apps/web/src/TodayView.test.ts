import { describe, expect, it } from "vitest";
import type { EntrySummary, TodayEntry } from "./api";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { origin, quietLine, rowTag, summaryBadges, TodayRow } from "./TodayView";

const base: EntrySummary = {
  status: "ok",
  gist: "x",
  action_needed: false,
  action: "",
  deadline_text: "",
};

describe("今日 badges", () => {
  it("never marks low-value mail 重要, whatever its importance", () => {
    expect(summaryBadges({ ...base, low_value: true, importance: "high" })).toEqual(["次要"]);
  });

  it("marks low importance 次要 as the 邮件 page does", () => {
    expect(summaryBadges({ ...base, low_value: false, importance: "low" })).toEqual(["次要"]);
    expect(summaryBadges({ ...base, low_value: false, importance: "high" })).toEqual(["重要"]);
    expect(summaryBadges({ ...base, low_value: false, importance: "normal" })).toEqual([]);
  });

  it("shows nothing for a mail without a finished summary", () => {
    expect(summaryBadges(null)).toEqual([]);
    expect(summaryBadges({ ...base, status: "pending", importance: "high" })).toEqual([]);
  });
});

describe("今日 rows", () => {
  const entry: TodayEntry = {
    kind: "assignment",
    title: "Quiz",
    at: null,
    all_day: false,
    source: "Canvas",
    note: "F26 MATH D001A 49 Calculus I",
    url: "",
    badge: "缺交",
    ref: "1",
  };

  it("names the course shortly, or the sender when there is no course", () => {
    expect(origin(entry)).toBe("MATH 1A");
    expect(origin({ note: "F26 ECON C2002 Prin Macroeconomics 03Y", source: "邮箱" })).toBe("ECON 2002");
    expect(origin({ note: "Edfinity", source: "邮箱" })).toBe("Edfinity");
    expect(origin({ note: "", source: "日历" })).toBe("日历");
  });

  it("gives a row one tag at most, and none that its section already says", () => {
    expect(rowTag({ ...entry, badge: "已提交" }, "other", "今天截止")).toBe("已提交");
    expect(rowTag(entry, "other", "缺交 / 逾期")).toBe("");
    expect(rowTag({ ...entry, badge: "进行中" }, "other", "进行中")).toBe("");
    const mail = { ...entry, badge: "未读", summary: { ...base, importance: "high" as const } };
    expect(rowTag(mail, "mail", "未读邮件")).toBe("重要"); // not 未读
    expect(rowTag(mail, "action", "邮件里要你做的")).toBe("");
    expect(rowTag({ ...mail, summary: null }, "mail", "未读邮件")).toBe("");
  });

  it("keeps a mail's deadline even when it asks for nothing", () => {
    expect(quietLine({ ...base, deadline_text: "周五" })).toBe("截止 周五");
    const both = { ...base, action_needed: true, action: "交作业", deadline_text: "周五" };
    expect(quietLine(both)).toBe("交作业，截止 周五");
    expect(quietLine({ ...base, status: "pending", deadline_text: "周五" })).toBe("");
    expect(quietLine(null)).toBe("");
  });

  it("renders mail text as text, never as HTML", () => {
    const evil = {
      ...entry,
      title: '<script>alert("x")</script>',
      summary: { ...base, action_needed: true, action: "<img src=x onerror=1>" },
    };
    const html = renderToStaticMarkup(
      createElement(TodayRow, { entry: evil, withDay: false, section: "mail", title: "未读邮件" }),
    );
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
  });
});
