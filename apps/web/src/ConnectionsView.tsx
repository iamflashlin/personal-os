import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type Api,
  ApiError,
  type Integration,
  type IntegrationStatus,
  type NewFeed,
  type SyncedItem,
} from "./api";

const STATUS: Record<IntegrationStatus, string> = {
  never_synced: "还没同步过",
  ok: "正常",
  error: "出错",
};

const INTERVALS: [number, string][] = [
  [900, "每 15 分钟"],
  [3600, "每小时"],
  [86400, "每天"],
];

const UPCOMING_DAYS = 14;
const REFRESH_MS = 10_000;
const SYNC_WAIT_MS = 60_000;
const INTRO =
  "把外部来源接进来，系统会在后台定时同步。现在支持“日历订阅链接”（ICS），" +
  "例如 Canvas 的 Calendar Feed。链接里带有私密令牌，只存进 Windows 凭据管理器，" +
  "页面不会再显示它。";

interface Upcoming {
  item: SyncedItem;
  source: string;
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) return `操作失败（${err.status}）：${err.detail}`;
  return String(err);
}

/**
 * Start of "today" for the upcoming list. All-day items are stored at UTC midnight, so
 * the window starts at whichever is earlier: local midnight or UTC midnight of today's
 * local date. Today's deadlines and events already in progress stay visible.
 */
export function startOfToday(now: Date = new Date()): Date {
  const local = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const utc = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  return local < utc ? local : utc;
}

