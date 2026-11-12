import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type AgendaEntry, type Agenda, type Api, ApiError, type EventKind } from "./api";
import { safeLink } from "./ConnectionsView";
import { browserZone } from "./TodayView";

const KIND_LABEL: Record<string, string> = {
  class: "上课",
  activity: "活动",
  workout: "健身",
  task: "任务",
  exam: "考试",
  other: "其他",
  calendar: "日历",
  deadline: "截止",
};
const KINDS: EventKind[] = ["class", "activity", "workout", "task", "exam", "other"];
const DAYS: { key: string; label: string }[] = [
  { key: "MO", label: "一" },
  { key: "TU", label: "二" },
  { key: "WE", label: "三" },
  { key: "TH", label: "四" },
  { key: "FR", label: "五" },
  { key: "SA", label: "六" },
  { key: "SU", label: "日" },
];

/** Monday 00:00 local of the week that holds `d`. */
export function weekStart(d: Date): Date {
  const out = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  out.setDate(out.getDate() - ((out.getDay() + 6) % 7));
  return out;
}

/** Entries grouped by local day (yyyy-mm-dd), in time order. */
export function byDay(entries: AgendaEntry[]): Map<string, AgendaEntry[]> {
  const out = new Map<string, AgendaEntry[]>();
  for (const e of entries) {
    const d = new Date(e.starts_at);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    out.set(key, [...(out.get(key) ?? []), e]);
  }
  return out;
}

function hm(at: string): string {
  return new Date(at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function localInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function Entry({ e, onDelete }: { e: AgendaEntry; onDelete: (id: string) => void }) {
  const link = safeLink(e.url);
  return (
    <li className={`sched-entry${e.conflict ? " conflict" : ""}`} data-testid="sched-entry">
      <span className="badge">{KIND_LABEL[e.kind] ?? e.kind}</span>{" "}
      <span className="muted">
        {e.all_day ? "全天" : e.ends_at ? `${hm(e.starts_at)}–${hm(e.ends_at)}` : hm(e.starts_at)}
      </span>{" "}
      {link ? (
        <a href={link} target="_blank" rel="noreferrer noopener">
          {e.title}
        </a>
      ) : (
        e.title
      )}
      {e.location && <span className="muted"> · {e.location}</span>}
      {e.conflict && (
        <span className="badge submission-缺交" data-testid="sched-conflict">
          时间冲突
        </span>
      )}
      {e.event_id && (
        <button type="button" className="link-button" onClick={() => onDelete(e.event_id ?? "")}>
          删除
        </button>
      )}
    </li>
  );
}

export function ScheduleView({ api }: { api: Api }) {
  const [start, setStart] = useState(() => weekStart(new Date()));
  const [agenda, setAgenda] = useState<Agenda | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);

  const load = useCallback(async () => {
    const until = new Date(start);
    until.setDate(until.getDate() + 7);
    try {
      setAgenda(await api.agenda(start.toISOString(), until.toISOString(), browserZone()));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  }, [api, start]);
  useEffect(() => {
    void load();
  }, [load]);

  async function add(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const f = new FormData(ev.currentTarget);
    const s = new Date(String(f.get("start")));
    const e = new Date(String(f.get("end")));
    setBusy(true);
    try {
      await api.createEvent(
        {
          title: String(f.get("title") ?? ""),
          kind: String(f.get("kind")) as EventKind,
          starts_at: s.toISOString(),
          ends_at: e.toISOString(),
          location: String(f.get("location") ?? ""),
          repeat_days: DAYS.map((d) => d.key).filter((k) => f.get(`day-${k}`) === "on"),
          repeat_until: f.get("until") ? String(f.get("until")) : null,
        },
        browserZone(),
      );
      setAdding(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
    setBusy(false);
  }

  async function remove(id: string) {
    try {
      await api.deleteEvent(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  }

  function shift(days: number) {
    const d = new Date(start);
    d.setDate(d.getDate() + days);
    setStart(d);
  }

  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date(start);
    d.setDate(d.getDate() + i);
    return d;
  });
  const grouped = byDay(agenda?.entries ?? []);
  const freeByDay = byDay(
    (agenda?.free ?? []).map((f) => ({
      key: f.starts_at,
      title: "",
      kind: "free",
      starts_at: f.starts_at,
      ends_at: f.ends_at,
      all_day: false,
      location: "",
      source: "manual" as const,
      event_id: null,
      url: "",
      blocks: false,
      conflict: false,
    })),
  );
  const defaultStart = new Date();
  defaultStart.setMinutes(0, 0, 0);
  defaultStart.setHours(defaultStart.getHours() + 1);
  const defaultEnd = new Date(defaultStart.getTime() + 60 * 60 * 1000);

  return (
    <section className="schedule" data-testid="schedule">
      <div className="sched-head">
        <button type="button" onClick={() => shift(-7)}>
          上一周
        </button>
        <strong>
          {start.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })} –{" "}
          {new Date(end.getTime() - 1).toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" })}
        </strong>
        <button type="button" onClick={() => shift(7)}>
          下一周
        </button>
        <button type="button" onClick={() => setStart(weekStart(new Date()))}>
          本周
        </button>
        <button type="button" data-testid="sched-add" onClick={() => setAdding((v) => !v)}>
          {adding ? "取消" : "添加日程"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {adding && (
        <form className="sched-form" aria-label="添加日程" onSubmit={(ev) => void add(ev)}>
          <label>
            名称 <input name="title" required maxLength={200} />
          </label>
          <label>
            类型{" "}
            <select name="kind" defaultValue="class">
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {KIND_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          <label>
            开始 <input name="start" type="datetime-local" required defaultValue={localInput(defaultStart)} />
          </label>
          <label>
            结束 <input name="end" type="datetime-local" required defaultValue={localInput(defaultEnd)} />
          </label>
          <label>
            地点 <input name="location" maxLength={300} />
          </label>
          <fieldset>
            <legend>每周重复（可不选）</legend>
            {DAYS.map((d) => (
              <label key={d.key}>
                <input type="checkbox" name={`day-${d.key}`} /> 周{d.label}
              </label>
            ))}
            <label>
              直到 <input name="until" type="date" />
            </label>
          </fieldset>
          <button type="submit" disabled={busy}>
            保存
          </button>
        </form>
      )}
      {!agenda && !error && <p>加载中…</p>}
      {agenda && (
        <div className="sched-week">
          {days.map((d) => {
            const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
            const entries = grouped.get(key) ?? [];
            const free = freeByDay.get(key) ?? [];
            return (
              <div key={key} className="sched-day" data-testid="sched-day">
                <h3>
                  {d.toLocaleDateString("zh-CN", { weekday: "short", month: "numeric", day: "numeric" })}
                </h3>
                {entries.length === 0 && <p className="muted">没有安排</p>}
                <ul>
                  {entries.map((e) => (
                    <Entry key={e.key} e={e} onDelete={(id) => void remove(id)} />
                  ))}
                </ul>
                {free.length > 0 && (
                  <p className="muted sched-free">
                    空闲：{free.map((f) => `${hm(f.starts_at)}–${hm(f.ends_at ?? f.starts_at)}`).join("、")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
