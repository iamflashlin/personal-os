import { describe, expect, it } from "vitest";
import type { Integration } from "./api";
import { DATA_KINDS, type DataKind, kindStatus } from "./DataKinds";

const NOW = Date.parse("2026-11-12T12:00:00Z");

function source(over: Partial<Integration>): Integration {
  const base: Integration = {
    id: "i1",
    version: 1,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
    kind: "canvas",
    config: {},
    name: "De Anza Canvas",
    credential_name: "c",
    interval_s: 3600,
    status: "ok",
    last_sync_at: "2026-11-12T11:30:00Z",
    last_success_at: "2026-11-12T11:30:00Z",
    last_error: "",
    item_count: 10,
  };
  return { ...base, ...over };
}

function kind(key: string): DataKind {
  const found = DATA_KINDS.find((k) => k.key === key);
  if (!found) throw new Error(key);
  return found;
}

describe("data kinds overview", () => {
  it("lists the six P0 kinds", () => {
    expect(DATA_KINDS.map((k) => k.key)).toEqual([
      "academic",
      "schedule",
      "mail",
      "pc",
      "files",
      "goals",
    ]);
  });

  it("is ok after a recent sync and stale after three missed intervals", () => {
    expect(kindStatus(kind("academic"), [source({})], NOW).state).toBe("ok");
    const old = source({ last_success_at: "2026-11-12T07:00:00Z" });
    expect(kindStatus(kind("academic"), [old], NOW).state).toBe("stale");
  });

  it("shows the failure reason", () => {
    const s = kindStatus(
      kind("academic"),
      [source({ status: "error", last_error: "token 过期" })],
      NOW,
    );
    expect(s.state).toBe("error");
    expect(s.error).toBe("token 过期");
  });

  it("tells unconnected, local, later and never-synced kinds apart", () => {
    expect(kindStatus(kind("mail"), [source({})], NOW).state).toBe("none");
    expect(kindStatus(kind("goals"), [], NOW).state).toBe("local");
    expect(kindStatus(kind("schedule"), [], NOW).state).toBe("local");
    expect(kindStatus(kind("pc"), [], NOW).state).toBe("later");
    const fresh = source({
      kind: "email",
      status: "never_synced",
      last_sync_at: null,
      last_success_at: null,
    });
    expect(kindStatus(kind("mail"), [fresh], NOW).state).toBe("never");
  });

  it("is never-synced while any of its sources has not worked yet", () => {
    const second = source({ id: "i2", status: "never_synced", last_sync_at: null, last_success_at: null });
    expect(kindStatus(kind("academic"), [source({}), second], NOW).state).toBe("never");
  });

  it("names the failing source when there are several", () => {
    const bad = source({ id: "i2", name: "旧 Canvas", status: "error", last_error: "HTTP 401" });
    expect(kindStatus(kind("academic"), [source({}), bad], NOW).error).toBe("旧 Canvas：HTTP 401");
  });

  it("is still ok at exactly three intervals", () => {
    const edge = source({ last_success_at: new Date(NOW - 3 * 3600 * 1000).toISOString() });
    expect(kindStatus(kind("academic"), [edge], NOW).state).toBe("ok");
  });
});
