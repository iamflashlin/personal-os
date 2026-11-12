import { memo, useCallback, useEffect, useRef, useState } from "react";
import { ChatBox } from "./ChatBox";
import { type Api, ApiError, type EmailSummary, type SyncedItem } from "./api";
import { SUMMARY_LABEL } from "./Summary";

const MAIL_LIMIT = 1000; // every mail (the Hub's max per request); was 100 before history
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

export type MailFilter = "all" | "unread" | "action";

export const FILTERS: { key: MailFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "unread", label: "未读" },
  { key: "action", label: "需处理" },
];

function isUnread(row: MailRow): boolean {
  return !(row.item.data as { seen?: boolean }).seen;
}

function needsAction(row: MailRow): boolean {
  const s = row.summary;
  return !!s && s.status === "ok" && s.action_needed && !s.low_value;
}

/** The rows a filter shows, still newest first. */
export function filterMail(rows: MailRow[], filter: MailFilter): MailRow[] {
  if (filter === "unread") return rows.filter(isUnread);
  if (filter === "action") return rows.filter(needsAction);
  return rows;
}

export function countMail(rows: MailRow[]): Record<MailFilter, number> {
  return {
    all: rows.length,
    unread: rows.filter(isUnread).length,
    action: rows.filter(needsAction).length,
  };
}

/** Summaries for every row, asked for in chunks of the Hub's per-request cap. */
export async function summariesFor(api: Pick<Api, "emailSummaries">, ids: string[]): Promise<EmailSummary[]> {
  const chunks: string[][] = [];
  for (let i = 0; i < ids.length; i += MAX_SUMMARY_IDS) chunks.push(ids.slice(i, i + MAX_SUMMARY_IDS));
  return (await Promise.all(chunks.map((c) => api.emailSummaries(c)))).flat();
}

/** What the list shows as the line: the AI title when there is one, else the subject. */
export function mailTitle(row: MailRow): string {
  const s = row.summary;
  if (s && s.status === "ok" && s.gist && s.prompt_version >= TITLE_PROMPT_VERSION) {
    return s.gist;
  }
  return row.item.title || "（无主题）";
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

function MailLineView({ row, initiallyOpen = false }: { row: MailRow; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen);
  const { item, summary } = row;
  const data = item.data as { from_name?: string; from_address?: string; seen?: boolean };
  const ok = summary?.status === "ok";
  const level = ok ? (summary.low_value ? IMPORTANCE.low : IMPORTANCE[summary.importance]) : null;
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
  const [filter, setFilter] = useState<MailFilter>("all");
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);
  const busy = useRef(false); // a slow refresh is not stacked on by the next tick
  const rowsCapped = useRef(false);

  const reload = useCallback(async () => {
    if (busy.current || document.hidden) return; // no polling in a hidden tab
    busy.current = true;
    const ticket = ++latest.current;
    try {
      const boxes = (await api.integrations()).filter((i) => i.kind === "email");
      const fetched = await Promise.allSettled(
        boxes.map(async (i) =>
          (await api.recentMail(i, MAIL_LIMIT)).map((item) => ({ item, source: i.name })),
        ),
      );
      const found = fetched.flatMap((r) => (r.status === "fulfilled" ? r.value : []));
      rowsCapped.current = fetched.some(
        (r) => r.status === "fulfilled" && r.value.length >= MAIL_LIMIT,
      );
      found.sort((a, b) => (b.item.starts_at ?? "").localeCompare(a.item.starts_at ?? ""));
      const summaries = await summariesFor(
        api,
        found.map((r) => r.item.id),
      ).catch(() => null);
      if (ticket !== latest.current) return;
      setRows((previous) => {
        const known = summaries
          ? new Map(summaries.map((s) => [s.item_id, s]))
          : new Map((previous ?? []).flatMap((r) => (r.summary ? [[r.item.id, r.summary]] : [])));
        // Keep a row's object when its item and summary are unchanged, so memo(MailLine)
        // skips it: a refresh of ~1000 mails re-renders only what changed.
        const old = new Map((previous ?? []).map((r) => [r.item.id, r]));
        return found.map((r) => {
          const summary = known.get(r.item.id);
          const was = old.get(r.item.id);
          const same =
            was &&
            was.item.updated_at === r.item.updated_at &&
            was.item.version === r.item.version &&
            was.summary?.updated_at === summary?.updated_at;
          return same ? was : { ...r, summary };
        });
      });
      setError(null);
    } catch (err) {
      // Keep what is shown (and which mails are open); just say the refresh failed.
      if (ticket === latest.current) setError(`连不上 Hub：${errorText(err)}`);
    } finally {
      busy.current = false;
    }
  }, [api]);

  useEffect(() => {
    void reload();
    const timer = window.setInterval(() => void reload(), REFRESH_MS);
    const onShow = () => {
      if (!document.hidden) void reload();
    };
    document.addEventListener("visibilitychange", onShow);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onShow);
    };
  }, [reload]);

  const alert = error && (
    <p className="error" role="alert">
      {error}
    </p>
  );
  if (rows === null) return alert || <p>加载中…</p>;
  if (rows.length === 0) return <p className="muted">还没有邮件。在“连接”页接入邮箱后，这里会列出整理好的邮件。</p>;

  const counts = countMail(rows);
  const capped = rowsCapped.current;
  const shown = filterMail(rows, filter);
  // All mail in time order, newest first; low-value mail is only marked 次要 (the user,
  // 2026-11-11: "不要把那些无用的折叠起来，就跟正常的邮件按时间顺序放好").
  return (
    <section data-testid="mail-view">
      {alert}
      <ChatBox api={api} />
      <h2>
        邮件（共 {capped ? "至少 " : ""}
        {counts.all} 封，未读 {counts.unread} 封）
      </h2>
      <div className="mail-filters" role="group" aria-label="筛选邮件">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            className={filter === f.key ? "active" : ""}
            data-testid={`mail-filter-${f.key}`}
            onClick={() => setFilter(f.key)}
          >
            {f.label} {counts[f.key]}
          </button>
        ))}
      </div>
      <p className="muted">每行是 AI 写的一句话：什么事、什么时候截止。点开先看要点，再看原文。</p>
      {shown.length === 0 && <p className="muted">这里没有邮件。</p>}
      <ul className="memories">
        {shown.map((r) => (
          <MailLine key={r.item.id} row={r} />
        ))}
      </ul>
    </section>
  );
}

/** Rows keep their identity across refreshes when nothing changed, so lines do not re-render. */
export const MailLine = memo(MailLineView);
