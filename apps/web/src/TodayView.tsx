import { useCallback, useEffect, useRef, useState } from "react";
import { type Api, ApiError, type EntrySummary, type TodayEntry, type TodayView as Today } from "./api";
import { safeLink } from "./ConnectionsView";
import { shortCode } from "./GpaView";
import { StudyCard } from "./StudyCard";
import { SUMMARY_LABEL } from "./Summary";

function errorText(err: unknown): string {
  if (err instanceof ApiError) return `（${err.status}）${err.detail}`;
  return String(err);
}

/** The browser's IANA zone, so "today" is the user's day, not the server's. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

/** 重要 / 次要 for a mail on 今日: the same rule as the 邮件 page. Low-value mail is never 重要. */
export function summaryBadges(s: EntrySummary | null | undefined): string[] {
  if (!s || s.status !== "ok") return [];
  if (s.low_value || s.importance === "low") return ["次要"];
  return s.importance === "high" ? ["重要"] : [];
}

/** The right-hand column of a row: the course as a short name when the note names one
 * ("F26 MATH D001A 49 Calculus I" -> "MATH 1A"), else the note itself (a sender, a calendar). */
export function origin(entry: Pick<TodayEntry, "note" | "source">): string {
  const m = /\b([A-Z]{2,5})\s+([A-Z]?\d{3,4}[A-Z]?)\b/.exec(entry.note);
  return m ? shortCode(`${m[1]} ${m[2]}`) : entry.note || entry.source;
}

/** The single tag of a row, never one its section title already says (no 未读 under
 * 未读邮件, no 进行中 under 进行中, no 缺交 under 缺交 / 逾期). Mail shows only how much it
 * matters; other rows show their state (已提交, 已评分 …). */
export function rowTag(
  entry: TodayEntry,
  section: "mail" | "action" | "other",
  title: string,
): string {
  if (section === "action") return "";
  const tag = section === "mail" ? (summaryBadges(entry.summary)[0] ?? "") : entry.badge;
  return tag && !title.includes(tag) ? tag : "";
}

/** The quiet line under a mail's title: what it asks for and its deadline, either alone. */
export function quietLine(s: EntrySummary | null | undefined): string {
  if (!s || s.status !== "ok") return "";
  return [s.action_needed ? s.action : "", s.deadline_text ? `截止 ${s.deadline_text}` : ""]
    .filter(Boolean)
    .join("，");
}

function whenText(entry: TodayEntry, withDay: boolean): string {
  if (!entry.at) return "";
  const at = new Date(entry.at);
  if (entry.all_day) {
    // All-day items are stored at UTC midnight of their day.
    return withDay
      ? at.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric", timeZone: "UTC" })
      : "全天";
  }
  return at.toLocaleString("zh-CN", {
    ...(withDay ? { month: "numeric", day: "numeric" } : {}),
    hour: "2-digit",
    minute: "2-digit",
  });
}

const TAG_CLASS: Record<string, string> = {
  缺交: "t-tag bad",
  逾期: "t-tag bad",
  重要: "t-tag bad",
  已提交: "t-tag ok",
  已评分: "t-tag ok",
};

export function TodayRow({
  entry,
  withDay,
  section,
  title,
}: {
  entry: TodayEntry;
  withDay: boolean;
  section: "mail" | "action" | "other";
  title: string;
}) {
  const link = safeLink(entry.url);
  const tag = rowTag(entry, section, title);
  const s = entry.summary;
  const quiet = quietLine(s);
  return (
    <li className="t-row" data-testid="today-entry">
      <span className="t-when">{whenText(entry, withDay)}</span>
      <span className="t-what">
        {link ? (
          <a href={link} target="_blank" rel="noreferrer noopener">
            {entry.title}
          </a>
        ) : (
          entry.title
        )}
        {tag && (
          <span className={TAG_CLASS[tag] ?? "t-tag"}>
            <span className="sr-only">，</span>
            {tag}
          </span>
        )}
        {quiet && (
          <span className="t-todo" data-testid="summary">
            {quiet}
          </span>
        )}
        {s && s.status !== "ok" && (
          <span className="t-todo" data-testid="summary-state">
            {SUMMARY_LABEL[s.status]}
          </span>
        )}
      </span>
      <span className="t-from">{origin(entry)}</span>
    </li>
  );
}

