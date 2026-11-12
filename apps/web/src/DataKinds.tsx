import type { Integration } from "./api";

/** The six kinds of personal data (the user's P0 list), and what feeds each one. */
export interface DataKind {
  key: string;
  label: string;
  examples: string;
  /** Integration kinds that feed it; an empty list means it is not connectable yet. */
  sources: Integration["kind"][];
  /** Data the user keeps in the Hub by hand, so the kind is never empty. */
  local?: string;
  later?: string;
}

export const DATA_KINDS: DataKind[] = [
  { key: "academic", label: "学业", examples: "Canvas、课程大纲、成绩", sources: ["canvas"] },
  {
    key: "schedule",
    label: "日程",
    examples: "Google 日历、学校日历",
    sources: ["ics"],
    local: "日程页里自己添加的课程和活动",
  },
  { key: "mail", label: "邮件", examples: "Gmail、163", sources: ["email"] },
  {
    key: "pc",
    label: "电脑活动",
    examples: "Windows、浏览器、软件使用",
    sources: [],
    later: "等课程和邮件稳定后再接",
  },
  {
    key: "files",
    label: "文件和资料",
    examples: "本地文件、PDF、笔记、云盘",
    sources: [],
    later: "先定用 WPS 本地还是 Google Drive",
  },
  {
    key: "goals",
    label: "目标和经历",
    examples: "计划、决定、项目",
    sources: [],
    local: "记忆页里记下的内容",
  },
];

export type KindState = "ok" | "stale" | "error" | "never" | "none" | "local" | "later";

export interface KindStatus {
  kind: DataKind;
  state: KindState;
  connected: Integration[];
  lastSuccess: string | null;
  error: string;
}

/** A source counts as stale once it has missed three of its own sync intervals. */
const STALE_INTERVALS = 3;

export function kindStatus(kind: DataKind, all: Integration[], now = Date.now()): KindStatus {
  const connected = all.filter((i) => kind.sources.includes(i.kind));
  const failing = connected.find((i) => i.status === "error");
  const times = connected
    .map((i) => i.last_success_at)
    .filter((t): t is string => t !== null)
    .sort((a, b) => Date.parse(a) - Date.parse(b));
  const lastSuccess = times.at(-1) ?? null;
  const reason = failing
    ? `${connected.length > 1 ? `${failing.name}：` : ""}${failing.last_error || "未知"}`
    : "";
  const base = { kind, connected, lastSuccess, error: reason };
  if (connected.length === 0) {
    if (kind.local) return { ...base, state: "local" };
    return { ...base, state: kind.later ? "later" : "none" };
  }
  if (failing) return { ...base, state: "error" };
  // Any source that has never worked makes the kind incomplete, even if a sibling has.
  if (connected.some((i) => i.last_success_at === null)) return { ...base, state: "never" };
  const stale = connected.some(
    (i) =>
      i.last_success_at !== null &&
      now - new Date(i.last_success_at).getTime() > STALE_INTERVALS * i.interval_s * 1000,
  );
  return { ...base, state: stale ? "stale" : "ok" };
}

const STATE_TEXT: Record<KindState, string> = {
  ok: "正常",
  stale: "数据可能过期",
  error: "同步出错",
  never: "还没同步过",
  none: "未连接",
  local: "在 Hub 里手动记录",
  later: "以后接入",
};

function when(iso: string | null): string {
  return iso
    ? new Date(iso).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
}

export function DataKindsOverview({ integrations }: { integrations: Integration[] }) {
  return (
    <section data-testid="data-kinds">
      <h2>数据来源总览</h2>
      <ul className="data-kinds">
        {DATA_KINDS.map((k) => {
          const s = kindStatus(k, integrations);
          return (
            <li key={k.key} className={`data-kind state-${s.state}`} data-testid={`kind-${k.key}`}>
              <div>
                <strong>{k.label}</strong>{" "}
                <span className={`badge state-${s.state}`}>{STATE_TEXT[s.state]}</span>
              </div>
              <div className="muted">{k.examples}</div>
              {s.connected.length > 0 && (
                <div>
                  {s.connected.map((i) => i.name).join("、")} · 最近成功 {when(s.lastSuccess)}
                </div>
              )}
              {s.state === "error" && <div className="error">原因：{s.error}</div>}
              {s.state === "local" && <div className="muted">{k.local}</div>}
              {s.state === "later" && <div className="muted">{k.later}</div>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
