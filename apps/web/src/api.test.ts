import { describe, expect, it } from "vitest";
import { ApiError, createApi, type Integration, type Memory, parseTags, type Task } from "./api";

interface Call {
  url: string;
  init?: RequestInit;
}

function fakeFetch(status: number, body: unknown, calls: Call[]) {
  return async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(status === 204 ? null : JSON.stringify(body), { status });
  };
}

const task = { id: "01ABC", version: 3 } as Task;

describe("api client", () => {
  it("sends the task version and note when completing", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, { ...task, status: "done" }, calls));
    const done = await api.completeTask(task, "finished lab");
    expect(done.status).toBe("done");
    expect(calls[0].url).toBe("/tasks/01ABC/complete");
    expect(calls[0].init?.method).toBe("POST");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ version: 3, note: "finished lab" });
  });

  it("turns an error response into ApiError with the server's detail", async () => {
    const api = createApi(fakeFetch(409, { detail: "version is 4" }, []));
    await expect(api.completeTask(task, "")).rejects.toEqual(new ApiError(409, "version is 4"));
  });

  it("describes validation errors that are not plain strings", async () => {
    const api = createApi(fakeFetch(422, { detail: [{ msg: "too short" }] }, []));
    await expect(api.createTask({ title: "", project_id: null, tags: [] }, "k")).rejects.toThrow(
      "too short",
    );
  });

  it("sends the caller's Idempotency-Key with a new task", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(201, { id: "01T" }, calls));
    await api.createTask({ title: "t", project_id: null, tags: [] }, "key-123");
    const headers = new Headers(calls[0].init?.headers);
    expect(headers.get("Idempotency-Key")).toBe("key-123");
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("reports a non-JSON error body instead of a parse error", async () => {
    const api = createApi(async () => new Response("Internal Server Error", { status: 500 }));
    await expect(api.goals()).rejects.toEqual(new ApiError(500, "Internal Server Error"));
  });
});

