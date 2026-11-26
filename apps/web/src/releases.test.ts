import { describe, expect, it } from "vitest";
import { CHANGELOG, CURRENT } from "./releases";

const parts = (v: string) => v.split(".").map(Number);
const newer = (a: string, b: string) => {
  const [x, y] = [parts(a), parts(b)];
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] > y[i];
  return false;
};

describe("版本记录", () => {
  it("lists versions newest first with dates that never go forward", () => {
    for (let i = 1; i < CHANGELOG.length; i++) {
      expect(newer(CHANGELOG[i - 1].version, CHANGELOG[i].version)).toBe(true);
      expect(CHANGELOG[i - 1].date >= CHANGELOG[i].date).toBe(true);
    }
  });

  it("gives every version a x.y.z number, a real date and at least one line", () => {
    for (const r of CHANGELOG) {
      expect(r.version).toMatch(/^\d+\.\d+\.\d+$/);
      expect(r.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(Number.isNaN(Date.parse(r.date))).toBe(false);
      expect(r.items.length).toBeGreaterThan(0);
      for (const item of r.items) expect(item.trim()).not.toBe("");
    }
  });

  it("calls the newest version current", () => {
    expect(CURRENT).toBe(CHANGELOG[0]);
  });
});
