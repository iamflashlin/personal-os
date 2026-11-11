import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { createApi, type EntrySummary } from "./api";
import { formatUsd, SUMMARY_LABEL, SummaryLine } from "./Summary";

const ok: EntrySummary = {
  status: "ok",
  gist: "Lab 5 周五截止",
  action_needed: true,
  action: "在 Canvas 提交",
  deadline_text: "周五 23:59",
};

describe("AI summaries in the web UI", () => {
  it("formats spend from micro-USD", () => {
    expect(formatUsd(0)).toBe("$0.00");
    expect(formatUsd(1_234_567)).toBe("$1.23");
    expect(formatUsd(10_000_000)).toBe("$10.00");
    expect(formatUsd(-5)).toBe("$0.00");
  });

  it("renders each summary state with its label", () => {
    for (const status of ["pending", "skipped_sensitive", "skipped_unreadable", "failed"] as const) {
      const html = renderToStaticMarkup(
        createElement(SummaryLine, { summary: { ...ok, status } }),
      );
      expect(html).toContain(SUMMARY_LABEL[status]);
    }
    expect(SUMMARY_LABEL.skipped_sensitive).toContain("未发送给 AI");
    const html = renderToStaticMarkup(createElement(SummaryLine, { summary: ok }));
    expect(html).toContain("Lab 5 周五截止");
    expect(html).toContain("需处理");
    expect(html).toContain("周五 23:59");
    expect(renderToStaticMarkup(createElement(SummaryLine, { summary: null }))).toBe("");
  });

  it("renders a summary containing HTML as text", () => {
    const evil = { ...ok, gist: '<script>alert("x")</script>', action: "<img src=x onerror=1>" };
    const html = renderToStaticMarkup(createElement(SummaryLine, { summary: evil }));
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;script&gt;");
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
