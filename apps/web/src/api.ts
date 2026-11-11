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
