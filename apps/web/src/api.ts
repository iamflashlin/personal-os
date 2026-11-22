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
  importance?: "high" | "normal" | "low";
  low_value?: boolean;
  action_needed: boolean;
  action: string;
  deadline_text: string;
}

export interface EmailSummary extends EntrySummary {
  id: string;
  points: string[];
  low_value: boolean;
  prompt_version: number;
  item_id: string;
  deadline_date: string | null;
  importance: "high" | "normal" | "low";
  error: string;
  updated_at: string;
  version: number;
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
  low_value_mail?: number;
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

/** Questions about mail (POST /chat/ask, ADR 0033). The browser keeps the conversation. */
export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

export interface ChatAsk {
  question: string;
  history: ChatTurn[];
  time_zone: string;
}

export interface CitedMail {
  item: SyncedItem;
  summary: EmailSummary | null;
}

/** An action the assistant proposes; nothing happens until the user clicks 确认. */
export interface ChatProposal {
  action: "mark_handled";
  item_ids: string[];
  count: number;
  description: string; // written by the Hub, not the model
  sample: CitedMail[];
}

export interface ChatAnswer {
  answer: string;
  cited: CitedMail[];
  considered: number;
  unsummarised: number;
  proposal: ChatProposal | null;
}

/** In-app mail triage (ADR 0034): 已处理 marks, groups, batches with undo, rules. */
export type HandledBy = "batch" | "manual" | "rule";

export interface TriageGroup {
  key: string;
  kind: string;
  label: string;
  count: number;
  item_ids: string[];
  rule: unknown | null;
  rule_description: string;
}

export interface HandledMark {
  item_id: string;
  by: HandledBy;
  batch_id: string | null;
  rule_id: string | null;
}

export interface TriageBatch {
  id: string;
  kind: string;
  status: "applied" | "undone";
  label: string;
  description: string;
  count: number;
  item_ids: string[];
  rule_id: string | null;
  applied_at: string | null;
  undone_at: string | null;
  version: number;
}

export interface TriageRule {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  matched: number;
  created_at: string;
  version: number;
}

export interface TriageView {
  open_count: number;
  unread_count: number;
  unsummarised: number;
  groups: TriageGroup[];
  handled: HandledMark[];
  recent: TriageBatch[];
  rules: TriageRule[];
}

/** GPA management from Canvas (ADR 0037). */
export interface GroupStatus {
  name: string;
  weight: number;
  earned: number;
  possible: number;
  percent: number | null;
  graded: number;
  total: number;
}

export interface WorkItem {
  item_id: string;
  title: string;
  due: string | null;
  points: number | null;
  group: string;
  state: string;
  score: number | null;
  url: string;
}

export interface CourseGpa {
  integration_item_id: string;
  code: string;
  name: string;
  url: string;
  current_score: number | null;
  current_grade: string;
  percent: number | null;
  basis: "syllabus" | "canvas" | "none";
  letter: string;
  letter_source: "syllabus" | "canvas" | "";
  units: number | null;
  profile_confirmed: boolean | null;
  notes: string[];
  grade_points: number | null;
  weighted: boolean;
  groups: GroupStatus[];
  completion: { due_so_far: number; done: number; missing: number; late: number };
  missing: WorkItem[];
  upcoming: WorkItem[];
  recent: WorkItem[];
  lines: { label: string; target: number; needed: number | null; status: string }[];
  materials: { title: string; module: string; kind: string; url: string }[];
}

export interface GpaView {
  courses: CourseGpa[];
  gpa: number | null;
  gpa_weighted: boolean;
  units_total: number | null;
  gpa_note: string;
  generated_at: string;
}

/** The course knowledge map (ADR 0041). */
export type MasteryState = "not_tested" | "seen" | "practicing" | "verified" | "needs_review";

export interface MapEvidence {
  title: string;
  score: number | null;
  points: number | null;
  percent: number | null;
  due: string | null;
  url: string;
}

export interface MapResource {
  title: string;
  kind: string;
  url: string;
}

export interface MapMastery {
  state: MasteryState;
  source: "user" | "quiz" | "none";
  note: string;
  updated_at: string | null;
}

export interface MapConcept {
  key: string;
  kind: "chapter" | "section" | "concept";
  parent: string;
  title: string;
  title_zh: string;
  page: number | null;
  material_url: string;
  prereq: string[];
  prereq_origin: "teacher" | "ai";
  origin: "teacher" | "ai";
  assessments: MapEvidence[];
  resources: MapResource[];
  mastery: MapMastery | null;
}

export interface MapExam {
  name: string;
  at: string | null;
  days_left: number | null;
  scope: string[];
  scope_source: string;
  review: string;
  review_url: string;
  resources: MapResource[];
  grade: MapEvidence | null;
}

export interface CourseMap {
  course_code: string;
  material: string;
  note: string;
  concepts: MapConcept[];
  exams: MapExam[];
  checklist: { text: string; source: string }[];
}

export interface ExamMap {
  course_code: string;
  exam: MapExam;
  sections: MapConcept[];
  prerequisites: MapConcept[];
  suggested: string[];
  why: Record<string, string>;
  checklist: { text: string; source: string }[];
}

/** A course's syllabus rules (ADR 0040). */
export interface CourseRule {
  kind: "late" | "makeup" | "exam" | "gate" | "integrity" | "grading" | "other";
  text: string;
  source: string;
}

export interface CourseProfile {
  id: string;
  code: string;
  title: string;
  term: string;
  units: number | null;
  units_source: string;
  scale: { letter: string; min: number }[];
  scale_source: string;
  categories: { name: string; weight: number; match: string }[];
  rules: CourseRule[];
  open_questions: string[];
  syllabus_source: string;
  confirmed_at: string | null;
  origin: string;
  updated_at: string;
  version: number;
}

/** The schedule (ADR 0038). */
export type EventKind = "class" | "activity" | "workout" | "task" | "exam" | "other";

export interface NewEvent {
  title: string;
  kind: EventKind;
  starts_at: string;
  ends_at: string;
  all_day?: boolean;
  location?: string;
  notes?: string;
  repeat_days?: string[];
  repeat_until?: string | null;
}

export interface AgendaEntry {
  key: string;
  title: string;
  kind: string;
  starts_at: string;
  ends_at: string | null;
  all_day: boolean;
  location: string;
  source: "manual" | "calendar" | "canvas";
  event_id: string | null;
  url: string;
  blocks: boolean;
  conflict: boolean;
  repeats: boolean;
}

export interface Agenda {
  start: string;
  end: string;
  time_zone: string;
  entries: AgendaEntry[];
  free: { starts_at: string; ends_at: string; minutes: number }[];
  day_window: [number, number];
}

/** The 简报 (ADR 0039). */
export interface NewDigestItem {
  channel: "news" | "club" | "group" | "other";
  source_name: string;
  title: string;
  summary?: string;
  raw_text?: string;
  url?: string;
  topics?: string[];
  published_at?: string | null;
  happens_at?: string | null;
  important?: boolean;
}

export interface DigestItem {
  id: string;
  channel: string;
  source_name: string;
  title: string;
  summary: string;
  raw_text: string;
  url: string;
  topics: string[];
  published_at: string;
  happens_at: string | null;
  important: boolean;
  read: boolean;
  read_at: string | null;
  origin: string;
  created_at: string;
  version: number;
}

export interface DigestView {
  view: "today" | "history";
  items: DigestItem[];
  unread_today: number;
  unread_history: number;
  channels: Record<string, number>;
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

/** A fresh idempotency key. `crypto.randomUUID` needs a secure context (https or loopback). */
export function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

// 开始学习 (ADR 0042)
export interface StudyStep {
  label: string;
  action: string;
  params: Record<string, unknown>;
}
export interface NextUp {
  key: string;
  title: string;
  why: string;
  page: number | null;
  exam: string;
}
export interface LastSession {
  started_at: string;
  finished_at: string | null;
  title: string;
}
export interface StudyPlan {
  course_code: string;
  next: NextUp;
  steps: StudyStep[];
  last: LastSession | null;
}
export type StepStatus =
  | "dispatched"
  | "succeeded"
  | "failed"
  | "needs_user"
  | "cancelled"
  | "lost"
  | "not_sent";
export interface StepRun {
  label: string;
  action_run_id: string | null;
  status: StepStatus;
  message: string;
}
export interface StudySession {
  id: string;
  course_code: string;
  status: "started" | "finished";
  next: NextUp;
  steps: StepRun[];
  started_at: string;
  finished_at: string | null;
  note: string;
  version: number;
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
    gpa: () => call<GpaView>("/gpa"),
    profiles: () => call<CourseProfile[]>("/academic/profiles"),
    studyNext: () => call<StudyPlan>("/study/next"),
    studyPlan: (code: string) => call<StudyPlan>(`/study/plans/${encodeURIComponent(code)}`),
    /** `idempotencyKey`: one per attempt to start, reused on a retry, so a retry never opens
     * things twice. */
    startStudy: (code: string, idempotencyKey: string) =>
      call<StudySession>("/study/sessions", {
        method: "POST",
        body: JSON.stringify({ course_code: code }),
        headers: { "Idempotency-Key": idempotencyKey },
      }),
    studySession: (id: string) => call<StudySession>(`/study/sessions/${encodeURIComponent(id)}`),
    finishStudy: (id: string, version: number, note = "") =>
      call<StudySession>(`/study/sessions/${encodeURIComponent(id)}/finish`, {
        method: "POST",
        body: JSON.stringify({ version, note }),
      }),
    courseMaps: () => call<string[]>("/academic/maps"),
    courseMap: (code: string) => call<CourseMap>(`/academic/maps/${encodeURIComponent(code)}`),
    examMap: (code: string, exam: string) =>
      call<ExamMap>(
        `/academic/maps/${encodeURIComponent(code)}/exams/${encodeURIComponent(exam)}`,
      ),
    setMastery: (code: string, key: string, state: MasteryState, note = "") =>
      call<MapMastery>(
        `/academic/maps/${encodeURIComponent(code)}/mastery/${encodeURIComponent(key)}`,
        { method: "PUT", body: JSON.stringify({ state, note }) },
      ),
    clearMastery: (code: string, key: string) =>
      call<void>(`/academic/maps/${encodeURIComponent(code)}/mastery/${encodeURIComponent(key)}`, {
        method: "DELETE",
      }),
    confirmProfile: (code: string, version: number) =>
      call<CourseProfile>(`/academic/profiles/${encodeURIComponent(code)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ version }),
      }),
    digest: (view: "today" | "history", timeZone: string, unreadOnly = false, channel = "") =>
      call<DigestView>(
        `/digest?${new URLSearchParams({
          view,
          time_zone: timeZone,
          unread_only: String(unreadOnly),
          ...(channel ? { channel } : {}),
        })}`,
      ),
    addDigest: (item: NewDigestItem, timeZone: string) =>
      call<DigestItem>(`/digest/items?${new URLSearchParams({ time_zone: timeZone })}`, {
        method: "POST",
        body: JSON.stringify(item),
      }),
    markDigest: (id: string, read: boolean) =>
      call<DigestItem>(`/digest/items/${encodeURIComponent(id)}/read`, {
        method: "PUT",
        body: JSON.stringify({ read }),
      }),
    readAllDigest: (view: "today" | "history", timeZone: string, channel = "") =>
      call<{ marked: number }>(
        `/digest/read-all?${new URLSearchParams({
          view,
          time_zone: timeZone,
          ...(channel ? { channel } : {}),
        })}`,
        { method: "POST" },
      ),
    agenda: (start: string, end: string, timeZone: string) =>
      call<Agenda>(`/schedule?${new URLSearchParams({ start, end, time_zone: timeZone })}`),
    createEvent: (event: NewEvent, timeZone: string) =>
      call<{ id: string }>(`/schedule/events?${new URLSearchParams({ time_zone: timeZone })}`, {
        method: "POST",
        body: JSON.stringify(event),
      }),
    deleteEvent: (id: string) =>
      call<void>(`/schedule/events/${encodeURIComponent(id)}`, { method: "DELETE" }),
    triage: (timeZone: string) =>
      call<TriageView>(`/triage?${new URLSearchParams({ time_zone: timeZone })}`),
    handleMail: (itemIds: string[], groupKey = "", saveRule = false) =>
      call<TriageBatch>("/triage/handle", {
        method: "POST",
        body: JSON.stringify({ item_ids: itemIds, group_key: groupKey, save_rule: saveRule }),
      }),
    undoBatch: (batchId: string) =>
      call<TriageBatch>(`/triage/batches/${encodeURIComponent(batchId)}/undo`, { method: "POST" }),
    setMailHandled: (itemId: string, handled: boolean) =>
      call<HandledMark>(`/triage/items/${encodeURIComponent(itemId)}`, {
        method: "PUT",
        body: JSON.stringify({ handled }),
      }),
    setRule: (ruleId: string, enabled: boolean) =>
      call<TriageRule>(`/triage/rules/${encodeURIComponent(ruleId)}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled }),
      }),
    askMail: (ask: ChatAsk) =>
      call<ChatAnswer>("/chat/ask", { method: "POST", body: JSON.stringify(ask) }),
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
