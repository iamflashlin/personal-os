import { describe, expect, it } from "vitest";
import { type AgendaEntry } from "./api";
import { planRows } from "./TodayPlan";

const at = (h: number, m = 0) => new Date(2026, 10, 23, h, m).toISOString();

function entry(over: Partial<AgendaEntry>): AgendaEntry {
  return {
    key: over.title ?? "k",
    title: "Class",
    kind: "class",
    starts_at: at(9),
    ends_at: at(10),
    all_day: false,
    location: "",
    source: "manual",
    event_id: null,
    url: "",
    blocks: true,
    conflict: false,
    repeats: false,
    ...over,
  };
}

describe("planRows", () => {
  const entries = [
    entry({ title: "ENGL 上课", starts_at: at(9), ends_at: at(10, 15) }),
    entry({ title: "写作业：Essay 2", kind: "task", starts_at: at(13), ends_at: at(14) }),
    entry({ title: "Journal", kind: "deadline", source: "canvas", starts_at: at(23, 59), ends_at: null, location: "F26 ENGL C1000 Reading", blocks: false }),
    entry({ title: "Holiday", kind: "calendar", source: "calendar", all_day: true, starts_at: at(0), ends_at: at(23, 59) }),
    entry({ title: "MATH 上课", starts_at: at(15), ends_at: at(16) }),
  ];
  const free = [{ starts_at: at(10, 15), ends_at: at(13), minutes: 165 }];

  it("lists all-day first, then everything in time order, free time included", () => {
    const rows = planRows(entries, free, new Date(2026, 10, 23, 9, 30).getTime());
    expect(rows.map((r) => r.title)).toEqual([
      "Holiday",
      "ENGL 上课",
      "空闲 2 小时 45 分",
      "写作业：Essay 2",
      "MATH 上课",
      "Journal",
    ]);
  });

  it("marks what is on now and the next thing to go to (never a free slot)", () => {
    const rows = planRows(entries, free, new Date(2026, 10, 23, 9, 30).getTime());
    const state = Object.fromEntries(rows.map((r) => [r.title, r.state]));
    expect(state["ENGL 上课"]).toBe("now");
    expect(state["写作业：Essay 2"]).toBe("next");
    expect(state["空闲 2 小时 45 分"]).toBe("later");
    expect(state["Holiday"]).toBe("later");
  });

  it("names homework blocks and Canvas courses on the right", () => {
    const rows = planRows(entries, free, new Date(2026, 10, 23, 8).getTime());
    const sideOf = Object.fromEntries(rows.map((r) => [r.title, r.side]));
    expect(sideOf["写作业：Essay 2"]).toBe("写作业");
    expect(sideOf["ENGL 上课"]).toBe("上课");
    expect(sideOf["Journal"]).toBe("ENGL 1000");
  });

  it("passes what is over, and a deadline once it has gone by", () => {
    const evening = new Date(2026, 10, 23, 23, 59, 30).getTime();
    const rows = planRows(entries, [], evening);
    expect(rows.filter((r) => r.state === "past").map((r) => r.title)).toEqual([
      "ENGL 上课",
      "写作业：Essay 2",
      "MATH 上课",
      "Journal",
    ]);
    expect(rows.some((r) => r.state === "next")).toBe(false);
  });
});
