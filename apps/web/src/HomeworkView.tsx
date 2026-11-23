import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ActionRun,
  type Api,
  ApiError,
  type HomeworkBoard,
  type HomeworkItem,
  type HomeworkSlot,
  type HomeworkWeek,
  type Job,
  newKey,
  type PlannedTime,
} from "./api";
import { safeLink } from "./ConnectionsView";
import { courseIn } from "./GpaView";
import { pollUntil } from "./poll";
import { STEP_WORD, stepReason } from "./StudyCard";
import { browserZone } from "./TodayView";

const HOUR = 3_600_000;
const CHECK_MS = 3000;
const CHECK_LIMIT_MS = 90_000;

/** "还剩 40 分钟" / "还剩 3 小时" / "还剩 2 天" / "过了 1 天". */
export function dueText(due: string | null, now: number): string {
  if (!due) return "没有截止时间";
  const left = new Date(due).getTime() - now;
  const abs = Math.abs(left);
  const amount =
    abs < HOUR
      ? `${Math.max(1, Math.round(abs / 60_000))} 分钟`
      : abs < 24 * HOUR
        ? `${Math.floor(abs / HOUR)} 小时`
        : `${Math.floor(abs / (24 * HOUR))} 天`;
  return left >= 0 ? `还剩 ${amount}` : `过了 ${amount}`;
}

