import { describe, expect, it, vi } from "vitest";
import { type ActionRun, ApiError, type HomeworkBoard, type HomeworkItem, type Job } from "./api";
import { attention, blockText, courseOf, firstThing, weekLabel, weekText, dueText, openText, reminderText, waitForJobs } from "./HomeworkView";
import { pollUntil } from "./poll";

const NOW = Date.parse("2026-11-22T10:00:00Z");
const H = 3_600_000;

function item(over: Partial<HomeworkItem> = {}): HomeworkItem {
  return {
    id: "i1",
    title: "Journal 4",
    course: "F26 ENGL C1000 Reading",
    course_code: "ENGL C1000",
    due_at: new Date(NOW + 3 * H).toISOString(),
    url: "https://c/1",
    points: 10,
    state: "soon",
    submitted_at: null,
    late: false,
    ...over,
  };
}

function board(over: Partial<HomeworkBoard> = {}): HomeworkBoard {
  return {
    generated_at: new Date(NOW).toISOString(),
    canvas: true,
    synced_at: "2026-11-22T09:00:00Z",
    reminder: null,
    missing: [],
    soon: [],
    week: [],
    submitted: [],
    ...over,
  };
}

function run(status: ActionRun["status"], message = ""): ActionRun {
  return { id: "a1", status, message };
}

describe("blockText", () => {
  it("says the day and the hours of a planned block", () => {
    const text = blockText({ starts_at: "2026-11-24T19:00:00", ends_at: "2026-11-24T20:00:00" });
    expect(text).toBe("周二 11/24 19:00–20:00");
  });
});

describe("dueText", () => {
  it("says how long is left, or how long ago it was due", () => {
    expect(dueText(new Date(NOW + 40 * 60_000).toISOString(), NOW)).toBe("还剩 40 分钟");
    expect(dueText(new Date(NOW + 3.5 * H).toISOString(), NOW)).toBe("还剩 3 小时");
    expect(dueText(new Date(NOW + 50 * H).toISOString(), NOW)).toBe("还剩 2 天");
    expect(dueText(new Date(NOW - 30 * H).toISOString(), NOW)).toBe("过了 1 天");
    expect(dueText(new Date(NOW + 10_000).toISOString(), NOW)).toBe("还剩 1 分钟");
    expect(dueText(null, NOW)).toBe("没有截止时间");
  });
});

describe("reminderText", () => {
  it("names the time left, the homework and the course", () => {
    expect(reminderText(item(), NOW)).toBe("还剩 3 小时：Journal 4（ENGL 1000）还没交");
    expect(reminderText(item({ course_code: "", course: "" }), NOW)).toBe("还剩 3 小时：Journal 4还没交");
  });

  it("finds the course in Canvas's long course code, or in the course name", () => {
    const cis = { course_code: "F26 CIS D022A 54Y Beg Prog Method C++", course: "CIS 22A" };
    expect(courseOf(cis)).toBe("CIS 22A");
    expect(courseOf({ course_code: "", course: "F26 ENGL C1000 Reading" })).toBe("ENGL 1000");
    expect(courseOf({ course_code: "", course: "Orientation" })).toBe("Orientation");
  });
});

describe("attention", () => {
  it("counts missing and due within 24 h, not the week or what was handed in", () => {
    expect(attention(null)).toBe(0);
    const b = board({ missing: [item()], soon: [item(), item()], week: [item()], submitted: [item()] });
    expect(attention(b)).toBe(3);
  });
});

describe("openText", () => {
  it("says what the agent did, in Chinese", () => {
    expect(openText(null, null)).toBe("");
    expect(openText(run("dispatched"), null)).toBe("正在打开…");
    expect(openText(run("succeeded"), null)).toContain("我交了，查一下");
    expect(openText(run("failed", "no window titled 'Journal 4' appeared within 20 s"), null)).toBe(
      "没打开成功：页面可能打开了，但没认出它的窗口（比如 Canvas 要你先登录）",
    );
    expect(openText(run("lost"), null)).toBe("电脑助手断开了");
  });

  it("gives the offline refusal its own sentence", () => {
    expect(openText(null, new ApiError(503, "agent offline"))).toContain("电脑助手没有连上");
    expect(openText(null, new ApiError(404, "没有这份作业"))).toBe("（404）没有这份作业");
  });
});

