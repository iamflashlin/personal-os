import { describe, expect, it } from "vitest";
import type { EntrySummary } from "./api";
import { summaryBadges } from "./TodayView";

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
