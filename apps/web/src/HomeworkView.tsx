import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ActionRun,
  type Api,
  ApiError,
  type HomeworkBoard,
  type HomeworkItem,
  type Job,
  newKey,
} from "./api";
import { safeLink } from "./ConnectionsView";
import { courseIn } from "./GpaView";
import { pollUntil } from "./poll";
import { STEP_WORD, stepReason } from "./StudyCard";

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

function Row({ api, item, now }: { api: Api; item: HomeworkItem; now: number }) {
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
}: {
  title: string;
  items: HomeworkItem[];
  testId: string;
  api: Api;
  now: number;
  empty?: string;
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
            <Row key={h.id} api={api} item={h} now={now} />
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

/** 作业 (ADR 0044): what is missing, due soon and handed in. Submitted = Canvas says so. */
export function HomeworkView({ api, onBoard }: { api: Api; onBoard?: (b: HomeworkBoard) => void }) {
  const [board, setBoard] = useState<HomeworkBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState<Check>("idle");
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

  const reload = useCallback(async () => {
    try {
      show(await api.homework());
    } catch (err) {
      if (alive.current) setError(err instanceof ApiError ? `（${err.status}）${err.detail}` : String(err));
    }
  }, [api, show]);

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

  const now = Date.now();
  const left = board.missing.length + board.soon.length + board.week.length;
  return (
    <div className="today homework" data-testid="homework">
      <p className="headline" data-testid="homework-headline">
        {left === 0
          ? "这周没有要交的作业。"
          : `还有 ${left} 份没交${board.missing.length ? `，其中 ${board.missing.length} 份缺交` : ""}。`}
      </p>
      <p className="hw-check">
        <button type="button" onClick={() => void askCanvas()} disabled={check === "asking"}>
          我交了，查一下
        </button>
        <span className="muted" role="status" data-testid="homework-check">
          {CHECK_TEXT[check] ||
            (board.synced_at ? `Canvas 记录更新于 ${stamp(board.synced_at)}` : "还没从 Canvas 同步过")}
        </span>
      </p>
      <Group title="缺交" items={board.missing} testId="homework-missing" api={api} now={now} />
      <Group
        title="24 小时内要交"
        items={board.soon}
        testId="homework-soon"
        api={api}
        now={now}
        empty="24 小时内没有要交的"
      />
      <Group title="这周要交" items={board.week} testId="homework-week" api={api} now={now} />
      <Group
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

/** The 今日 reminder: the nearest unsubmitted homework due within 24 h, if any. */
export function HomeworkReminder({ item, onOpen }: { item: HomeworkItem | null; onOpen: () => void }) {
  if (!item) return null;
  return (
    <p className="hw-reminder" data-testid="homework-reminder">
      <span>{reminderText(item, Date.now())}</span>
      <button type="button" className="g-more" onClick={onOpen}>
        去作业页
      </button>
    </p>
  );
}
