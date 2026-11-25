import { useEffect, useState } from "react";
import { type Agenda, type AgendaEntry, type Api } from "./api";
import { safeLink } from "./ConnectionsView";
import { placeText, sideText, timeText } from "./ScheduleView";

type FreeSlot = Agenda["free"][number];

export type PlanState = "past" | "now" | "next" | "later";

export interface PlanRow {
  key: string;
  starts_at: string;
  ends_at: string | null;
  title: string;
  when: string; // "10:30–11:20", "截止 23:59", "全天", "空闲 14:00–16:00"
  side: string; // "上课", "写作业", "日历", ""
  place: string; // a room such as "ATC 203", or ""
  url: string; // a link to open the entry (calendar event), or ""
  state: PlanState;
  free: boolean;
}

function hm(at: string): string {
  return new Date(at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** "2026-11-23" for the local day of `now`. */
function localKey(now: number): string {
  const d = new Date(now);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/**
 * Whether an all-day entry is on the local day `key`. All-day items are stored at UTC
 * midnight of their date (as the briefing reads them), so their UTC date range is
 * compared, not their instants: a neighbouring day's holiday overlaps the local day's
 * window in any zone but UTC.
 */
export function allDayOn(e: Pick<AgendaEntry, "starts_at" | "ends_at">, key: string): boolean {
  const startMs = new Date(e.starts_at).getTime();
  const endMs = e.ends_at ? new Date(e.ends_at).getTime() : startMs + 86_400_000;
  const first = new Date(startMs).toISOString().slice(0, 10);
  const last = new Date(Math.max(endMs - 1, startMs)).toISOString().slice(0, 10); // end is exclusive
  return first <= key && key <= last;
}

/** A planned homework block reads as what it is ("写作业：…" is stored as a task). */
function side(e: AgendaEntry): string {
  if (e.kind === "task" && e.title.startsWith("写作业：")) return "写作业";
  return sideText(e);
}

/**
 * 今天的安排 (T-0071): today's agenda as one list in time order, free time included, each
 * row marked past / now / next / later against `now`. All-day entries of today come first
 * and are never "now"; a deadline is a point in time (past once it has passed). Canvas
 * deadlines are left out: 今天截止 on the same page already lists them.
 */
export function planRows(entries: AgendaEntry[], free: FreeSlot[], now: number): PlanRow[] {
  const today = localKey(now);
  const kept = entries.filter(
    (e) => !(e.source === "canvas" && e.kind === "deadline") && (!e.all_day || allDayOn(e, today)),
  );
  const rows: (Omit<PlanRow, "state"> & { allDay: boolean })[] = [
    ...kept.map((e) => ({
      key: e.key,
      starts_at: e.starts_at,
      ends_at: e.ends_at,
      title: e.title,
      when: timeText(e),
      side: side(e),
      place: placeText(e),
      url: e.url,
      free: false,
      allDay: e.all_day,
    })),
    ...free.map((f) => ({
      key: `free:${f.starts_at}`,
      starts_at: f.starts_at,
      ends_at: f.ends_at,
      title: `空闲 ${f.minutes >= 60 ? `${Math.floor(f.minutes / 60)} 小时${f.minutes % 60 ? ` ${f.minutes % 60} 分` : ""}` : `${f.minutes} 分钟`}`,
      when: `${hm(f.starts_at)}–${hm(f.ends_at)}`,
      side: "",
      place: "",
      url: "",
      free: true,
      allDay: false,
    })),
  ].sort((a, b) => Number(b.allDay) - Number(a.allDay) || Date.parse(a.starts_at) - Date.parse(b.starts_at));
  let nextTaken = false;
  return rows.map(({ allDay, ...r }) => {
    const start = new Date(r.starts_at).getTime();
    const end = r.ends_at ? new Date(r.ends_at).getTime() : start;
    let state: PlanState;
    if (allDay) state = "later";
    else if (end < now || (end === start && start < now)) state = "past";
    else if (start <= now) state = "now";
    else if (!nextTaken && !r.free) {
      state = "next";
      nextTaken = true;
    } else state = "later";
    return { ...r, state };
  });
}

const STATE_WORD: Record<PlanState, string> = { past: "", now: "现在", next: "下一项", later: "" };

/** Local midnight today and tomorrow, as ISO strings. */
function todayBounds(now: Date): [string, string] {
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return [start.toISOString(), end.toISOString()];
}

/** The 今日 list of today: classes, homework blocks, deadlines and free time (T-0071). */
export function TodayPlan({ api, zone, refresh }: { api: Api; zone: string; refresh: unknown }) {
  const [agenda, setAgenda] = useState<Agenda | null>(null);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    let alive = true;
    const [start, end] = todayBounds(new Date());
    api
      .agenda(start, end, zone)
      .then((a) => alive && setAgenda(a))
      .catch(() => undefined); // 今日 already says when the Hub is unreachable
    return () => {
      alive = false;
    };
  }, [api, zone, refresh]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000); // move "现在" along
    return () => window.clearInterval(timer);
  }, []);
  if (!agenda) return null;
  const rows = planRows(agenda.entries, agenda.free, now);
  if (rows.length === 0) return null;
  return (
    <div className="t-section" data-testid="today-plan">
      <h2>今天的安排</h2>
      <ul>
        {rows.map((r) => (
          <li key={r.key} className={`t-row plan-row plan-${r.state}${r.free ? " plan-free" : ""}`} data-testid="plan-row">
            <span className="t-when">{r.when}</span>
            <span className="t-what">
              {safeLink(r.url) ? (
                <a href={safeLink(r.url) ?? undefined} target="_blank" rel="noreferrer noopener">
                  {r.title}
                </a>
              ) : (
                r.title
              )}
              {r.place && <span className="t-todo">{r.place}</span>}
              {r.state === "past" && <span className="sr-only">，已结束</span>}
              {STATE_WORD[r.state] && (
                <span className={r.state === "now" && !r.free ? "t-tag ok" : "t-tag"}>
                  <span className="sr-only">，</span>
                  {STATE_WORD[r.state]}
                </span>
              )}
            </span>
            <span className="t-from">{r.side}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
