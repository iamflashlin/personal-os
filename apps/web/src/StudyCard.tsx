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

/** The refusal shown when 开始 fails: the agent being offline gets its own sentence. */
export function startError(err: unknown): string {
  if (err instanceof ApiError && err.status === 503)
    return "电脑助手没有连上，所以没法替你打开。资料链接在下面的课程页里，也可以自己点开。";
  if (err instanceof ApiError) return `（${err.status}）${err.detail}`;
  return String(err);
}

type Stage = "plan" | "confirm" | "running";

/**
 * 开始学习: what to study next, and one click to open it on the PC (ADR 0042).
 * `code` null: the course with the nearest exam (今日); otherwise that course (课程).
 */
export function StudyCard({ api, code }: { api: Api; code: string | null }) {
  const [plan, setPlan] = useState<StudyPlan | null>(null);
  const [session, setSession] = useState<StudySession | null>(null);
  const [stage, setStage] = useState<Stage>("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const key = useRef(newKey());

  const load = useCallback(async () => {
    try {
      if (code === null && (await api.courseMaps()).length === 0) {
        setMissing(true); // no course map yet: nothing to suggest (and no 404 to log)
        return;
      }
      setPlan(code === null ? await api.studyNext() : await api.studyPlan(code));
      setMissing(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setMissing(true);
      else setError(startError(err));
    }
  }, [api, code]);

  useEffect(() => {
    setStage("plan");
    setSession(null);
    setError(null);
    void load();
  }, [load]);

  // Follow the steps until the agent has answered each one (only while the tab is shown).
  useEffect(() => {
    if (!session || settled(session) || session.status === "finished") return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - startedAt > POLL_LIMIT_MS) {
        window.clearInterval(timer);
        return;
      }
      api
        .studySession(session.id)
        .then((s) => {
          setSession(s);
          if (settled(s)) window.clearInterval(timer);
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [api, session]);

  if (missing) return null; // no course map yet: nothing to suggest
  if (!plan) return error ? <p className="error">{error}</p> : null;

  async function start() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    try {
      setSession(await api.startStudy(plan.course_code, key.current));
      setStage("running");
    } catch (err) {
      setError(startError(err));
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
      setError(startError(err));
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
            {plan.steps.map((s) => (
              <li key={s.label}>{s.label}</li>
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
                {s.status !== "succeeded" && s.message && <span className="muted"> {s.message}</span>}
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
