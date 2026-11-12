import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { type CourseGpa, createApi } from "./api";
import { byModule, GpaView, keepLine, shortCode } from "./GpaView";

const course: CourseGpa = {
  integration_item_id: "c1",
  code: "MATH D001A",
  name: "Calculus I",
  url: "",
  current_score: 96.1,
  current_grade: "A",
  percent: 96.1,
  basis: "canvas",
  letter: "A",
  letter_source: "canvas",
  units: null,
  profile_confirmed: null,
  notes: [],
  grade_points: 4,
  weighted: true,
  groups: [],
  completion: { due_so_far: 3, done: 2, missing: 1, late: 0 },
  missing: [],
  upcoming: [],
  recent: [],
  lines: [],
  materials: [
    { title: "Syllabus", module: "Start", kind: "File", url: "https://c/1" },
    { title: "Notes 1", module: "Week 1", kind: "Page", url: "https://c/2" },
    { title: "Notes 2", module: "Week 1", kind: "Page", url: "https://c/3" },
  ],
};

describe("GpaView", () => {
  it("groups materials by module in order", () => {
    expect(byModule(course).map(([m, items]) => [m, items.length])).toEqual([
      ["Start", 1],
      ["Week 1", 2],
    ]);
  });

  it("asks the Hub for /gpa and shows loading first", async () => {
    const paths: string[] = [];
    const api = createApi(async (path) => {
      paths.push(path);
      return new Response(JSON.stringify({ courses: [], gpa: null, gpa_note: "", generated_at: "" }));
    });
    await api.gpa();
    expect(paths).toEqual(["/gpa"]);
    expect(renderToStaticMarkup(createElement(GpaView, { api }))).toContain("加载中");
  });
});

describe("the course line", () => {
  it("shortens course codes", () => {
    expect(shortCode("MATH D001A")).toBe("MATH 1A");
    expect(shortCode("CIS D022A")).toBe("CIS 22A");
    expect(shortCode("ECON C2002")).toBe("ECON 2002");
    expect(shortCode("Something else")).toBe("Something else");
  });

  it("says what the rest must average to keep the letter", () => {
    const lines = [
      { label: "A（94%）", target: 94, needed: 89.1, status: "reachable" },
      { label: "A-（90%）", target: 90, needed: 81.8, status: "reachable" },
    ];
    expect(keepLine({ letter: "A", lines })).toBe("89.1%");
    expect(keepLine({ letter: "A-", lines })).toBe("81.8%");
    expect(keepLine({ letter: "A", lines: [{ ...lines[0], status: "safe" }] })).toBe("已稳");
    expect(keepLine({ letter: "A", lines: [{ ...lines[0], status: "out_of_reach" }] })).toBe(
      "89.1%，很难",
    );
    expect(keepLine({ letter: "B", lines })).toBe("");
    expect(keepLine({ letter: "", lines })).toBe("");
  });
});

describe("course profiles", () => {
  it("lists profiles and confirms one by code and version", async () => {
    const calls: { path: string; method?: string; body?: unknown }[] = [];
    const api = createApi(async (path, init) => {
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify([]), { status: 200 });
    });
    await api.profiles();
    await api.confirmProfile("CIS D022A", 3);
    expect(calls[0].path).toBe("/academic/profiles");
    expect(calls[1]).toEqual({
      path: "/academic/profiles/CIS%20D022A/confirm",
      method: "POST",
      body: { version: 3 },
    });
  });
});

describe("course maps", () => {
  it("asks for maps, exam maps and mastery by encoded code and key", async () => {
    const calls: { path: string; method?: string; body?: unknown }[] = [];
    const api = createApi(async (path, init) => {
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify([]), { status: 200 });
    });
    await api.courseMaps();
    await api.courseMap("MATH D001A");
    await api.examMap("MATH D001A", "Exam 2");
    await api.setMastery("MATH D001A", "3.4", "verified");
    await api.clearMastery("MATH D001A", "3.4");
    expect(calls.map((c) => c.path)).toEqual([
      "/academic/maps",
      "/academic/maps/MATH%20D001A",
      "/academic/maps/MATH%20D001A/exams/Exam%202",
      "/academic/maps/MATH%20D001A/mastery/3.4",
      "/academic/maps/MATH%20D001A/mastery/3.4",
    ]);
    expect(calls[4].method).toBe("DELETE");
    expect(calls[3]).toMatchObject({ method: "PUT", body: { state: "verified", note: "" } });
  });
});