describe("connections", () => {
  const integration = { id: "01I", credential_name: "feed.ab12" } as Integration;

  it("stores the feed address as a credential, then creates the integration", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, integration, calls));
    await api.connectFeed({ name: "Canvas", url: "https://x/feed.ics", interval_s: 900 }, "feed.ab12");
    expect(calls.map((c) => [c.init?.method, c.url])).toEqual([
      ["PUT", "/credentials/feed.ab12"],
      ["POST", "/integrations"],
    ]);
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      secret: "https://x/feed.ics",
      note: "Canvas",
    });
    const created = JSON.parse(String(calls[1].init?.body));
    expect(created).toEqual({
      kind: "ics",
      name: "Canvas",
      credential_name: "feed.ab12",
      interval_s: 900,
      config: {},
    });
    expect(JSON.stringify(created)).not.toContain("https://x/feed.ics");
  });

  it("removes the credential again when the integration cannot be created", async () => {
    const calls: Call[] = [];
    const api = createApi(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const failing = url === "/integrations";
      return new Response(failing ? JSON.stringify({ detail: "bad" }) : null, {
        status: failing ? 422 : 204,
      });
    });
    await expect(
      api.connectFeed({ name: "x", url: "https://x/f.ics", interval_s: 900 }, "feed.ab12"),
    ).rejects.toEqual(new ApiError(422, "bad"));
    expect(calls.map((c) => [c.init?.method, c.url])).toEqual([
      ["PUT", "/credentials/feed.ab12"],
      ["POST", "/integrations"],
      ["DELETE", "/credentials/feed.ab12"],
    ]);
  });

  it("deletes the integration and then its credential; a missing credential is fine", async () => {
    const calls: Call[] = [];
    const api = createApi(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const missing = url.startsWith("/credentials/");
      return new Response(missing ? JSON.stringify({ detail: "gone" }) : null, {
        status: missing ? 404 : 204,
      });
    });
    await api.disconnect(integration);
    expect(calls.map((c) => [c.init?.method, c.url])).toEqual([
      ["DELETE", "/integrations/01I"],
      ["DELETE", "/credentials/feed.ab12"],
    ]);
  });

  it("sends a Canvas token only to the credential store, the address as config", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, integration, calls));
    await api.connectCanvas(
      { name: "Canvas", baseUrl: "https://school.instructure.com", token: "tok-123", interval_s: 3600 },
      "canvas.ab12",
    );
    expect(JSON.parse(String(calls[0].init?.body)).secret).toBe("tok-123");
    const created = JSON.parse(String(calls[1].init?.body));
    expect(created.config).toEqual({ base_url: "https://school.instructure.com" });
    expect(created.kind).toBe("canvas");
    expect(JSON.stringify(created)).not.toContain("tok-123");
  });

  it("sends the mail code only to the credential store, server and address as config", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, integration, calls));
    await api.connectEmail(
      { name: "邮箱", host: "imap.163.com", username: "me@163.com", code: "CODE-9" },
      "mail.ab12",
    );
    expect(JSON.parse(String(calls[0].init?.body)).secret).toBe("CODE-9");
    const created = JSON.parse(String(calls[1].init?.body));
    expect(created.kind).toBe("email");
    expect(created.config).toEqual({ host: "imap.163.com", username: "me@163.com" });
    expect(JSON.stringify(created)).not.toContain("CODE-9");
  });

  it("keeps a credential that another integration still uses", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(204, null, calls));
    await api.disconnect(integration, { keepCredential: true });
    expect(calls.map((c) => [c.init?.method, c.url])).toEqual([["DELETE", "/integrations/01I"]]);
  });

  it("asks for items in a time window", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, [], calls));
    const start = new Date("2026-11-10T00:00:00Z");
    await api.integrationItems(integration, start, new Date("2026-11-24T00:00:00Z"));
    const url = new URL(calls[0].url, "http://hub");
    expect(url.pathname).toBe("/integrations/01I/items");
    expect(url.searchParams.get("start")).toBe("2026-11-10T00:00:00.000Z");
  });

  it("asks for the newest mail first, mail only", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, [], calls));
    await api.recentMail(integration);
    const url = new URL(calls[0].url, "http://hub");
    expect(url.pathname).toBe("/integrations/01I/items");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      order: "desc",
      item_type: "email_message",
      limit: "30",
    });
  });
});

describe("parseTags", () => {
  it("splits on ASCII and full-width commas, trims and de-duplicates", () => {
    expect(parseTags(" course:CIS， home ,course:CIS,, ")).toEqual(["course:CIS", "home"]);
  });
});

describe("memory client", () => {
  const memory = { id: "01MEM", version: 2, body: "old" } as Memory;

  it("encodes the search query, including Chinese and spaces", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, [], calls));
    await api.searchMemories("学习 C++ & more");
    expect(calls[0].url).toBe(`/memories/search?q=${encodeURIComponent("学习 C++ & more").replace(/%20/g, "+")}`);
  });

  it("sends the version with a correction and with a confirmation", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, memory, calls));
    await api.correctMemory(memory, "new");
    await api.confirmMemory(memory);
    expect(calls[0].init?.method).toBe("PATCH");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      version: 2,
      body: "new",
      provenance: "user_confirmed",
      confidence: 1,
    });
    expect(calls[1].url).toBe("/memories/01MEM/confirm");
    expect(JSON.parse(String(calls[1].init?.body))).toEqual({ version: 2 });
  });

  it("deletes with no body and accepts 204", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(204, null, calls));
    await expect(api.deleteMemory(memory)).resolves.toBeNull();
    expect(calls[0].init?.method).toBe("DELETE");
    expect(calls[0].url).toBe("/memories/01MEM");
  });
});

describe("today client", () => {
  it("sends the browser's time zone when there is one", async () => {
    const calls: Call[] = [];
    const api = createApi(fakeFetch(200, {}, calls));
    await api.today("America/Los_Angeles");
    await api.today("");
    expect(calls.map((c) => c.url)).toEqual(["/today?tz=America%2FLos_Angeles", "/today"]);
  });
});
