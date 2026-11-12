import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { type ChatAnswer, createApi } from "./api";
import { ChatBox, historyFor, MAX_HISTORY } from "./ChatBox";

const answer = (text: string): ChatAnswer => ({ answer: text, cited: [], considered: 1, unsummarised: 0 });

describe("historyFor", () => {
  it("sends answered turns only, newest last, at most six", () => {
    const xs = [
      ...Array.from({ length: 5 }, (_, i) => ({ question: `q${i}`, answer: answer(`a${i}`) })),
      { question: "failed", error: "AI 这次没答上来" },
    ];
    const turns = historyFor(xs);
    expect(turns).toHaveLength(MAX_HISTORY);
    expect(turns.at(-1)).toEqual({ role: "assistant", text: "a4" });
    expect(turns.some((t) => t.text === "failed")).toBe(false);
  });

  it("cuts each turn to the Hub's limit", () => {
    const turns = historyFor([{ question: "x".repeat(2000), answer: answer("y".repeat(2000)) }]);
    expect(turns.every((t) => t.text.length <= 1000)).toBe(true);
  });
});

describe("askMail", () => {
  it("posts the question, history and zone, and shows the Hub's sentence on 503", async () => {
    const sent: { path: string; body: unknown }[] = [];
    const api = createApi(async (path, init) => {
      sent.push({ path, body: JSON.parse(String(init?.body)) });
      return new Response(JSON.stringify({ detail: "本月 AI 预算已用完" }), { status: 503 });
    });
    await expect(
      api.askMail({ question: "这周交什么", history: [], time_zone: "America/Los_Angeles" }),
    ).rejects.toMatchObject({ status: 503, detail: "本月 AI 预算已用完" });
    expect(sent).toEqual([
      {
        path: "/chat/ask",
        body: { question: "这周交什么", history: [], time_zone: "America/Los_Angeles" },
      },
    ]);
  });
});

describe("ChatBox", () => {
  it("renders an input and a disabled send button before anything is typed", () => {
    const html = renderToStaticMarkup(
      createElement(ChatBox, { api: createApi() }),
    );
    expect(html).toContain("chat-input");
    expect(html).toMatch(/<button[^>]*chat-send[^>]*disabled/);
  });
});
