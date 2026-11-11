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
  kind: "ics" | "canvas" | "email";
  config: Record<string, string>;
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

export type EntryKind = "assignment" | "task" | "event" | "mail" | "announcement";

export interface TodayEntry {
  kind: EntryKind;
  title: string;
  at: string | null;
  all_day: boolean;
  source: string;
  note: string;
  url: string;
  badge: string;
  ref: string;
  summary?: EntrySummary | null;
}

export type SummaryStatus =
  | "pending"
  | "ok"
  | "skipped_sensitive"
  | "skipped_unreadable"
  | "failed";

/** The AI summary of a mail on 今日 (contracts/today.py). */
export interface EntrySummary {
  status: SummaryStatus;
  gist: string;
  action_needed: boolean;
  action: string;
  deadline_text: string;
}

export interface EmailSummary extends EntrySummary {
  id: string;
  item_id: string;
  deadline_date: string | null;
  importance: "high" | "normal" | "low";
  error: string;
}

export interface ModelUsage {
  vendor: string;
  model: string;
  key_set: boolean;
  month: string;
  spent_micro_usd: number;
  budget_micro_usd: number;
  calls: number;
  last_error: string;
}

export interface SummariesStatus {
  pending: number;
  blocked: string;
  notice: string;
  usage: ModelUsage;
}

export interface TodayView {
  date: string;
  timezone: string;
  generated_at: string;
  headline: string;
  due_today: TodayEntry[];
  due_soon: TodayEntry[];
  missing: TodayEntry[];
  events: TodayEntry[];
  unread_mail: number;
  mail: TodayEntry[];
  announcements: TodayEntry[];
  in_progress: TodayEntry[];
  problems: { name: string; error: string }[];
  sources: number;
  mail_actions?: TodayEntry[];
  ai_notice?: string;
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

export interface NewCanvas {
  name: string;
  /** e.g. https://school.instructure.com; not secret. */
  baseUrl: string;
  /** The personal access token; sent once to the credential store, never shown again. */
  token: string;
  interval_s: number;
}

export interface NewEmail {
  name: string;
  /** imap.163.com, imap.gmail.com, …; not secret. */
  host: string;
  /** The mailbox address; not secret, but personal: it is entered, never built in. */
  username: string;
  /** For 163 the client authorisation code (授权码); sent once to the credential store. */
  code: string;
}

/** The credential name the Hub's model layer reads (apps/hub/models/service.py). */
export const MODEL_KEY = "deepseek";

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

  /**
   * Stores the secret as a credential first, then creates the integration. If the second
   * step fails, the credential is removed again so no unused secret is left.
   */
  async function connect(
    kind: Integration["kind"],
    name: string,
    secret: string,
    config: Record<string, string>,
    interval_s: number,
    credentialName: string,
  ): Promise<Integration> {
    const credential = `/credentials/${encodeURIComponent(credentialName)}`;
    await call<unknown>(credential, {
      method: "PUT",
      body: JSON.stringify({ secret, note: name }),
    });
    try {
      return await call<Integration>("/integrations", {
        method: "POST",
        body: JSON.stringify({ kind, name, credential_name: credentialName, interval_s, config }),
      });
    } catch (err) {
      await call<null>(credential, { method: "DELETE" }).catch(() => null);
      throw err;
    }
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
    connectFeed: (feed: NewFeed, credentialName: string) =>
      connect("ics", feed.name, feed.url, {}, feed.interval_s, credentialName),
    connectEmail: (mail: NewEmail, credentialName: string) =>
      connect(
        "email",
        mail.name,
        mail.code,
        { host: mail.host, username: mail.username },
        900,
        credentialName,
      ),
    connectCanvas: (canvas: NewCanvas, credentialName: string) =>
      connect(
        "canvas",
        canvas.name,
        canvas.token,
        { base_url: canvas.baseUrl },
        canvas.interval_s,
        credentialName,
      ),
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
    recentMail: (integration: Integration, limit = 30) =>
      call<SyncedItem[]>(
        `/integrations/${integration.id}/items?${new URLSearchParams({
          order: "desc",
          item_type: "email_message",
          limit: String(limit),
        })}`,
      ),
    today: (timeZone: string) =>
      call<TodayView>(timeZone ? `/today?${new URLSearchParams({ tz: timeZone })}` : "/today"),
    summariesStatus: () => call<SummariesStatus>("/summaries/status"),
    /** At most 200 ids per request (the Hub caps it). */
    emailSummaries: (itemIds: string[]) =>
      itemIds.length === 0
        ? Promise.resolve([] as EmailSummary[])
        : call<EmailSummary[]>(
            `/summaries/email?${new URLSearchParams({ item_ids: itemIds.slice(0, 200).join(",") })}`,
          ),
    runSummaries: () => call<{ job_id: string }>("/summaries/run", { method: "POST" }),
    /** Sent once to the credential store (ADR 0025); the Hub never returns it. */
    setModelKey: (secret: string) =>
      call<unknown>(`/credentials/${MODEL_KEY}`, {
        method: "PUT",
        body: JSON.stringify({ secret, note: "DeepSeek" }),
      }),
    deleteModelKey: () => call<null>(`/credentials/${MODEL_KEY}`, { method: "DELETE" }),
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
