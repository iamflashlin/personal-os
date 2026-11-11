import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { type Api, ApiError, type EntrySummary, type SummariesStatus } from "./api";

/** What each summary state looks like when there is no gist to show. */
export const SUMMARY_LABEL: Record<EntrySummary["status"], string> = {
  pending: "总结中…",
  ok: "",
  skipped_sensitive: "未发送给 AI（可能含验证码或重置密码）",
  skipped_unreadable: "无法读取正文，未总结",
  failed: "总结失败",
};

/** Micro-USD (integer) as dollars, e.g. 1234567 -> "$1.23". */
export function formatUsd(microUsd: number): string {
  return `$${(Math.max(0, microUsd) / 1_000_000).toFixed(2)}`;
}

/** One summary line. All text is rendered by React, so mail content is never HTML. */
export function SummaryLine({
  summary,
  hideGist = false,
}: {
  summary: EntrySummary | null | undefined;
  hideGist?: boolean;
}) {
  if (!summary) return null;
  if (summary.status !== "ok") {
    return (
      <p className="muted summary" data-testid="summary-state">
        {SUMMARY_LABEL[summary.status]}
      </p>
    );
  }
  if (hideGist && !summary.action_needed && !summary.deadline_text) return null;
  return (
    <p className="summary" data-testid="summary">
      {!hideGist && (
        <>
          <span className="badge ai">AI</span> {summary.gist}
        </>
      )}
      {summary.action_needed && (
        <>
          {" "}
          <span className="badge submission-缺交">需处理</span> {summary.action}
        </>
      )}
      {summary.deadline_text && <span className="muted">（截止：{summary.deadline_text}）</span>}
    </p>
  );
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return `操作失败（${err.status}）：${err.detail}`;
  return String(err);
}

/** 连接 page card: the DeepSeek key, this month's spend, why summaries are blocked. */
export function AiCard({ api, onChanged }: { api: Api; onChanged?: () => void }) {
  const [status, setStatus] = useState<SummariesStatus | null>(null);
  const [error, setError] = useState<string | null>(null); // from a button the user pressed
  const [pollError, setPollError] = useState<string | null>(null); // from the 10 s refresh
  const [busy, setBusy] = useState(false);
  const field = useRef<HTMLInputElement>(null);

  const reload = useCallback(async () => {
    try {
      setStatus(await api.summariesStatus());
      setPollError(null); // the Hub answers again: stop showing the old failure
    } catch (err) {
      setPollError(`连不上 Hub：${errorText(err)}`);
    }
  }, [api]);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), 10_000);
    return () => window.clearInterval(timer);
  }, [reload]);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
      await reload();
      onChanged?.();
    }
  };

  const save = (event: FormEvent) => {
    event.preventDefault();
    const input = field.current;
    const secret = input?.value.trim() ?? "";
    if (!input || !secret) return;
    input.value = ""; // the key leaves the page at once; it is never shown again
    void act(async () => {
      await api.setModelKey(secret);
      await api.runSummaries();
    });
  };

  const usage = status?.usage;
  return (
    <section data-testid="ai-card">
      <h2>AI 邮件总结（DeepSeek）</h2>
      <p className="muted">
        系统用 DeepSeek 总结最近 14 天的邮件：这封信是什么、要不要你做什么、有没有截止时间。
        验证码和重置密码类邮件不会发出去。key 只存进 Windows 凭据管理器，页面不会再显示它。
      </p>
      {(error || pollError) && (
        <p className="error" role="alert">
          {error ?? pollError}
        </p>
      )}
      {usage && (
        <p data-testid="ai-usage">
          {usage.key_set ? "已设置 key" : "还没有设置 key"} · 本月已用{" "}
          {formatUsd(usage.spent_micro_usd)} / {formatUsd(usage.budget_micro_usd)}（
          {usage.calls} 次）
        </p>
      )}
      {status?.notice && (
        <p className="error" data-testid="ai-notice">
          {status.notice}
          {status.pending > 0 && `，${status.pending} 封邮件在排队`}
        </p>
      )}
      <form className="new-memory" onSubmit={save} aria-label="设置 DeepSeek key" autoComplete="off">
        <label className="grow">
          <span className="label">DeepSeek API key（不会再显示）</span>
          {/* Text masked by CSS, not a password field: browsers would offer to save it. */}
          <input
            ref={field}
            type="text"
            className="masked"
            autoComplete="off"
            spellCheck={false}
            data-lpignore="true"
            data-1p-ignore="true"
            placeholder="sk-…"
            data-testid="ai-key"
            required
          />
        </label>
        <button type="submit" className="primary" disabled={busy}>
          {usage?.key_set ? "更换 key" : "保存 key"}
        </button>
        <button
          type="button"
          onClick={() => void act(() => api.runSummaries())}
          disabled={busy || !usage?.key_set}
        >
          现在总结
        </button>
        {usage?.key_set && (
          <button type="button" onClick={() => void act(() => api.deleteModelKey())} disabled={busy}>
            删除 key
          </button>
        )}
      </form>
    </section>
  );
}
