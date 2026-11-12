import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { type CourseGpa, createApi } from "./api";
import { byModule, GpaView } from "./GpaView";

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
