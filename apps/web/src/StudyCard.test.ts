import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { type Api, ApiError, type StudySession } from "./api";
import { lastText, settled, STEP_WORD, startError, StudyCard } from "./StudyCard";

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
