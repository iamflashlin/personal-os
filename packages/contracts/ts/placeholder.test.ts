import { describe, expect, it } from "vitest";
import { CONTRACTS_VERSION } from "./placeholder";

describe("contracts placeholder", () => {
  it("exposes a semver version string", () => {
    expect(CONTRACTS_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
  });
});