describe("waitForJobs", () => {
  const instant = { sleep: async () => undefined, intervalMs: 1 };
  function job(id: string, status: Job["status"]): Job {
    return { id, status, attempts: 1, last_error: "" };
  }

  it("waits for this click's sync jobs, not for any newer record", async () => {
    const answers: Record<string, Job["status"][]> = {
      a: ["queued", "running", "succeeded"],
      b: ["running", "succeeded"],
    };
    let clock = 0;
    const outcome = await waitForJobs(
      ["a", "b"],
      async (id) => job(id, answers[id].shift() ?? "succeeded"),
      () => true,
      { ...instant, limitMs: 100, now: () => clock++ },
    );
    expect(outcome).toBe("updated");
    expect(answers.a).toEqual([]);
  });

  it("says when the sync failed", async () => {
    const outcome = await waitForJobs(["a"], async (id) => job(id, "dead"), () => true, {
      ...instant,
      limitMs: 100,
    });
    expect(outcome).toBe("failed");
  });

  it("gives up after the limit and survives failed asks", async () => {
    let clock = 0;
    let calls = 0;
    const outcome = await waitForJobs(
      ["a"],
      async (id) => {
        calls += 1;
        if (calls === 1) throw new Error("hub restarting");
        return job(id, "running");
      },
      () => true,
      { ...instant, limitMs: 5, now: () => clock++ },
    );
    expect(outcome).toBe("slow");
    expect(calls).toBeGreaterThan(1);
  });

  it("says nothing once the page is gone", async () => {
    const outcome = await waitForJobs(["a"], async (id) => job(id, "succeeded"), () => false, {
      ...instant,
      limitMs: 100,
    });
    expect(outcome).toBeNull();
  });
});

describe("pollUntil", () => {
  it("tells the caller when it gave up", () => {
    vi.useFakeTimers();
    try {
      let clock = 0;
      const gaveUp = vi.fn();
      pollUntil(
        () => new Promise<number>(() => undefined), // never answers
        () => undefined,
        () => false,
        { intervalMs: 10, limitMs: 25, isVisible: () => true, now: () => clock, onGiveUp: gaveUp },
      );
      for (let i = 0; i < 5; i++) {
        clock += 10;
        vi.advanceTimersByTime(10);
      }
      expect(gaveUp).toHaveBeenCalledOnce();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("firstThing", () => {
  const week = (title: string, planned = false) =>
    item({
      title,
      state: "week",
      due_at: new Date(NOW + 50 * H).toISOString(),
      planned: planned ? { event_id: "e", starts_at: "x", ends_at: "y" } : null,
    });

  it("is nothing without a board or without work", () => {
    expect(firstThing(null, NOW)).toBeNull();
    expect(firstThing(board(), NOW)).toBeNull();
  });

  it("puts homework due within 24 h first, then missing, then an unplanned one", () => {
    const missing = item({ title: "Essay 1", state: "missing", due_at: new Date(NOW - 50 * H).toISOString() });
    const all = board({ soon: [item()], missing: [missing], week: [week("Essay 2")] });
    expect(firstThing(all, NOW)).toMatchObject({ kind: "soon", text: "还剩 3 小时：Journal 4（ENGL 1000）还没交" });
    expect(firstThing({ ...all, soon: [] }, NOW)).toMatchObject({
      kind: "missing",
      text: "缺交：Essay 1（ENGL 1000），已过 2 天",
    });
    expect(firstThing({ ...all, soon: [], missing: [] }, NOW)).toMatchObject({
      kind: "plan",
      text: "还剩 2 天：Essay 2（ENGL 1000），还没排时间",
    });
  });

  it("leaves the time out for missing work with no due date", () => {
    const b = board({ missing: [item({ title: "Essay 1", state: "missing", due_at: null })] });
    expect(firstThing(b, NOW)?.text).toBe("缺交：Essay 1（ENGL 1000）");
  });

  it("skips homework that already has time set aside", () => {
    const b = board({ week: [week("Essay 2", true), week("Essay 3")] });
    expect(firstThing(b, NOW)?.item.title).toBe("Essay 3");
    expect(firstThing(board({ week: [week("Essay 2", true)] }), NOW)).toBeNull();
  });
});

describe("weekText and weekLabel", () => {
  const w = { start: "2026-11-16", on_time: 3, late: 1, missing: 0, open: 2 };
  it("says the counts in words, leaving out zeros except 按时", () => {
    expect(weekText(w)).toBe("按时 3 · 迟交 1 · 还没交 2");
    expect(weekText({ ...w, on_time: 0, late: 0, open: 0 })).toBe("按时 0");
  });
  it("names the week by its Monday, or 这周", () => {
    expect(weekLabel(w, false)).toBe("11/16 那周");
    expect(weekLabel(w, true)).toBe("这周");
  });
});
