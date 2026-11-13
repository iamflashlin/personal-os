import { describe, expect, it } from "vitest";
import type { EntrySummary, TodayEntry } from "./api";
import { origin, rowTag, summaryBadges } from "./TodayView";

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
    expect(rowTag(entry, "other")).toBe("缺交");
    const mail = { ...entry, badge: "未读", summary: { ...base, importance: "high" as const } };
    expect(rowTag(mail, "mail")).toBe("重要"); // not 未读: the section is 未读邮件
    expect(rowTag(mail, "action")).toBe("");
    expect(rowTag({ ...mail, summary: null }, "mail")).toBe("");
  });
});
