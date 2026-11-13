import { describe, expect, it } from "vitest";
import { type AgendaEntry, createApi } from "./api";
import { byDay, sideText, timeText, weekStart } from "./ScheduleView";

const entry = (startsAt: string): AgendaEntry => ({
  key: startsAt,
  title: "x",
  kind: "class",
  starts_at: startsAt,
  ends_at: null,
  all_day: false,
  location: "",
  source: "manual",
  event_id: null,
  url: "",
  blocks: true,
  conflict: false,
  repeats: false,
});

describe("schedule", () => {
  it("starts weeks on Monday", () => {
    expect(weekStart(new Date(2026, 10, 12, 15)).getDay()).toBe(1); // Thursday -> Monday
    expect(weekStart(new Date(2026, 10, 16, 9)).getDate()).toBe(16); // a Monday stays
    expect(weekStart(new Date(2026, 10, 15, 9)).getDate()).toBe(9); // Sunday -> the Monday before
  });

  it("groups entries by local day", () => {
    const a = new Date(2026, 10, 12, 9).toISOString();
    const b = new Date(2026, 10, 12, 18).toISOString();
    const c = new Date(2026, 10, 13, 9).toISOString();
    const days = byDay([entry(a), entry(b), entry(c)]);
    expect([...days.keys()]).toEqual(["2026-11-12", "2026-11-13"]);
    expect(days.get("2026-11-12")?.length).toBe(2);
  });

  it("asks for the agenda with the browser zone and posts new events", async () => {
    const calls: { path: string; body?: unknown }[] = [];
    const api = createApi(async (path, init) => {
      calls.push({ path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify({ id: "e1" }), { status: 200 });
    });
    await api.agenda("2026-11-09T08:00:00.000Z", "2026-11-16T08:00:00.000Z", "America/Los_Angeles");
    await api.createEvent(
      { title: "健身", kind: "workout", starts_at: "a", ends_at: "b", repeat_days: ["MO"] },
      "America/Los_Angeles",
    );
    expect(calls[0].path).toContain("/schedule?start=2026-11-09");
    expect(calls[0].path).toContain("time_zone=America%2FLos_Angeles");
    expect(calls[1].path).toBe("/schedule/events?time_zone=America%2FLos_Angeles");
    expect(calls[1].body).toMatchObject({ title: "健身", repeat_days: ["MO"] });
  });

  it("says a deadline in the time column and names its course shortly", () => {
    const at = new Date(2026, 10, 15, 23, 59).toISOString();
    const deadline = { kind: "deadline", all_day: false, starts_at: at, ends_at: null };
    expect(timeText(deadline)).toBe("截止 23:59");
    expect(timeText({ ...deadline, all_day: true })).toBe("全天");
    expect(sideText({ kind: "deadline", location: "F26 ECON C2002 Prin Macroeconomics 03Y", source: "canvas" })).toBe(
      "ECON 2002",
    );
    expect(sideText({ kind: "workout", location: "Gym", source: "manual" })).toBe("健身");
    expect(sideText({ kind: "deadline", location: "", source: "canvas" })).toBe("");
  });
});