function Section({
  title,
  entries,
  testId,
  withDay = false,
  section = "other",
}: {
  title: string;
  entries: TodayEntry[];
  testId: string;
  withDay?: boolean;
  section?: "mail" | "action" | "other";
}) {
  if (entries.length === 0) return null;
  return (
    <div className="t-section" data-testid={testId}>
      <h2>{title}</h2>
      <ul>
        {entries.map((e) => (
          <TodayRow
            key={`${e.kind}-${e.ref}`}
            entry={e}
            withDay={withDay}
            section={section}
            title={title}
          />
        ))}
      </ul>
    </div>
  );
}

export function TodayView({ api, onConnect }: { api: Api; onConnect: () => void }) {
  const [today, setToday] = useState<Today | null>(null);
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      let view: Today;
      try {
        view = await api.today(browserZone());
      } catch (err) {
        // The Hub may not know this browser's zone name: fall back to the PC's zone.
        if (!(err instanceof ApiError && err.status === 422)) throw err;
        view = await api.today("");
      }
      if (ticket === latest.current) {
        setToday(view);
        setError(null);
      }
    } catch (err) {
      if (ticket === latest.current) setError(`连不上 Hub：${errorText(err)}`);
    }
  }, [api]);

  useEffect(() => {
    void reload();
    // Synced data changes in the background; refresh while the page is open.
    const timer = window.setInterval(() => void reload(), 5 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [reload]);

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (!today) return <p>加载中…</p>;

  const nothingConnected = today.sources === 0;
  // A mail that asks for something is listed there; 未读邮件 does not repeat it.
  const actionRefs = new Set((today.mail_actions ?? []).map((m) => m.ref));
  return (
    <div className="today" data-testid="today">
      <p className="headline" data-testid="today-headline">
        {today.headline}
      </p>
      <StudyCard api={api} code={null} />
      {nothingConnected && (
        <p className="muted">
          还没有连接任何来源。连上 Canvas 和邮箱后，这里会列出截止、缺交和未读邮件。{" "}
          <button type="button" onClick={onConnect}>
            去连接
          </button>
        </p>
      )}
      {today.ai_notice && (
        <p className="t-notice" data-testid="today-ai-notice">
          AI 邮件总结暂停：{today.ai_notice}{" "}
          <button type="button" className="g-more" onClick={onConnect}>
            去处理
          </button>
        </p>
      )}
      <Section title="缺交 / 逾期" entries={today.missing} testId="today-missing" withDay />
      <Section title="今天截止" entries={today.due_today} testId="today-due" />
      <Section title="今日日程" entries={today.events} testId="today-events" />
      <Section
        title="邮件里要你做的"
        entries={today.mail_actions ?? []}
        testId="today-mail-actions"
        withDay
        section="action"
      />
      <Section title="接下来三天" entries={today.due_soon} testId="today-soon" withDay />
      <Section
        title="未读邮件"
        entries={today.mail.filter((m) => !actionRefs.has(m.ref))}
        testId="today-mail"
        section="mail"
      />
      <Section title="新公告" entries={today.announcements} testId="today-news" withDay />
      <Section title="进行中" entries={today.in_progress} testId="today-progress" />
      <p className="t-foot">
        {today.problems.length > 0 && (
          <span className="t-problem" data-testid="today-problems">
            {today.problems.map((p) => `${p.name}没同步上：${p.error}`).join("；")}
          </span>
        )}
        <span>
          更新于 {new Date(today.generated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
        </span>
        <button type="button" className="g-more" onClick={() => void reload()}>
          刷新
        </button>
      </p>
    </div>
  );
}
