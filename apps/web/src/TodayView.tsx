import { useCallback, useEffect, useRef, useState } from "react";
import { type Api, ApiError, type EntrySummary, type TodayEntry, type TodayView as Today } from "./api";
import { safeLink } from "./ConnectionsView";
import { SummaryLine } from "./Summary";

const BADGE_CLASS: Record<string, string> = {
  缺交: "submission-缺交",
  逾期: "submission-缺交",
  未读: "submission-缺交",
  已提交: "submission-已提交",
  已评分: "submission-已评分",
  进行中: "in_progress",
};

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

function Entry({ entry, withDay }: { entry: TodayEntry; withDay: boolean }) {
  const when = whenText(entry, withDay);
  const link = safeLink(entry.url);
  return (
    <li className="memory" data-testid="today-entry">
      <div className="memory-main">
        {when && <span className="badge">{when}</span>}
        <span className="memory-body">
          {link ? (
            <a href={link} target="_blank" rel="noreferrer noopener">
              {entry.title}
            </a>
          ) : (
            entry.title
          )}
        </span>
        {summaryBadges(entry.summary).map((b) => (
          <span key={b} className={b === "重要" ? "badge submission-缺交" : "badge"}>
            {b}
          </span>
        ))}
        {entry.badge && (
          <span className={`badge ${BADGE_CLASS[entry.badge] ?? ""}`}>{entry.badge}</span>
        )}
      </div>
      <div className="muted">{[entry.note, entry.source].filter(Boolean).join(" · ")}</div>
      {/* The line above already is the AI title; show only what to do and when. */}
      <SummaryLine summary={entry.summary} hideGist />
    </li>
  );
}

function Section({
  title,
  entries,
  testId,
  empty,
  withDay = false,
}: {
  title: string;
  entries: TodayEntry[];
  testId: string;
  empty?: string;
  withDay?: boolean;
}) {
  if (entries.length === 0 && !empty) return null;
  return (
    <section data-testid={testId}>
      <h2>{title}</h2>
      {entries.length === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <ul>
          {entries.map((e) => (
            <Entry key={`${e.kind}-${e.ref}`} entry={e} withDay={withDay} />
          ))}
        </ul>
      )}
    </section>
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

  const date = new Date(`${today.date}T00:00:00`).toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  });
  const nothingConnected = today.sources === 0;
  return (
    <div className="today" data-testid="today">
      <p className="headline" data-testid="today-headline">
        <strong>{date}</strong> {today.headline}
      </p>
      {nothingConnected && (
        <p className="muted">
          还没有连接任何来源。连上 Canvas 和邮箱后，这里会自动列出截止、缺交和未读邮件。{" "}
          <button type="button" onClick={onConnect}>
            去连接
          </button>
        </p>
      )}
      {today.ai_notice && (
        <p className="error" data-testid="today-ai-notice">
          AI 邮件总结暂停：{today.ai_notice}{" "}
          <button type="button" onClick={onConnect}>
            去处理
          </button>
        </p>
      )}
      {today.problems.length > 0 && (
        <section data-testid="today-problems">
          <h2>同步出错</h2>
          <ul>
            {today.problems.map((p) => (
              <li key={p.name} className="error">
                {p.name}：{p.error}
              </li>
            ))}
          </ul>
        </section>
      )}
      <Section title="缺交 / 逾期" entries={today.missing} testId="today-missing" withDay />
      <Section
        title="今天截止"
        entries={today.due_today}
        testId="today-due"
        empty="今天没有截止的作业或任务"
      />
      <Section
        title="需要处理的邮件（7 天内）"
        entries={today.mail_actions ?? []}
        testId="today-mail-actions"
        withDay
      />
      <Section title="今日日程" entries={today.events} testId="today-events" />
      <Section
        title={`未读邮件（过去 24 小时 ${today.unread_mail} 封）`}
        entries={today.mail}
        testId="today-mail"
      />
      <Section title="接下来三天" entries={today.due_soon} testId="today-soon" withDay />
      <Section title="新公告" entries={today.announcements} testId="today-news" withDay />
      <Section title="进行中" entries={today.in_progress} testId="today-progress" />
      <p className="muted">
        更新于 {new Date(today.generated_at).toLocaleTimeString("zh-CN")}（{today.timezone}）{" "}
        <button type="button" onClick={() => void reload()}>
          刷新
        </button>
      </p>
    </div>
  );
}
