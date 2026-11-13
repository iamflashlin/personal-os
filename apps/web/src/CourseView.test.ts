import { describe, expect, it } from "vitest";
import { countdown, workText } from "./CourseView";

const work = (percents: (number | null)[]) => ({
  assessments: percents.map((percent, i) => ({
    title: `Q${i}`,
    score: null,
    points: null,
    percent,
    due: null,
    url: "",
  })),
});

describe("课程 rows", () => {
  it("sums up a section's graded work in one phrase", () => {
    expect(workText(work([]))).toBe("");
    expect(workText(work([null]))).toBe("1 项未出分");
    expect(workText(work([90, 100, null]))).toBe("2 项 · 95%");
  });

  it("counts down to an exam", () => {
    expect(countdown(null)).toBe("");
    expect(countdown(-1)).toBe("已考");
    expect(countdown(0)).toBe("今天");
    expect(countdown(4)).toBe("还有 4 天");
  });
});
