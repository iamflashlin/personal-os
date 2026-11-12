import { describe, expect, it } from "vitest";
import raw from "./styles.css?raw";

describe("styles.css", () => {
  it("has balanced braces (one missing } silently drops every rule after it)", () => {
    const css = raw.replace(/\/\*[\s\S]*?\*\//g, "");
    let depth = 0;
    let lowest = 0;
    for (const ch of css) {
      if (ch === "{") depth += 1;
      if (ch === "}") depth -= 1;
      lowest = Math.min(lowest, depth);
    }
    expect(lowest).toBe(0);
    expect(depth).toBe(0);
  });
});
