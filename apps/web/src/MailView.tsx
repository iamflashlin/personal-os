import { useCallback, useEffect, useRef, useState } from "react";
import { type Api, ApiError, type EmailSummary, type SyncedItem } from "./api";
import { SUMMARY_LABEL } from "./Summary";

const MAIL_LIMIT = 100;
const MAX_SUMMARY_IDS = 200; // the Hub's cap per request (summaries/api.py)
/** Summaries from older prompts hold long sentences, not short titles. */
export const TITLE_PROMPT_VERSION = 2;
const REFRESH_MS = 15_000;

export interface MailRow {
  item: SyncedItem;
  source: string;
  summary?: EmailSummary;
}

const IMPORTANCE: Record<EmailSummary["importance"], { text: string; className: string }> = {
  high: { text: "重要", className: "badge submission-缺交" },
  normal: { text: "", className: "" },
  low: { text: "次要", className: "badge" },
};

/** What the list shows as the line: the AI title when there is one, else the subject. */
export function mailTitle(row: MailRow): string {
  const s = row.summary;
  if (s && s.status === "ok" && s.gist && s.prompt_version >= TITLE_PROMPT_VERSION) {
    return s.gist;
  }
  return row.item.title || "（无主题）";
}

/** Valuable mail first-class; mail the AI found worthless goes behind one line. */
export function splitMail(rows: MailRow[]): { shown: MailRow[]; collapsed: MailRow[] } {
  const shown: MailRow[] = [];
  const collapsed: MailRow[] = [];
  for (const row of rows) {
    const s = row.summary;
    (s && s.status === "ok" && s.low_value ? collapsed : shown).push(row);
  }
  return { shown, collapsed };
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return `（${err.status}）${err.detail}`;
  return String(err);
}

function when(item: SyncedItem): string {
  if (!item.starts_at) return "";
  return new Date(item.starts_at).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** An opened mail: the distilled points first, then what to do, then the original. */
export function MailDetail({ row }: { row: MailRow }) {
  const { item, summary } = row;
  const data = item.data as { from_name?: string; from_address?: string };
  const ok = summary?.status === "ok";
  return (
    <div className="mail-detail" data-testid="mail-detail">
      {ok && summary.points.length > 0 && (
        <ul className="points" data-testid="mail-points">
          {summary.points.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      )}
      {ok && summary.action_needed && (
        <p>
          <strong>要做：</strong>
          {summary.action}
          {summary.deadline_text && `（截止：${summary.deadline_text}）`}
        </p>
      )}
      <details open={!ok} data-testid="mail-original">
        <summary className="muted">
          原文 · {data.from_name || data.from_address || ""} · {item.title}
        </summary>
        <p className="original">{item.body}</p>
      </details>
    </div>
  );
}

export function MailLine({ row, initiallyOpen = false }: { row: MailRow; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const { item, summary } = row;
  const data = item.data as { from_name?: string; from_address?: string; seen?: boolean };
  const ok = summary?.status === "ok";
  const level = ok ? IMPORTANCE[summary.importance] : null;
  return (
    <li className={`memory mail-line${data.seen ? "" : " unread"}`} data-testid="mail-line">
      <button
        type="button"
        className="mail-head"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {level?.text && <span className={level.className}>{level.text}</span>}
        <span className="memory-body" data-testid="mail-title">
          {mailTitle(row)}
        </span>
        {ok && summary.action_needed && <span className="badge submission-缺交">需处理</span>}
        {!data.seen && <span className="badge unread">未读</span>}
        <span className="muted">{when(item)}</span>
      </button>
      {summary && !ok && (
        <p className="muted summary" data-testid="summary-state">
          {SUMMARY_LABEL[summary.status]}
        </p>
      )}
      {open && <MailDetail row={row} />}
    </li>
  );
}

export function MailView({ api }: { api: Api }) {
  const [rows, setRows] = useState<MailRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCollapsed, setShowCollapsed] = useState(false);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const boxes = (await api.integrations()).filter((i) => i.kind === "email");
      const found = (
        await Promise.allSettled(
          boxes.map(async (i) =>
            (await api.recentMail(i, MAIL_LIMIT)).map((item) => ({ item, source: i.name })),
          ),
        )
      ).flatMap((r) => (r.status === "fulfilled" ? r.value : []));
      found.sort((a, b) => (b.item.starts_at ?? "").localeCompare(a.item.starts_at ?? ""));
      // Newest first, so the cap keeps the mail on top of the list.
      const summaries = await api
        .emailSummaries(found.slice(0, MAX_SUMMARY_IDS).map((r) => r.item.id))
        .catch(() => null);
      if (ticket !== latest.current) return;
      setRows((previous) => {
        const known = summaries
          ? new Map(summaries.map((s) => [s.item_id, s]))
          : new Map((previous ?? []).flatMap((r) => (r.summary ? [[r.item.id, r.summary]] : [])));
        return found.map((r) => ({ ...r, summary: known.get(r.item.id) }));
      });
      setError(null);
    } catch (err) {
      // Keep what is shown (and which mails are open); just say the refresh failed.
      if (ticket === latest.current) setError(`连不上 Hub：${errorText(err)}`);
    }
  }, [api]);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [reload]);

  const alert = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );
  if (rows === null) return alert || <p>加载中…</p>;
  if (rows.length === 0) return <p className="muted">还没有邮件。在“连接”页接入邮箱后，这里会列出整理好的邮件。</p>;

  const { shown, collapsed } = splitMail(rows);
  return (
    <section data-testid="mail-view">
      {alert}
      <h2>邮件（最新 {MAIL_LIMIT} 封）</h2>
      <p className="muted">每行是 AI 写的一句话：什么事、什么时候截止。点开先看要点，再看原文。</p>
      <ul className="memories">
        {shown.map((r) => (
          <MailLine key={r.item.id} row={r} />
        ))}
      </ul>
      {collapsed.length > 0 && (
        <>
          <button
            type="button"
            className="collapsed-toggle"
            data-testid="mail-collapsed"
            onClick={() => setShowCollapsed((v) => !v)}
          >
            {showCollapsed ? "收起" : `已收起 ${collapsed.length} 封没有价值的邮件`}
          </button>
          {showCollapsed && (
            <ul className="memories muted">
              {collapsed.map((r) => (
                <MailLine key={r.item.id} row={r} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