/** Only web links are clickable; a feed could carry file:, search-ms: or similar. */
export function safeLink(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function when(item: SyncedItem): string {
  if (!item.starts_at) return "时间未知";
  const start = new Date(item.starts_at);
  if (item.all_day) {
    // All-day dates are stored as UTC midnight; show that calendar day, not a local shift.
    return start.toLocaleDateString("zh-CN", {
      timeZone: "UTC",
      month: "long",
      day: "numeric",
      weekday: "short",
    });
  }
  return start.toLocaleString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ago(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString("zh-CN") : "—";
}

function time(iso: string | null): number {
  return iso ? Date.parse(iso) : Number.POSITIVE_INFINITY;
}

/** A fresh credential name that the Hub accepts: lower-case letters, digits and dots. */
function newCredentialName(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(5));
  return `feed.${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export function ConnectionsView({ api }: { api: Api }) {
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [upcoming, setUpcoming] = useState<Upcoming[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<Set<string>>(new Set());
  const latest = useRef(0);
  const mounted = useRef(true);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const found = await api.integrations();
      const start = startOfToday();
      const end = new Date(start.getTime() + UPCOMING_DAYS * 24 * 3600 * 1000);
      // One source failing (e.g. deleted in another tab) must not blank the others.
      const lists = await Promise.allSettled(
        found.map(async (i) =>
          (await api.integrationItems(i, start, end)).map((item) => ({ item, source: i.name })),
        ),
      );
      const merged = lists
        .flatMap((r) => (r.status === "fulfilled" ? r.value : []))
        .sort((a, b) => time(a.item.starts_at) - time(b.item.starts_at));
      if (mounted.current && ticket === latest.current) {
        setIntegrations(found);
        setUpcoming(merged);
        setLoadError(null);
      }
    } catch (err) {
      if (mounted.current && ticket === latest.current) {
        setLoadError(`连不上 Hub：${errorText(err)}`);
      }
    }
  }, [api]);

  useEffect(() => {
    mounted.current = true;
    void reload();
    // Background syncs change what is shown; keep the page current while it is open.
    const timer = window.setInterval(() => void reload(), REFRESH_MS);
    return () => {
      mounted.current = false;
      window.clearInterval(timer);
    };
  }, [reload]);

  const run = async (action: () => Promise<unknown>): Promise<boolean> => {
    try {
      await action();
      if (mounted.current) setActionError(null);
      return true;
    } catch (err) {
      if (mounted.current) setActionError(errorText(err));
      return false;
    } finally {
      if (mounted.current) await reload();
    }
  };

  /** Queue a sync and wait for that very job to finish (or the page to close). */
  const syncNow = async (integration: Integration) => {
    setSyncing((s) => new Set(s).add(integration.id));
    try {
      await run(async () => {
        const { job_id } = await api.syncIntegration(integration);
        const deadline = Date.now() + SYNC_WAIT_MS;
        while (mounted.current && Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 1000));
          const job = await api.job(job_id);
          // A failed attempt goes back to "queued" with its error; that is an answer too.
          if (job.status !== "running" && (job.status !== "queued" || job.attempts > 0)) return;
        }
      });
    } finally {
      if (mounted.current) {
        setSyncing((s) => {
          const next = new Set(s);
          next.delete(integration.id);
          return next;
        });
      }
    }
  };

  const disconnect = (integration: Integration) => {
    // A credential shared with another integration (created through the API) stays.
    const shared = (integrations ?? []).some(
      (i) => i.id !== integration.id && i.credential_name === integration.credential_name,
    );
    return run(() => api.disconnect(integration, { keepCredential: shared }));
  };

  return (
    <>
      <p className="muted">{INTRO}</p>
      {loadError && (
        <p className="error" role="alert">
          {loadError}
        </p>
      )}
      {actionError && (
        <p className="error" role="alert">
          {actionError}
        </p>
      )}
      <NewFeedForm onConnect={(feed) => run(() => api.connectFeed(feed, newCredentialName()))} />
      <section data-testid="integrations">
        <h2>已连接</h2>
        {integrations === null && !loadError && <p>加载中…</p>}
        {integrations?.length === 0 && <p className="muted">还没有连接任何来源</p>}
        <ul className="memories">
          {integrations?.map((i) => (
            <IntegrationRow
              key={i.id}
              integration={i}
              syncing={syncing.has(i.id)}
              onSync={() => void syncNow(i)}
              onDelete={() => disconnect(i)}
            />
          ))}
        </ul>
      </section>
      <section data-testid="upcoming">
        <h2>接下来 {UPCOMING_DAYS} 天</h2>
        {upcoming.length === 0 && <p className="muted">没有即将到来的日程</p>}
        <ul className="memories">
          {upcoming.map(({ item, source }) => {
            const link = safeLink(item.url);
            const title = item.title || "（无标题）";
            return (
              <li key={item.id} className="memory" data-testid="upcoming-item">
                <div className="memory-main">
                  <span className="badge">{when(item)}</span>
                  <span className="memory-body">
                    {link ? (
                      <a href={link} target="_blank" rel="noreferrer noopener">
                        {title}
                      </a>
                    ) : (
                      title
                    )}
                  </span>
                  <span className="muted">{source}</span>
                </div>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

/** Calendar apps often hand out webcal:// links; they are plain https underneath. */
export function feedAddress(text: string): string {
  const trimmed = text.trim();
  return trimmed.toLowerCase().startsWith("webcal://")
    ? `https://${trimmed.slice("webcal://".length)}`
    : trimmed;
}

function NewFeedForm({ onConnect }: { onConnect: (feed: NewFeed) => Promise<boolean> }) {
  const [name, setName] = useState("");
  const [every, setEvery] = useState(900);
  const [busy, setBusy] = useState(false);
  // Uncontrolled: React would otherwise mirror the link into the DOM's value attribute.
  const link = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const field = link.current;
    if (!field) return;
    setBusy(true);
    try {
      const feed = { name: name.trim(), url: feedAddress(field.value), interval_s: every };
      if (await onConnect(feed)) {
        setName("");
        field.value = "";
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="new-memory" onSubmit={submit} aria-label="添加日历订阅" autoComplete="off">
      <label>
        <span className="label">名称</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如：Canvas 日历"
          maxLength={80}
          required
        />
      </label>
      <label className="grow">
        <span className="label">订阅链接（不会再显示）</span>
        {/* Text, masked by CSS: a password field would invite the browser to save the link
            in its password manager, a second copy outside Credential Manager. */}
        <input
          ref={link}
          type="text"
          className="masked"
          autoComplete="off"
          spellCheck={false}
          data-lpignore="true"
          data-1p-ignore="true"
          placeholder="https://…/feed.ics"
          required
        />
      </label>
      <label>
        <span className="label">同步频率</span>
        <select value={every} onChange={(e) => setEvery(Number(e.target.value))}>
          {INTERVALS.map(([seconds, text]) => (
            <option key={seconds} value={seconds}>
              {text}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "连接中…" : "连接"}
      </button>
    </form>
  );
}

function IntegrationRow({
  integration,
  syncing,
  onSync,
  onDelete,
}: {
  integration: Integration;
  syncing: boolean;
  onSync: () => void;
  onDelete: () => Promise<boolean>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const remove = async () => {
    setDeleting(true);
    try {
      await onDelete();
    } finally {
      setDeleting(false);
    }
  };
  return (
    <li className="memory" data-testid={`integration-${integration.id}`}>
      <div className="memory-main">
        <span className="memory-body">{integration.name}</span>
        <span className={`badge status-${integration.status}`}>{STATUS[integration.status]}</span>
        <span className="muted">
          {integration.item_count} 条 · 上次成功：{ago(integration.last_success_at)}
        </span>
      </div>
      {integration.status === "error" && integration.last_error && (
        <p className="error">{integration.last_error}</p>
      )}
      <div className="memory-actions">
        <button type="button" onClick={onSync} disabled={syncing}>
          {syncing ? "同步中…" : "立即同步"}
        </button>
        {confirming ? (
          <>
            <button
              type="button"
              className="danger"
              onClick={() => void remove()}
              disabled={deleting}
            >
              确定删除（连同已同步的条目和订阅链接）
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={deleting}>
              不删
            </button>
          </>
        ) : (
          <button type="button" onClick={() => setConfirming(true)}>
            删除
          </button>
        )}
      </div>
    </li>
  );
}
