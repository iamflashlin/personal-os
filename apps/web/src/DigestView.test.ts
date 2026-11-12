import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { CHANNEL_LABEL } from "./DigestView";

describe("digest", () => {
  it("asks for today with the zone, filters, and marks read", async () => {
    const calls: { path: string; method?: string; body?: unknown }[] = [];
    const api = createApi(async (path, init) => {
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined });
      return new Response(JSON.stringify({}), { status: 200 });
    });
    await api.digest("today", "America/Los_Angeles", true, "group");
    await api.markDigest("d1", true);
    await api.readAllDigest("history", "America/Los_Angeles");
    expect(calls[0].path).toBe(
      "/digest?view=today&time_zone=America%2FLos_Angeles&unread_only=true&channel=group",
    );
    expect(calls[1]).toEqual({ path: "/digest/items/d1/read", method: "PUT", body: { read: true } });
    expect(calls[2].path).toBe("/digest/read-all?view=history&time_zone=America%2FLos_Angeles");
  });

  it("names every channel in Chinese", () => {
    expect(Object.keys(CHANNEL_LABEL).sort()).toEqual(["club", "group", "news", "other"]);
  });
});
