import { describe, expect, it } from "vitest";
import { ApiError, createApi, parseTags, type Task } from "./api";

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

describe("parseTags", () => {
  it("splits on ASCII and full-width commas, trims and de-duplicates", () => {
    expect(parseTags(" course:CIS， home ,course:CIS,, ")).toEqual(["course:CIS", "home"]);
  });
});
