import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type Api,
  ApiError,
  type ExecutionMode,
  type Goal,
  type NewTask,
  type Project,
  type Task,
  type TaskStatus,
  parseTags,
} from "./api";
import { ConnectionsView } from "./ConnectionsView";
import { MailView } from "./MailView";
import { MemoryView } from "./MemoryView";
import { TodayView } from "./TodayView";

const TASK_STATUS: Record<TaskStatus, string> = {
  todo: "未开始",
  in_progress: "进行中",
  blocked: "卡住",
  done: "已完成",
  cancelled: "已取消",
};

const MODE: Record<ExecutionMode, string> = {
  delegate: "交给 AI",
  collaborate: "一起做",
  human_led: "自己做",
};

const VIEW = {
  today: "今日",
  mail: "邮件",
  tasks: "任务",
  memories: "记忆",
  connections: "连接",
} as const;
type View = keyof typeof VIEW;

interface Data {
  goals: Goal[];
  projects: Project[];
  tasks: Task[];
}

/** A fresh idempotency key. `crypto.randomUUID` needs a secure context (https or loopback). */
function newKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}

/** Runs one user action; resolves to true only if it succeeded. */
type Run = (action: () => Promise<unknown>) => Promise<boolean>;

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const hint = err.status === 409 ? "（数据刚被改过，页面已刷新，请再试一次）" : "";
    return `操作失败（${err.status}）：${err.detail}${hint}`;
  }
  return String(err);
}

export function App({ api }: { api: Api }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("today");
  const latestReload = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latestReload.current;
    try {
      const [goals, projects, tasks] = await Promise.all([api.goals(), api.projects(), api.tasks()]);
      // A slower, older reload must not overwrite newer data.
      if (ticket === latestReload.current) setData({ goals, projects, tasks });
    } catch (err) {
      setError(`连不上 Hub：${errorText(err)}`);
    }
  }, [api]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const run: Run = async (action) => {
    try {
      await action();
      setError(null);
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      // Reload on failure too, so a 409 brings in the current version for the retry.
      await reload();
    }
  };

  const goalTitle = new Map((data?.goals ?? []).map((g) => [g.id, g.title]));
  const projectTitle = new Map((data?.projects ?? []).map((p) => [p.id, p.title]));

  return (
    <main className="page">
      <header>
        <h1>Personal OS</h1>
        <nav className="views" aria-label="切换页面">
          {(Object.keys(VIEW) as View[]).map((v) => (
            <button
              key={v}
              type="button"
              className={view === v ? "active" : ""}
              aria-current={view === v ? "page" : undefined}
              onClick={() => setView(v)}
            >
              {VIEW[v]}
            </button>
          ))}
        </nav>
      </header>
      {view === "today" && <TodayView api={api} onConnect={() => setView("connections")} />}
      {view === "mail" && <MailView api={api} />}
      {view === "memories" && <MemoryView api={api} />}
      {view === "connections" && <ConnectionsView api={api} />}
      {view === "tasks" && !data && !error && <p>加载中…</p>}
      {view === "tasks" && error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {view === "tasks" && data && (
      <>
      <div className="columns">
        <section data-testid="goals">
          <h2>目标</h2>
          {data.goals.length === 0 && <p className="muted">还没有目标</p>}
          <ul>
            {data.goals.map((g) => (
              <li key={g.id}>{g.title}</li>
            ))}
          </ul>
        </section>
        <section data-testid="projects">
          <h2>项目</h2>
          {data.projects.length === 0 && <p className="muted">还没有项目</p>}
          <ul>
            {data.projects.map((p) => (
              <li key={p.id}>
                {p.title}
                {p.goal_id && <span className="muted"> · {goalTitle.get(p.goal_id)}</span>}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section data-testid="tasks">
        <h2>任务</h2>
        <NewTaskForm
          projects={data.projects}
          onCreate={(task, key) => run(() => api.createTask(task, key))}
        />
        {data.tasks.length === 0 && <p className="muted">还没有任务</p>}
        <ul className="tasks">
          {data.tasks.map((t) => (
            <TaskRow
              key={t.id}
              task={t}
              project={t.project_id ? projectTitle.get(t.project_id) : undefined}
              onComplete={(note) => run(() => api.completeTask(t, note))}
            />
          ))}
        </ul>
      </section>
      </>
      )}
    </main>
  );
}

function NewTaskForm({
  projects,
  onCreate,
}: {
  projects: Project[];
  onCreate: (task: NewTask, idempotencyKey: string) => Promise<boolean>;
}) {
  const [title, setTitle] = useState("");
  const [projectId, setProjectId] = useState("");
  const [tags, setTags] = useState("");
  const [pending, setPending] = useState(false);
  // One key per distinct request: any edit makes a new one, so a retry of the same
  // submission is deduplicated but an edited one is never refused as "different body".
  const [key, setKey] = useState(newKey);
  const edit = (set: (value: string) => void) => (value: string) => {
    set(value);
    setKey(newKey());
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending || !title.trim()) return;
    setPending(true);
    const task = { title: title.trim(), project_id: projectId || null, tags: parseTags(tags) };
    const ok = await onCreate(task, key);
    setPending(false);
    if (ok) {
      setTitle("");
      setTags("");
      setKey(newKey());
    }
  };

  return (
    <form className="new-task" onSubmit={submit} aria-label="新建任务">
      <label>
        <span className="label">任务标题</span>
        <input
          required
          pattern=".*\S.*"
          title="标题不能只有空格"
          placeholder="例如：读第 3 次实验的说明"
          value={title}
          onChange={(e) => edit(setTitle)(e.target.value)}
        />
      </label>
      <label>
        <span className="label">所属项目</span>
        <select value={projectId} onChange={(e) => edit(setProjectId)(e.target.value)}>
          <option value="">（不属于任何项目）</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.title}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="label">标签（逗号分开）</span>
        <input
          placeholder="course:CIS"
          value={tags}
          onChange={(e) => edit(setTags)(e.target.value)}
        />
      </label>
      <button type="submit" disabled={pending}>
        {pending ? "添加中…" : "添加任务"}
      </button>
    </form>
  );
}

function TaskRow({
  task,
  project,
  onComplete,
}: {
  task: Task;
  project: string | undefined;
  onComplete: (note: string) => Promise<boolean>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const done = task.status === "done";

  const confirm = async () => {
    if (pending) return;
    setPending(true);
    const ok = await onComplete(note);
    setPending(false);
    if (ok) setConfirming(false);
  };

  return (
    <li className={done ? "task done" : "task"} data-testid={`task-${task.id}`}>
      <div className="task-main">
        <span className="task-title">{task.title}</span>
        <span className={`badge ${task.status}`} data-testid="task-status">
          {TASK_STATUS[task.status]}
        </span>
        <span className="muted">
          {MODE[task.execution_mode]}
          {project && ` · ${project}`}
          {task.tags.length > 0 && ` · ${task.tags.join(", ")}`}
        </span>
      </div>
      {!done && !confirming && (
        <button type="button" onClick={() => setConfirming(true)}>
          标记完成
        </button>
      )}
      {!done && confirming && (
        <div className="confirm">
          <label>
            <span className="label">完成说明（可不填）</span>
            <input
              autoFocus
              placeholder="一句话说明做完了什么"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </label>
          <button type="button" className="primary" disabled={pending} onClick={confirm}>
            {pending ? "提交中…" : "确认，我已完成"}
          </button>
          <button type="button" disabled={pending} onClick={() => setConfirming(false)}>
            取消
          </button>
        </div>
      )}
    </li>
  );
}
