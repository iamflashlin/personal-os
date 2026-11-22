import { useCallback, useEffect, useRef, useState } from "react";
import { type Api, ApiError, newKey, type StepRun, type StudyPlan, type StudySession } from "./api";
import { shortCode } from "./GpaView";

const POLL_MS = 1500;
const POLL_LIMIT_MS = 60_000;

/** One word per step state, as the user reads it. */
export const STEP_WORD: Record<StepRun["status"], string> = {
  dispatched: "正在打开…",
  succeeded: "已打开",
  failed: "没打开成功",
  needs_user: "需要你处理",
  cancelled: "取消了",
  lost: "电脑助手断开了",
  not_sent: "没发出去",
};

/** "上次：11月20日 复习 3.3 · 学完了" (or 没点学完). */
export function lastText(last: StudyPlan["last"]): string {
  if (!last) return "";
  const day = new Date(last.started_at).toLocaleDateString("zh-CN", { month: "long", day: "numeric" });
  return `上次：${day} ${last.title} · ${last.finished_at ? "学完了" : "没点学完"}`;
}

export function settled(s: StudySession): boolean {
  return s.steps.every((st) => st.status !== "dispatched");
}

/** The refusal shown when 开始 fails: the agent being offline gets its own sentence,
 * pointing to where the links are on this page (课程) or on another one (今日). */
export function startError(err: unknown, onCoursePage = true): string {
  if (err instanceof ApiError && err.status === 503) {
    const where = onCoursePage ? "下面的课程内容里" : "「课程」页里";
    return `电脑助手没有连上，所以没法替你打开。资料链接在${where}，也可以自己点开。`;
  }
  if (err instanceof ApiError) return `（${err.status}）${err.detail}`;
  return String(err);
}

/** The agent reports in English; the common reasons are said in plain Chinese. */
export function stepReason(message: string): string {
  if (/^no window titled .* appeared within/.test(message))
    return "页面可能打开了，但没认出它的窗口（比如 Canvas 要你先登录）";
  if (/^no VS Code window/.test(message)) return "VS Code 没有在时间内打开";
  if (/not on PATH/.test(message)) return "这台电脑上找不到 VS Code";
  if (message === "the agent disconnected before reporting a result")
    return "电脑助手中途断开了，不知道打开没有";
  return message;
}

/** A plan that could not be loaded: the Hub's own words, never the agent sentence. */
export function loadError(err: unknown): string {
  if (err instanceof ApiError) return `没能读到学习计划（${err.status}）${err.detail}`;
  return `没能读到学习计划：${String(err)}`;
}

export interface PollOptions {
  intervalMs?: number;
  limitMs?: number;
  isVisible?: () => boolean;
  now?: () => number;
}

/**
 * Asks for the session every `intervalMs` until each step is answered, `limitMs` has
 * passed since the start, or `stop()` is called. Skips a tick while the tab is hidden.
 * Answers that arrive after stop() are dropped.
 */
export function pollSession(
  fetchSession: () => Promise<StudySession>,
  onUpdate: (s: StudySession) => void,
  {
    intervalMs = POLL_MS,
    limitMs = POLL_LIMIT_MS,
    isVisible = () => document.visibilityState === "visible",
    now = () => Date.now(),
  }: PollOptions = {},
): () => void {
  const startedAt = now();
  let stopped = false;
  const stop = () => {
    stopped = true;
    clearInterval(timer);
  };
  const timer = setInterval(() => {
    if (now() - startedAt > limitMs) return stop();
    if (!isVisible()) return;
    fetchSession()
      .then((s) => {
        if (stopped) return;
        onUpdate(s);
        if (settled(s)) stop();
      })
      .catch(() => undefined);
  }, intervalMs);
  return stop;
}

type Stage = "plan" | "confirm" | "running";

/**
 * 开始学习: what to study next, and one click to open it on the PC (ADR 0042).
 * `code` null: the course with the nearest exam (今日); otherwise that course (课程).
 * Give it `key={code}` so a course switch starts fresh (a new Idempotency-Key too).
 */
