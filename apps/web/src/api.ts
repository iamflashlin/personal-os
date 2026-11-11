export type WorkStatus = "active" | "paused" | "done" | "dropped";
export type TaskStatus = "todo" | "in_progress" | "blocked" | "done" | "cancelled";
export type ExecutionMode = "delegate" | "collaborate" | "human_led";

interface Stored {
  id: string;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface Goal extends Stored {
  title: string;
  notes: string;
  status: WorkStatus;
  due_date: string | null;
}

export interface Project extends Stored {
  goal_id: string | null;
  title: string;
  notes: string;
  status: WorkStatus;
  due_date: string | null;
}

export interface Task extends Stored {
  project_id: string | null;
  title: string;
  notes: string;
  status: TaskStatus;
  due_date: string | null;
  execution_mode: ExecutionMode;
  tags: string[];
  depends_on: string[];
}

export interface NewTask {
  title: string;
  project_id: string | null;
  tags: string[];
}

export type MemoryKind = "preference" | "fact" | "decision" | "experience";
export type Provenance = "raw" | "user_confirmed" | "ai_inferred" | "verified";
export type Sensitivity = "normal" | "private" | "secret";

export interface Memory extends Stored {
  kind: MemoryKind;
  body: string;
  provenance: Provenance;
  confidence: number;
  sensitivity: Sensitivity;
  expires_at: string | null;
  source_ref: string;
}

export interface MemoryHit {
  memory: Memory;
  rank: number | null;
}

export interface NewMemory {
  kind: MemoryKind;
  body: string;
  sensitivity: Sensitivity;
}

export type IntegrationStatus = "never_synced" | "ok" | "error";

export interface Integration extends Stored {
  kind: "ics";
  name: string;
  credential_name: string;
  interval_s: number;
  status: IntegrationStatus;
  last_sync_at: string | null;
  last_success_at: string | null;
  last_error: string;
  item_count: number;
}

export interface SyncedItem extends Stored {
  integration_id: string;
  item_type: string;
  external_id: string;
  title: string;
  body: string;
  location: string;
  url: string;
  starts_at: string | null;
  ends_at: string | null;
  all_day: boolean;
  data: Record<string, unknown>;
}

export interface Job {
  id: string;
  status: "queued" | "running" | "succeeded" | "dead";
  attempts: number;
  last_error: string;
}

export interface NewFeed {
  name: string;
  /** The private feed address; sent once to the credential store, never shown again. */
  url: string;
  interval_s: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`HTTP ${status}: ${detail}`);
  }
}

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;

function describe(body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  }
  return "unexpected response";
}

export function createApi(fetchImpl: Fetch = (input, init) => fetch(input, init)) {
  async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("Content-Type", "application/json");
    const response = await fetchImpl(path, { ...init, headers });
    let body: unknown = null;
    if (response.status !== 204) {
      const text = await response.text();
      try {
        body = text ? JSON.parse(text) : null;
      } catch {
        body = { detail: text || response.statusText };
      }
    }
    if (!response.ok) {
      throw new ApiError(response.status, describe(body) || response.statusText);
    }
    return body as T;
  }

  return {
    goals: () => call<Goal[]>("/goals"),
    projects: () => call<Project[]>("/projects"),
    tasks: () => call<Task[]>("/tasks"),
    /** `idempotencyKey` should be made once per user action, so a retry cannot duplicate. */
    createTask: (task: NewTask, idempotencyKey: string) =>
      call<Task>("/tasks", {
        method: "POST",
        body: JSON.stringify(task),
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    completeTask: (task: Task, note: string) =>
      call<Task>(`/tasks/${task.id}/complete`, {
        method: "POST",
        body: JSON.stringify({ version: task.version, note }),
      }),
    memories: () => call<Memory[]>("/memories"),
    /** Search never returns secret memories (this client does not ask for them). */
    searchMemories: (q: string) =>
      call<MemoryHit[]>(`/memories/search?${new URLSearchParams({ q })}`),
    createMemory: (memory: NewMemory) =>
      call<Memory>("/memories", { method: "POST", body: JSON.stringify(memory) }),
    /** The user wrote the new text, so it is user_confirmed (contracts/memory.py). */
    correctMemory: (memory: Memory, body: string) =>
      call<Memory>(`/memories/${memory.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: memory.version,
          body,
          provenance: "user_confirmed",
          confidence: 1,
        }),
      }),
    confirmMemory: (memory: Memory) =>
      call<Memory>(`/memories/${memory.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ version: memory.version }),
      }),
    deleteMemory: (memory: Memory) =>
      call<null>(`/memories/${memory.id}`, { method: "DELETE" }),
    integrations: () => call<Integration[]>("/integrations"),
    /**
     * Stores the feed address as a credential first, then creates the integration. If the
     * second step fails, the credential is removed again so no unused secret is left.
     */
    connectFeed: async (feed: NewFeed, credentialName: string) => {
      const credential = `/credentials/${encodeURIComponent(credentialName)}`;
      await call<unknown>(credential, {
        method: "PUT",
        body: JSON.stringify({ secret: feed.url, note: feed.name }),
      });
      try {
        return await call<Integration>("/integrations", {
          method: "POST",
          body: JSON.stringify({
            kind: "ics",
            name: feed.name,
            credential_name: credentialName,
            interval_s: feed.interval_s,
          }),
        });
      } catch (err) {
        await call<null>(credential, { method: "DELETE" }).catch(() => null);
        throw err;
      }
    },
    syncIntegration: (integration: Integration) =>
      call<{ job_id: string }>(`/integrations/${integration.id}/sync`, { method: "POST" }),
    /** Deletes the integration, its synced items and (unless kept) its credential. */
    disconnect: async (integration: Integration, options: { keepCredential?: boolean } = {}) => {
      await call<null>(`/integrations/${integration.id}`, { method: "DELETE" });
      if (options.keepCredential) return;
      await call<null>(`/credentials/${encodeURIComponent(integration.credential_name)}`, {
        method: "DELETE",
      }).catch((err: unknown) => {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
      });
    },
    job: (jobId: string) => call<Job>(`/jobs/${jobId}`),
    integrationItems: (integration: Integration, start: Date, end: Date) =>
      call<SyncedItem[]>(
        `/integrations/${integration.id}/items?${new URLSearchParams({
          start: start.toISOString(),
          end: end.toISOString(),
        })}`,
      ),
  };
}

export type Api = ReturnType<typeof createApi>;

export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[,，]/)
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  ];
}