/** "11月22日 23:59" in the browser's zone. */
export function stamp(at: string | null): string {
  if (!at) return "";
  return new Date(at).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "周二 11/24 19:00–20:00" in the browser's zone: a planned block, as the user reads it. */
export function blockText(b: Pick<PlannedTime, "starts_at" | "ends_at">): string {
  const start = new Date(b.starts_at);
  const weekday = start.toLocaleDateString("zh-CN", { weekday: "short" });
  const day = `${weekday} ${start.getMonth() + 1}/${start.getDate()}`;
  const hm = (d: Date) => d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  return `${day} ${hm(start)}–${hm(new Date(b.ends_at))}`;
}

/** "ENGL 1000" from Canvas's course code or name, else the name as it is. */
export function courseOf(item: Pick<HomeworkItem, "course" | "course_code">): string {
  return courseIn(item.course_code) ?? courseIn(item.course) ?? item.course;
}

/** The 今日 reminder: "还剩 3 小时：Journal 4（ENGL 1000）还没交". */
export function reminderText(item: HomeworkItem, now: number): string {
  const name = courseOf(item);
  const course = name ? `（${name}）` : "";
  return `${dueText(item.due_at, now)}：${item.title}${course}还没交`;
}

/** How many need the user now: missing, or due within 24 h. Shown on the sidebar. */
export function attention(board: HomeworkBoard | null): number {
  return board ? board.missing.length + board.soon.length : 0;
}

/** The sentence under 去提交 once the agent answered, or the Hub refused. */
export function openText(run: ActionRun | null, err: unknown): string {
  if (err instanceof ApiError && err.status === 503)
    return "电脑助手没有连上，所以没法替你打开。点作业名字也能自己打开。";
  if (err instanceof ApiError) return `（${err.status}）${err.detail}`;
  if (err) return String(err);
  if (!run) return "";
  if (run.status === "succeeded") return "已打开。在 Canvas 交完后，点上面的「我交了，查一下」";
  if (run.status === "dispatched") return STEP_WORD.dispatched;
  const reason = run.message ? `：${stepReason(run.message)}` : "";
  return `${STEP_WORD[run.status]}${reason}`;
}

/** 去提交: the agent opens this assignment's Canvas page (the Hub picks the URL). */
function OpenButton({ api, item }: { api: Api; item: HomeworkItem }) {
  const key = useRef(newKey());
  const [run, setRun] = useState<ActionRun | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [gaveUp, setGaveUp] = useState(false); // the agent did not answer within the poll
  const stop = useRef<() => void>(() => undefined);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stop.current();
    };
  }, []);

  const open = async () => {
    // A retry after a failure is a new action; a retry after a refusal (no run) is not.
    if (run !== null) key.current = newKey();
    setBusy(true);
    setErr(null);
    setGaveUp(false);
    try {
      const opened = await api.openHomework(item.id, key.current);
      if (!mounted.current) return; // the row is gone (the board moved it, or the page)
      setRun(opened.action);
      stop.current();
      stop.current = pollUntil(
        () => api.action(opened.action.id),
        (r) => mounted.current && setRun(r),
        (r) => r.status !== "dispatched",
        { onGiveUp: () => mounted.current && setGaveUp(true) },
      );
    } catch (e) {
      if (mounted.current) setErr(e);
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  const text = gaveUp && run?.status === "dispatched" ? "电脑助手一直没回话，可以再试一次" : openText(run, err);
  const waiting = run?.status === "dispatched" && !gaveUp;
  return (
    <span className="hw-open">
      {run?.status !== "succeeded" && (
        <button type="button" className="g-more" onClick={() => void open()} disabled={busy || waiting}>
          {run ? "再试一次" : "去提交"}
        </button>
      )}
      {text && (
        <span className={`hw-open-text ${run ? `step-${run.status}` : err ? "step-failed" : ""}`} role="status">
          {text}
        </span>
      )}
    </span>
  );
}

const PLAN_MINUTES = 60;

/**
 * 排时间 (T-0067): the Hub suggests the earliest free hour before the homework is due;
 * 排进日程 puts it on 日程 as a task block. Once planned, the row says when.
 */
function PlanButton({
  api,
  item,
  onPlanned,
}: {
  api: Api;
  item: HomeworkItem;
  onPlanned: (block: PlannedTime) => void;
}) {
  const [slot, setSlot] = useState<HomeworkSlot | null>(null);
  const [planned, setPlanned] = useState<PlannedTime | null>(item.planned ?? null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => setPlanned(item.planned ?? null), [item.planned]);

  const failed = (e: unknown) => (e instanceof ApiError ? `（${e.status}）${e.detail}` : String(e));
  const ask = async () => {
    setBusy(true);
    setErr("");
    try {
      const found = await api.homeworkSlot(item.id, PLAN_MINUTES, browserZone());
      if (mounted.current) setSlot(found);
    } catch (e) {
      if (mounted.current) setErr(failed(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };
  const confirm = async () => {
    if (!slot?.starts_at || !slot.ends_at) return;
    setBusy(true);
    setErr("");
    try {
      const block = await api.planHomework(item.id, slot.starts_at, slot.ends_at, browserZone());
      if (!mounted.current) return;
      setPlanned(block);
      setSlot(null);
      onPlanned(block);
    } catch (e) {
      if (mounted.current) setErr(failed(e));
    } finally {
      if (mounted.current) setBusy(false);
    }
  };

  if (planned)
    return (
      <span className="hw-plan hw-planned" data-testid="homework-planned">
        已排：{blockText(planned)}
      </span>
    );
  return (
    <span className="hw-plan">
      {!slot && (
        <button type="button" className="g-more" onClick={() => void ask()} disabled={busy}>
          排时间
        </button>
      )}
      {slot?.starts_at && slot.ends_at && (
        <>
          <span data-testid="homework-slot">建议：{blockText({ starts_at: slot.starts_at, ends_at: slot.ends_at })}</span>
          <button type="button" className="g-more" onClick={() => void confirm()} disabled={busy}>
            排进日程
          </button>
          <button type="button" className="g-more" onClick={() => setSlot(null)} disabled={busy}>
            取消
          </button>
        </>
      )}
      {slot && !slot.starts_at && (
        <span className="muted" role="status">
          {slot.reason}
          <button type="button" className="g-more" onClick={() => setSlot(null)}>
            知道了
          </button>
        </span>
      )}
      {err && (
        <span className="hw-open-text step-failed" role="status">
          {err}
        </span>
      )}
    </span>
  );
}

function Row({
  api,
  item,
  now,
  onPlanned,
}: {
  api: Api;
  item: HomeworkItem;
  now: number;
  onPlanned: () => void;
}) {
  const link = safeLink(item.url);
  const done = item.state === "submitted";
  return (
    <li className="t-row hw-row" data-testid="homework-item">
      <span className={`t-when ${item.state === "missing" || item.state === "soon" ? "hw-urgent" : ""}`}>
        {done ? `交于 ${stamp(item.submitted_at)}` : dueText(item.due_at, now)}
      </span>
      <span className="t-what">
        {link ? (
          <a href={link} target="_blank" rel="noreferrer noopener">
            {item.title}
          </a>
        ) : (
          item.title
        )}
        {done && (
          <span className={item.late ? "t-tag bad" : "t-tag ok"}>
            <span className="sr-only">，</span>
            {item.late ? "迟交" : "已交"}
          </span>
        )}
        <span className="t-todo">
          {[item.due_at ? `截止 ${stamp(item.due_at)}` : "", item.points !== null ? `${item.points} 分` : ""]
            .filter(Boolean)
            .join(" · ")}
        </span>
        {!done && link && <OpenButton api={api} item={item} />}
        {!done && <PlanButton api={api} item={item} onPlanned={onPlanned} />}
      </span>
      <span className="t-from">{courseOf(item)}</span>
    </li>
  );
}

function Group({
  title,
  items,
  testId,
  api,
  now,
  empty,
  onPlanned,
}: {
  title: string;
  items: HomeworkItem[];
  testId: string;
  api: Api;
  now: number;
  empty?: string;
  onPlanned: () => void;
}) {
  if (items.length === 0 && !empty) return null;
  return (
    <div className="t-section" data-testid={testId}>
      <h2>{title}</h2>
      {items.length === 0 ? (
        <p className="muted hw-empty">{empty}</p>
      ) : (
        <ul>
          {items.map((h) => (
            <Row key={h.id} api={api} item={h} now={now} onPlanned={onPlanned} />
          ))}
        </ul>
      )}
    </div>
  );
}

type Check = "idle" | "asking" | "updated" | "slow" | "failed";
const CHECK_TEXT: Record<Check, string> = {
  idle: "",
  asking: "正在问 Canvas…",
  updated: "已经是 Canvas 最新的记录",
  slow: "Canvas 还没回，过一会儿再刷新看看",
  failed: "没能让 Canvas 同步",
};

/**
 * Waits for the sync jobs this click queued (not just any newer record: a scheduled sync
 * that finished earlier must not count). All succeeded: "updated"; one dead: "failed";
 * still running after `limitMs`: "slow"; `alive()` false: null.
 */
export async function waitForJobs(
  jobIds: string[],
  loadJob: (id: string) => Promise<Job>,
  alive: () => boolean,
  {
    intervalMs = CHECK_MS,
    limitMs = CHECK_LIMIT_MS,
    sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
    now = () => Date.now(),
  } = {},
): Promise<"updated" | "failed" | "slow" | null> {
  const deadline = now() + limitMs;
  const left = new Set(jobIds);
  while (now() < deadline) {
    await sleep(intervalMs);
    if (!alive()) return null;
    for (const id of [...left]) {
      try {
        const job = await loadJob(id);
        if (job.status === "dead") return alive() ? "failed" : null;
        if (job.status === "succeeded") left.delete(id);
      } catch {
        // try again on the next round
      }
    }
    if (!alive()) return null;
    if (left.size === 0) return "updated";
  }
  return "slow";
}

const WEEK_PARTS = [
  { key: "on_time", label: "按时", cls: "wk-ok" },
  { key: "late", label: "迟交", cls: "wk-late" },
  { key: "missing", label: "缺交", cls: "wk-miss" },
  { key: "open", label: "还没交", cls: "wk-open" },
] as const;

/** "按时 3 · 迟交 1 · 缺交 0 · 还没交 2", leaving out what is 0 except 按时. */
export function weekText(w: HomeworkWeek): string {
  const parts = WEEK_PARTS.filter((p) => p.key === "on_time" || w[p.key] > 0).map(
    (p) => `${p.label} ${w[p.key]}`,
  );
  return parts.join(" · ");
}

/** "11/16 那周" or "这周" for the last one. */
export function weekLabel(w: HomeworkWeek, isThisWeek: boolean): string {
  if (isThisWeek) return "这周";
  const [, m, d] = w.start.split("-").map(Number);
  return `${m}/${d} 那周`;
}

/**
 * 这几周交作业情况 (T-0069): this week's counts as one line, and a stacked bar per week
 * (oldest first) so the trend shows at a glance. Status colours with a legend and a
 * hover title on each segment; the line and each bar's label say the same in words.
 */
export function WeeksStrip({ weeks }: { weeks: HomeworkWeek[] }) {
  if (weeks.length === 0) return null;
  const most = Math.max(1, ...weeks.map((w) => w.on_time + w.late + w.missing + w.open));
  const last = weeks[weeks.length - 1];
  return (
    <div className="wk" data-testid="homework-weeks">
      <p className="wk-now">
        <span className="wk-title">这周</span> {weekText(last)}
      </p>
      <div className="wk-bars" role="list">
        {weeks.map((w, i) => {
          const label = weekLabel(w, i === weeks.length - 1);
          const total = w.on_time + w.late + w.missing + w.open;
          return (
            <div className="wk-col" role="listitem" key={w.start} aria-label={`${label}：${weekText(w)}`}>
              <div className={total ? "wk-bar" : "wk-bar wk-empty"} style={{ height: `${(total / most) * 100}%` }}>
                {WEEK_PARTS.filter((p) => w[p.key] > 0).map((p) => (
                  <span
                    key={p.key}
                    className={`wk-seg ${p.cls}`}
                    style={{ flexGrow: w[p.key] }}
                    title={`${label} ${p.label} ${w[p.key]} 份`}
                  />
                ))}
              </div>
              <span className="wk-label">{label}</span>
            </div>
          );
        })}
      </div>
      <p className="wk-legend" aria-hidden="true">
        {WEEK_PARTS.map((p) => (
          <span key={p.key}>
            <i className={`wk-dot ${p.cls}`} />
            {p.label}
          </span>
        ))}
      </p>
    </div>
  );
}

/** 作业 (ADR 0044): what is missing, due soon and handed in. Submitted = Canvas says so. */
export function HomeworkView({ api, onBoard }: { api: Api; onBoard?: (b: HomeworkBoard) => void }) {
  const [board, setBoard] = useState<HomeworkBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<Check>("idle");
  const [weeks, setWeeks] = useState<HomeworkWeek[]>([]);
  const alive = useRef(true);

  const show = useCallback(
    (b: HomeworkBoard) => {
      if (!alive.current) return;
      setBoard(b);
      setError(null);
      onBoard?.(b);
    },
    [onBoard],
  );

  const latest = useRef(0);
  const reload = useCallback(async () => {
    const ticket = ++latest.current; // an older, slower answer must not undo a newer one
    try {
      const b = await api.homework();
      if (ticket === latest.current) show(b);
    } catch (err) {
      if (alive.current && ticket === latest.current)
        setError(err instanceof ApiError ? `（${err.status}）${err.detail}` : String(err));
    }
  }, [api, show]);

  useEffect(() => {
    let live = true;
    api
      .homeworkWeeks(4, browserZone())
      .then((r) => live && setWeeks(r.weeks))
      .catch(() => undefined); // the board above still answers what to do
    return () => {
      live = false;
    };
  }, [api, board?.synced_at]);

  useEffect(() => {
    alive.current = true;
    void reload();
    const timer = window.setInterval(() => void reload(), 5 * 60 * 1000);
    return () => {
      alive.current = false;
      window.clearInterval(timer);
    };
  }, [reload]);

  /** Ask Canvas to sync, wait for that sync to finish, then reload once. */
  const askCanvas = async () => {
    setCheck("asking");
    let jobIds: string[];
    try {
      jobIds = (await api.checkHomework()).job_ids;
    } catch {
      if (alive.current) setCheck("failed");
      return;
    }
    const outcome = await waitForJobs(jobIds, (id) => api.job(id), () => alive.current);
    if (!outcome) return;
    await reload();
    if (alive.current) setCheck(outcome);
  };

  if (error)
    return (
      <p className="error" role="alert">
        没能读到作业：{error}
      </p>
    );
  if (!board) return <p>加载中…</p>;
  if (!board.canvas) return <p className="muted">还没有连接 Canvas。连上以后，这里会列出每份作业交没交。</p>;

  const replan = () => void reload();
  const now = Date.now();
  const left = board.missing.length + board.soon.length + board.week.length;
  return (
    <div className="today homework" data-testid="homework">
      <p className="headline" data-testid="homework-headline">
        {left === 0
          ? "这周没有要交的作业。"
          : `还有 ${left} 份没交${board.missing.length ? `，其中 ${board.missing.length} 份缺交` : ""}。`}
      </p>
      <WeeksStrip weeks={weeks} />
      <p className="hw-check">
        <button type="button" onClick={() => void askCanvas()} disabled={check === "asking"}>
          我交了，查一下
        </button>
        <span className="muted" role="status" data-testid="homework-check">
          {CHECK_TEXT[check] ||
            (board.synced_at ? `Canvas 记录更新于 ${stamp(board.synced_at)}` : "还没从 Canvas 同步过")}
        </span>
      </p>
      <Group onPlanned={replan} title="缺交" items={board.missing} testId="homework-missing" api={api} now={now} />
      <Group onPlanned={replan}
        title="24 小时内要交"
        items={board.soon}
        testId="homework-soon"
        api={api}
        now={now}
        empty="24 小时内没有要交的"
      />
      <Group onPlanned={replan} title="这周要交" items={board.week} testId="homework-week" api={api} now={now} />
      <Group onPlanned={replan}
        title="最近交了"
        items={board.submitted}
        testId="homework-submitted"
        api={api}
        now={now}
        empty="最近 7 天 Canvas 里没有提交记录"
      />
      <p className="t-foot">
        <span>只有 Canvas 记下提交时间才算交了。作业内容和提交都由你自己完成。</span>
      </p>
    </div>
  );
}

export type FirstKind = "soon" | "missing" | "plan";
export interface First {
  kind: FirstKind;
  item: HomeworkItem;
  text: string;
}

/**
 * 先做这个 (T-0068): the one homework thing to do now, or null (then 开始学习 is the answer).
 * In order: due within 24 h and not handed in; marked missing by Canvas; due this week with
 * no time set aside yet. Computed from the board, no model.
 */
export function firstThing(board: HomeworkBoard | null, now: number): First | null {
  if (!board) return null;
  const course = (h: HomeworkItem) => (courseOf(h) ? `（${courseOf(h)}）` : "");
  const soon = board.soon[0];
  if (soon) return { kind: "soon", item: soon, text: reminderText(soon, now) };
  const missing = board.missing[0];
  if (missing)
    return {
      kind: "missing",
      item: missing,
      text: `缺交：${missing.title}${course(missing)}${missing.due_at ? `，${dueText(missing.due_at, now).replace("过了", "已过")}` : ""}`,
    };
  const unplanned = board.week.find((h) => !h.planned);
  if (unplanned)
    return {
      kind: "plan",
      item: unplanned,
      text: `${dueText(unplanned.due_at, now)}：${unplanned.title}${course(unplanned)}，还没排时间`,
    };
  return null;
}

/** The top of 今日: one homework thing to do now, with its button (先做这个, T-0068). */
export function FirstThing({
  api,
  board,
  onOpen,
  onPlanned,
}: {
  api: Api;
  board: HomeworkBoard | null;
  onOpen: () => void;
  onPlanned: () => void;
}) {
  // What was just put on 日程 stays said after the board moves on to the next pick.
  const [done, setDone] = useState("");
  const first = firstThing(board, Date.now());
  const link = first ? safeLink(first.item.url) : null;
  const planned = (title: string) => (block: PlannedTime) => {
    setDone(`已排进日程：${title} ${blockText(block)}`);
    onPlanned();
  };
  if (!first && !done) return null;
  return (
    <>
      {done && (
        <p className="hw-first-done" role="status" data-testid="first-done">
          {done}
        </p>
      )}
      {first && (
    // keyed by the item, so a new first thing starts with fresh buttons
    <div key={first.item.id} className={`hw-first hw-first-${first.kind}`} data-testid="first-thing">
      <p className="hw-first-head">
        <span className="hw-first-label">先做这个</span>
        <span data-testid={first.kind === "soon" ? "homework-reminder" : undefined}>{first.text}</span>
      </p>
      <p className="hw-first-actions">
        {first.kind === "plan" ? (
          <PlanButton api={api} item={first.item} onPlanned={planned(first.item.title)} />
        ) : (
          link && <OpenButton api={api} item={first.item} />
        )}
        <button type="button" className="g-more" onClick={onOpen}>
          去作业页
        </button>
      </p>
    </div>
      )}
    </>
  );
}