export function StudyCard({ api, code }: { api: Api; code: string | null }) {
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [session, setSession] = useState<StudySession | null>(null);
  const [stage, setStage] = useState<Stage>("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  // One per attempt to start: reused on a retry, so a retry never opens things twice.
  const key = useRef(newKey());
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    try {
      if (code === null && (await api.courseMaps()).length === 0) {
        if (alive.current) setMissing(true); // no course map yet (and no 404 to log)
        return;
      }
      const p = code === null ? await api.studyNext() : await api.studyPlan(code);
      if (!alive.current) return;
      setPlan(p);
      setMissing(false);
      setError(null);
    } catch (err) {
      if (!alive.current) return;
      if (err instanceof ApiError && err.status === 404) setMissing(true);
      else setError(loadError(err));
    }
  }, [api, code]);

  useEffect(() => {
    void load();
  }, [load]);

  // Follow the steps until the agent has answered each one: one poller per session.
  const sessionId = session?.id ?? null;
  const pending = session !== null && session.status === "started" && !settled(session);
  useEffect(() => {
    if (sessionId === null || !pending) return;
    return pollSession(
      () => api.studySession(sessionId),
      (s) => {
        if (alive.current) setSession((cur) => (cur?.id === s.id ? s : cur));
      },
    );
  }, [api, sessionId, pending]);

  if (missing) return null; // no course map yet: nothing to suggest
  // On 今日 a plan that failed to load shows nothing; 课程 says why.
  if (!plan) return error && code !== null ? <p className="error">{error}</p> : null;

  async function start() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      setSession(await api.startStudy(plan.course_code, key.current));
      setStage("running");
    } catch (err) {
      setError(startError(err, code !== null));
      setStage("plan");
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!session) return;
    setBusy(true);
    setError(null);
    try {
      await api.finishStudy(session.id, session.version);
      key.current = newKey();
      setSession(null);
      setStage("plan");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? `（${err.status}）${err.detail}` : String(err));
    } finally {
      setBusy(false);
    }
  }

  const course = shortCode(plan.course_code);
  return (
    <section className="study" data-testid="study-card" aria-label="开始学习">
      {stage !== "running" && (
        <>
          <p className="study-next">
            <span className="study-course">{course}</span>
            <strong>{plan.next.title}</strong>
            {plan.next.page !== null && <span className="muted"> · 讲义第 {plan.next.page} 页</span>}
          </p>
          <p className="study-why muted">{plan.next.why}</p>
          {plan.last && <p className="study-last muted">{lastText(plan.last)}</p>}
        </>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {stage === "plan" && (
        <button
          type="button"
          className="primary"
          disabled={plan.steps.length === 0}
          onClick={() => setStage("confirm")}
        >
          开始学习
        </button>
      )}
      {stage === "plan" && plan.steps.length === 0 && (
        <p className="muted">这一节还没有能打开的资料链接。</p>
      )}
      {stage === "confirm" && (
        <div className="study-confirm" data-testid="study-confirm">
          <p>会在电脑上打开：</p>
          <ul>
            {plan.steps.map((s, i) => (
              <li key={`${i}-${s.label}`}>{s.label}</li>
            ))}
          </ul>
          <div className="study-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => void start()}>
              确认打开
            </button>
            <button type="button" disabled={busy} onClick={() => setStage("plan")}>
              取消
            </button>
          </div>
        </div>
      )}
      {stage === "running" && session && (
        <div className="study-run" data-testid="study-run">
          <p className="study-next">
            <span className="study-course">{course}</span>
            <strong>{session.next.title}</strong>
          </p>
          <ul className="study-steps">
            {session.steps.map((s, i) => (
              <li key={`${i}-${s.label}`} className={`step-${s.status}`}>
                <span>{s.label}</span>
                <span className="study-word">{STEP_WORD[s.status]}</span>
                {s.status !== "succeeded" && s.message && (
                  <span className="muted"> {stepReason(s.message)}</span>
                )}
              </li>
            ))}
          </ul>
          <div className="study-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => void finish()}>
              学完了
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
