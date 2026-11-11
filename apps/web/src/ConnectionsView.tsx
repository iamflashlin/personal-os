import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type Api,
  ApiError,
  type Integration,
  type IntegrationStatus,
  type NewCanvas,
  type NewEmail,
  type NewFeed,
  type SyncedItem,
} from "./api";
import { AiCard } from "./Summary";

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
const NEWS_DAYS = 7;
const SECRET_NAME: Record<Integration["kind"], string> = {
  ics: "订阅链接",
  canvas: "访问令牌",
  email: "授权码",
};
const REFRESH_MS = 10_000;
const SYNC_WAIT_MS = 60_000;
const INTRO =
  "把外部来源接进来，系统会在后台定时同步。现在支持“日历订阅链接”（ICS），" +
  "例如 Canvas 的 Calendar Feed；也可以用 Canvas 的访问令牌直接接入（能看到是否已交、" +
  "分数和公告）；邮箱用 IMAP 接入（163 要用授权码）。链接、令牌和授权码都只存进 " +
  "Windows 凭据管理器，页面不会再显示它们。";

const MAIL_LIMIT = 30;

const MAIL_PRESETS: [string, string][] = [
  ["imap.163.com", "163 邮箱"],
  ["imap.gmail.com", "Gmail"],
  ["imap.qq.com", "QQ 邮箱"],
];

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
function newCredentialName(prefix: "feed" | "canvas" | "mail"): string {
  const bytes = crypto.getRandomValues(new Uint8Array(5));
  return `${prefix}.${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

/** What a Canvas assignment's submission says, in a word; null for anything else. */
export function submissionBadge(item: SyncedItem): string | null {
  if (item.item_type !== "canvas_assignment") return null;
  const data = item.data as { submission_state?: string; missing?: boolean };
  if (data.missing) return "缺交";
  if (data.submission_state === "graded") return "已评分";
  if (data.submission_state === "submitted" || data.submission_state === "pending_review") {
    return "已提交";
  }
  return null;
}

export function ConnectionsView({ api }: { api: Api }) {
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [upcoming, setUpcoming] = useState<Upcoming[]>([]);
  const [news, setNews] = useState<Upcoming[]>([]);
  const [mailCount, setMailCount] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<Set<string>>(new Set());
  const latest = useRef(0);
  const mounted = useRef(true);

  const reload = useCallback(async () => {
    const ticket = ++latest.current;
    try {
      const found = await api.integrations();
      const today = startOfToday();
      const day = 24 * 3600 * 1000;
      const pastStart = new Date(today.getTime() - NEWS_DAYS * day);
      const end = new Date(today.getTime() + UPCOMING_DAYS * day);
      // Two windows, so last week's calendar events never crowd out what is coming.
      // One source failing (e.g. deleted in another tab) must not blank the others.
      const load = async (from: Date, to: Date) =>
        (
          await Promise.allSettled(
            found
              .filter((i) => i.kind !== "email")
              .map(async (i) =>
                (await api.integrationItems(i, from, to)).map((item) => ({ item, source: i.name })),
              ),
          )
        ).flatMap((r) => (r.status === "fulfilled" ? r.value : []));
      // Mail is read newest first and on its own, so a week of mail never hides older unread.
      const loadMail = async () =>
        (
          await Promise.allSettled(
            found
              .filter((i) => i.kind === "email")
              .map(async (i) =>
                (await api.recentMail(i, MAIL_LIMIT)).map((item) => ({ item, source: i.name })),
              ),
          )
        ).flatMap((r) => (r.status === "fulfilled" ? r.value : []));
      const [past, coming, recent] = await Promise.all([
        load(pastStart, today),
        load(today, end),
        loadMail(),
      ]);
      const byTime = (a: Upcoming, b: Upcoming) => time(a.item.starts_at) - time(b.item.starts_at);
      const isNews = (u: Upcoming) => u.item.item_type === "canvas_announcement";
      const isMail = (u: Upcoming) => u.item.item_type === "email_message";
      // Canvas marks work "missing" only after it was due: show last week's missing work too.
      const overdue = past.filter((u) => submissionBadge(u.item) === "缺交");
      if (mounted.current && ticket === latest.current) {
        setIntegrations(found);
        setUpcoming(
          [...overdue, ...coming.filter((u) => !isNews(u) && !isMail(u))].sort(byTime),
        );
        setMailCount(recent.length);
        setNews([...past, ...coming].filter(isNews).sort(byTime).reverse());
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
      <NewFeedForm
        onConnect={(feed) => run(() => api.connectFeed(feed, newCredentialName("feed")))}
      />
      <NewEmailForm
        onConnect={(m) => run(() => api.connectEmail(m, newCredentialName("mail")))}
      />
      <NewCanvasForm
        onConnect={(canvas) => run(() => api.connectCanvas(canvas, newCredentialName("canvas")))}
      />
      <AiCard api={api} onChanged={() => void reload()} />
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
          {upcoming.map((u) => (
            <ItemRow key={u.item.id} entry={u} testId="upcoming-item" />
          ))}
        </ul>
      </section>
      {mailCount > 0 && (
        <p className="muted" data-testid="mail-moved">
          邮件已同步。整理好的邮件在“邮件”页。
        </p>
      )}
      {news.length > 0 && (
        <section data-testid="news">
          <h2>最近公告（{NEWS_DAYS} 天内）</h2>
          <ul className="memories">
            {news.map((u) => (
              <ItemRow key={u.item.id} entry={u} testId="news-item" />
            ))}
          </ul>
        </section>
      )}
    </>
  );
}

function ItemRow({ entry, testId }: { entry: Upcoming; testId: string }) {
  const { item, source } = entry;
  const link = safeLink(item.url);
  const title = item.title || "（无标题）";
  const badge = submissionBadge(item);
  const course = (item.data as { course?: string }).course;
  return (
    <li className="memory" data-testid={testId}>
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
        {badge && <span className={`badge submission-${badge}`}>{badge}</span>}
        <span className="muted">{course || source}</span>
      </div>
      {item.item_type === "canvas_announcement" && item.body && (
        <p className="muted">{item.body.slice(0, 200)}</p>
      )}
    </li>
  );
}

function NewEmailForm({ onConnect }: { onConnect: (mail: NewEmail) => Promise<boolean> }) {
  const [name, setName] = useState("邮箱");
  const [host, setHost] = useState(MAIL_PRESETS[0][0]);
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const code = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const field = code.current;
    if (!field) return;
    setBusy(true);
    try {
      const mail = {
        name: name.trim(),
        host: host.trim(),
        username: username.trim(),
        code: field.value.trim(),
      };
      if (await onConnect(mail)) field.value = "";
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="new-memory" onSubmit={submit} aria-label="连接邮箱" autoComplete="off">
      <label>
        <span className="label">名称</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
      </label>
      <label>
        <span className="label">邮箱服务</span>
        <select value={host} onChange={(e) => setHost(e.target.value)}>
          {MAIL_PRESETS.map(([value, text]) => (
            <option key={value} value={value}>
              {text}（{value}）
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="label">邮箱地址</span>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="name@163.com"
          autoComplete="off"
          required
        />
      </label>
      <label className="grow">
        <span className="label">授权码（不会再显示）</span>
        <input
          ref={code}
          type="text"
          className="masked"
          autoComplete="off"
          spellCheck={false}
          data-lpignore="true"
          data-1p-ignore="true"
          required
        />
      </label>
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "连接中…" : "连接邮箱"}
      </button>
    </form>
  );
}

function NewCanvasForm({ onConnect }: { onConnect: (canvas: NewCanvas) => Promise<boolean> }) {
  const [name, setName] = useState("Canvas");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const token = useRef<HTMLInputElement>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const field = token.current;
    if (!field) return;
    setBusy(true);
    try {
      const canvas = {
        name: name.trim(),
        baseUrl: baseUrl.trim(),
        token: field.value.trim(),
        interval_s: 3600,
      };
      if (await onConnect(canvas)) field.value = "";
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="new-memory" onSubmit={submit} aria-label="连接 Canvas" autoComplete="off">
      <label>
        <span className="label">名称</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
      </label>
      <label>
        <span className="label">学校的 Canvas 网址</span>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://学校.instructure.com"
          required
        />
      </label>
      <label className="grow">
        <span className="label">访问令牌（不会再显示）</span>
        <input
          ref={token}
          type="text"
          className="masked"
          autoComplete="off"
          spellCheck={false}
          data-lpignore="true"
          data-1p-ignore="true"
          required
        />
      </label>
      <button type="submit" className="primary" disabled={busy}>
        {busy ? "连接中…" : "连接 Canvas"}
      </button>
    </form>
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
              {integration.kind === "email"
                ? "确定删除（只删本系统里的邮件副本和授权码，不会动邮箱里的邮件）"
                : `确定删除（连同已同步的条目和${SECRET_NAME[integration.kind]}）`}
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
