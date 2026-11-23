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
  newKey,
  parseTags,
} from "./api";
import { ConnectionsView } from "./ConnectionsView";
import { MailView } from "./MailView";
import { DigestView } from "./DigestView";
import { GpaView } from "./GpaView";
import { CourseView } from "./CourseView";
import { ScheduleView } from "./ScheduleView";
import { MemoryView } from "./MemoryView";
import { TodayView } from "./TodayView";
import { HomeworkView, attention } from "./HomeworkView";
import type { HomeworkBoard } from "./api";
import { Icon } from "./Icon";

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
  digest: "简报",
  homework: "作业",
  gpa: "成绩",
  course: "课程",
  schedule: "日程",
  tasks: "任务",
  memories: "记忆",
  connections: "连接",
} as const;
type View = keyof typeof VIEW;

/** The sidebar, in groups: what the user does daily comes first. */
const GROUPS: { label: string; views: View[] }[] = [
  { label: "今天", views: ["today", "schedule"] },
  { label: "学业", views: ["homework", "course", "gpa"] },
  { label: "信息", views: ["mail", "digest"] },
  { label: "系统", views: ["tasks", "memories", "connections"] },
];

function todayLabel(): string {
  return new Date().toLocaleDateString("zh-CN", { month: "long", day: "numeric", weekday: "long" });
}

interface Data {
  goals: Goal[];
  projects: Project[];
  tasks: Task[];
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
  // One homework board (ADR 0044) for the sidebar count and the 今日 reminder: loaded at
  // start, every 5 minutes and on each visit to 今日; the 作业 page passes its own up.
  const [homework, setHomework] = useState<HomeworkBoard | null>(null);
  const homeworkCount = attention(homework);
  const homeworkTicket = useRef(0);
  /** A board the 作业 page just loaded: newer than any App load still on its way. */
  const showHomework = useCallback((b: HomeworkBoard) => {
    homeworkTicket.current += 1;
    setHomework(b);
  }, []);
  const loadHomework = useCallback(() => {
    const ticket = ++homeworkTicket.current; // an older, slower answer must not win
    api
      .homework()
      .then((b) => ticket === homeworkTicket.current && setHomework(b))
      .catch(() => undefined); // 今日 already says when the Hub is unreachable
  }, [api]);
  useEffect(() => {
    const timer = window.setInterval(loadHomework, 5 * 60 * 1000); // on every page
    return () => window.clearInterval(timer);
  }, [loadHomework]);
  useEffect(() => {
    if (view === "today") loadHomework();
  }, [view, loadHomework]);
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
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">P</span>
          <span className="brand-name">Personal OS</span>
        </div>
        <nav className="views" aria-label="切换页面">
          {GROUPS.map((g) => (
            <div key={g.label} className="nav-group">
              <div className="nav-label">{g.label}</div>
              {g.views.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={view === v ? "nav-item active" : "nav-item"}
                  aria-current={view === v ? "page" : undefined}
                  onClick={() => setView(v)}
                >
                  <Icon name={v} />
                  <span>{VIEW[v]}</span>
                  {v === "homework" && homeworkCount > 0 && (
                    <span className="nav-count" data-testid="homework-count">
                      <span className="sr-only">，要处理 </span>
                      {homeworkCount}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <main className="page">
        <header className="topbar">
          {/* 今日 is headed by the day itself; the sidebar already names the page. */}
          <h1>{view === "today" ? todayLabel() : VIEW[view]}</h1>
        </header>
        {view === "today" && (
          <TodayView
            api={api}
            onConnect={() => setView("connections")}
            onHomework={() => setView("homework")}
            homework={homework}
            onHomeworkChanged={loadHomework}
          />
        )}
        {view === "homework" && <HomeworkView api={api} onBoard={showHomework} />}
        {view === "mail" && <MailView api={api} />}
        {view === "digest" && <DigestView api={api} />}
        {view === "gpa" && <GpaView api={api} />}
        {view === "course" && <CourseView api={api} />}
        {view === "schedule" && <ScheduleView api={api} />}
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
    </div>
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
