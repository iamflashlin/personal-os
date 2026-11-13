import { describe, expect, it } from "vitest";
import { createApi } from "./api";
import { formatUsd, SUMMARY_LABEL } from "./Summary";

describe("AI summaries in the web UI", () => {
  it("formats spend from micro-USD", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(1_234_567)).toBe("$1.23");
    expect(formatUsd(10_000_000)).toBe("$10.00");
    expect(formatUsd(-5)).toBe("$0.00");
  });

  it("labels every summary state", () => {
    expect(SUMMARY_LABEL.skipped_sensitive).toContain("未发送给 AI");
    expect(SUMMARY_LABEL.pending).toBe("总结中…");
  });

  it("sends the key once to the credential store and nowhere else", async () => {
    const calls: { url: string; init?: RequestInit }[] = [];
    const api = createApi(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify({ name: "deepseek" }), { status: 200 });
    });
    await api.setModelKey("sk-secret-123");
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe("/credentials/deepseek");
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      secret: "sk-secret-123",
      note: "DeepSeek",
    });
  });

  it("asks for summaries of at most 200 mails and skips the call for none", async () => {
    const calls: string[] = [];
    const api = createApi(async (url: string) => {
      calls.push(url);
      return new Response("[]", { status: 200 });
    });
    expect(await api.emailSummaries([])).toEqual([]);
    expect(calls).toEqual([]);
    await api.emailSummaries(Array.from({ length: 250 }, (_, i) => `id${i}`));
    const ids = new URL(calls[0], "http://x").searchParams.get("item_ids") ?? "";
    expect(ids.split(",")).toHaveLength(200);
  });
});
