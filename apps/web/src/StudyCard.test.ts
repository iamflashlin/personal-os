import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { type Api, ApiError, type StudySession } from "./api";
import {
  lastText,
  loadError,
  pollSession,
  settled,
  STEP_WORD,
  startError,
  stepReason,
  StudyCard,
} from "./StudyCard";

const session = (statuses: StudySession["steps"][number]["status"][]): StudySession => ({
  id: "s",
  course_code: "MATH D001A",
  status: "started",
  next: { key: "3.4", title: "复习 3.4 链式法则", why: "x", page: 31, exam: "Final" },
  steps: statuses.map((status, i) => ({ label: `step ${i}`, action_run_id: null, status, message: "" })),
  started_at: "2026-11-20T10:00:00Z",
  finished_at: null,
  note: "",
  version: 1,
});

describe("开始学习", () => {
  it("is settled only when no step waits for the agent", () => {
    expect(settled(session(["succeeded", "failed"]))).toBe(true);
    expect(settled(session(["succeeded", "dispatched"]))).toBe(false);
    expect(settled(session([]))).toBe(true);
  });

  it("names every step state in one word", () => {
    expect(STEP_WORD.succeeded).toBe("已打开");
    expect(Object.keys(STEP_WORD)).toHaveLength(7);
  });

  it("says where the last session ended", () => {
    expect(lastText(null)).toBe("");
    const last = { started_at: "2026-11-20T10:00:00Z", finished_at: null, title: "复习 3.3" };
    expect(lastText(last)).toContain("复习 3.3 · 没点学完");
    expect(lastText({ ...last, finished_at: "2026-11-20T11:00:00Z" })).toContain("学完了");
  });

  it("explains an offline agent in plain words", () => {
    expect(startError(new ApiError(503, "电脑助手没有连上"))).toContain("电脑助手没有连上");
    expect(startError(new ApiError(404, "no"))).toBe("（404）no");
  });

  it("renders nothing before the plan arrives", () => {
    const api = { courseMaps: () => new Promise(() => undefined) } as unknown as Api;
    expect(renderToStaticMarkup(createElement(StudyCard, { api, code: null }))).toBe("");
  });
});

describe("following a started session", () => {
  afterEach(() => vi.useRealTimers());

  function setup(answer: () => StudySession, visible = () => true) {
    vi.useFakeTimers();
    const calls: number[] = [];
    const updates: StudySession[] = [];
    const stop = pollSession(
      () => {
        calls.push(Date.now());
        return Promise.resolve(answer());
      },
      (s) => updates.push(s),
      { intervalMs: 1500, limitMs: 60_000, isVisible: visible, now: () => Date.now() },
    );
    return { calls, updates, stop };
  }

  it("stops after 60 s even while the Hub keeps answering 'dispatched'", async () => {
    const { calls } = setup(() => session(["dispatched"]));
    await vi.advanceTimersByTimeAsync(59_000);
    const before = calls.length;
    expect(before).toBeGreaterThan(30);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(calls.length - before).toBeLessThanOrEqual(1);
  });

  it("stops once every step is answered", async () => {
    let n = 0;
    const { calls, updates } = setup(() => session([++n < 3 ? "dispatched" : "succeeded"]));
    await vi.advanceTimersByTimeAsync(20_000);
    expect(calls).toHaveLength(3);
    expect(updates.at(-1)?.steps[0].status).toBe("succeeded");
  });

  it("asks nothing while the tab is hidden", async () => {
    const { calls } = setup(() => session(["dispatched"]), () => false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(calls).toHaveLength(0);
  });

  it("drops an answer that arrives after stop()", async () => {
    vi.useFakeTimers();
    let resolve: (s: StudySession) => void = () => undefined;
    const updates: StudySession[] = [];
    const stop = pollSession(
      () => new Promise((r) => (resolve = r)),
      (s) => updates.push(s),
      { intervalMs: 1000, isVisible: () => true, now: () => Date.now() },
    );
    await vi.advanceTimersByTimeAsync(1000);
    stop();
    resolve(session(["succeeded"]));
    await vi.advanceTimersByTimeAsync(0);
    expect(updates).toHaveLength(0);
  });

  it("explains a plan that failed to load without blaming the agent", () => {
    expect(loadError(new ApiError(503, "Hub 正在重启"))).toBe("没能读到学习计划（503）Hub 正在重启");
  });
});

describe("plain words", () => {
  it("points to the links where they are", () => {
    expect(startError(new ApiError(503, "x"), true)).toContain("下面的课程内容里");
    expect(startError(new ApiError(503, "x"), false)).toContain("「课程」页里");
  });

  it("says the agent's common reasons in Chinese and keeps unknown ones", () => {
    expect(stepReason("no window titled 'Notes' appeared within 20s")).toContain("没认出它的窗口");
    expect(stepReason("the agent disconnected before reporting a result")).toContain("中途断开");
    expect(stepReason("something new")).toBe("something new");
  });
});
