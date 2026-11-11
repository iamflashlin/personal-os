import { describe, expect, it } from "vitest";
import { feedAddress, safeLink, startOfToday } from "./ConnectionsView";

describe("connections page helpers", () => {
  it("makes only http and https links clickable", () => {
    expect(safeLink("https://canvas.example.edu/a/1")).toBe("https://canvas.example.edu/a/1");
    expect(safeLink("http://x/y")).toBe("http://x/y");
    for (const bad of ["javascript:alert(1)", "search-ms:query=x", "file:///C:/x", "ms-msdt:x", "", "not a url"]) {
      expect(safeLink(bad)).toBeNull();
    }
  });

  it("turns webcal links into https and trims what was pasted", () => {
    expect(feedAddress("  webcal://canvas.example.edu/feeds/x.ics \n")).toBe(
      "https://canvas.example.edu/feeds/x.ics",
    );
    expect(feedAddress("https://a/b.ics")).toBe("https://a/b.ics");
  });

  it("starts the upcoming window early enough for today's all-day items", () => {
    const now = new Date(2026, 10, 10, 9, 30); // local 09:30
    const start = startOfToday(now);
    const localMidnight = new Date(2026, 10, 10);
    const utcMidnight = new Date(Date.UTC(2026, 10, 10));
    expect(start.getTime()).toBe(Math.min(localMidnight.getTime(), utcMidnight.getTime()));
    expect(start.getTime()).toBeLessThanOrEqual(utcMidnight.getTime()); // today's all-day items
    expect(start.getTime()).toBeLessThanOrEqual(now.getTime()); // events already in progress
  });
});
