import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type Api, ApiError, type DigestItem, type DigestView as Digest } from "./api";
import { MailBody } from "./MailBody";
import { safeLink } from "./ConnectionsView";
import { browserZone } from "./TodayView";

export const CHANNEL_LABEL: Record<string, string> = {
  news: "时事",
  club: "社团活动",
  group: "群聊精华",
  other: "其他",
};
const CHANNELS = ["news", "club", "group", "other"] as const;

function Item({ item, onRead }: { item: DigestItem; onRead: (id: string, read: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const link = safeLink(item.url);
  return (
    <li className={`digest-item${item.read ? "" : " unread"}`} data-testid="digest-item">
      <button
        type="button"
        className="mail-head"
        aria-expanded={open}
        onClick={() => {
          setOpen((v) => !v);
          if (!item.read) onRead(item.id, true); // opening it is reading it
        }}
      >
        <span className="badge">{CHANNEL_LABEL[item.channel] ?? item.channel}</span>
        {item.important && <span className="badge submission-缺交">重要</span>}
        <span className="memory-body">{item.title}</span>
        {!item.read && <span className="badge unread">未读</span>}
        <span className="muted">
          {item.source_name} · {new Date(item.published_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
        </span>
      </button>
      {open && (
        <div className="mail-detail" data-testid="digest-detail">
          {item.summary && <p className="digest-summary">{item.summary}</p>}
          {item.happens_at && (
            <p>
              <strong>时间：</strong>
              {new Date(item.happens_at).toLocaleString("zh-CN")}
            </p>
          )}
          {link && (
            <p>
              <a href={link} target="_blank" rel="noreferrer noopener">
                打开原链接
              </a>
            </p>
          )}
          {item.raw_text && (
            <details>
              <summary className="muted">原文</summary>
              <MailBody body={item.raw_text} />
            </details>
          )}
          <button type="button" className="link-button" onClick={() => onRead(item.id, !item.read)}>
            {item.read ? "标为未读" : "标为已读"}
          </button>
        </div>
      )}
    </li>
  );
}

export function DigestView({ api }: { api: Api }) {
  const [which, setWhich] = useState<"today" | "history">("today");
  const [channel, setChannel] = useState<string>("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [view, setView] = useState<Digest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    try {
      setView(await api.digest(which, browserZone(), unreadOnly, channel));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  }, [api, which, unreadOnly, channel]);
  useEffect(() => {
    void load();
  }, [load]);

  async function read(id: string, value: boolean) {
    try {
      const updated = await api.markDigest(id, value);
      // Update in place: with 只看未读 on, a reload would pull the item away while reading it.
      setView((v) => {
        if (!v) return v;
        const was = v.items.find((i) => i.id === id);
        const delta = was && was.read !== updated.read ? (updated.read ? -1 : 1) : 0;
        return {
          ...v,
          items: v.items.map((i) => (i.id === id ? updated : i)),
          unread_today: v.view === "today" ? v.unread_today + delta : v.unread_today,
          unread_history: v.view === "history" ? v.unread_history + delta : v.unread_history,
        };
      });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  }

  async function add(ev: FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const f = new FormData(ev.currentTarget);
    try {
      await api.addDigest({
        channel: String(f.get("channel")) as (typeof CHANNELS)[number],
        source_name: String(f.get("source") ?? ""),
        title: String(f.get("title") ?? ""),
        summary: String(f.get("summary") ?? ""),
        raw_text: String(f.get("raw") ?? ""),
        url: String(f.get("url") ?? ""),
        important: f.get("important") === "on",
      }, browserZone());
      setAdding(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    }
  }

  return (
    <section className="digest" data-testid="digest">
      <div className="mail-filters" role="group" aria-label="简报范围">
        <button type="button" aria-pressed={which === "today"} className={which === "today" ? "active" : ""} onClick={() => setWhich("today")}>
          今天{view ? ` · 未读 ${view.unread_today}` : ""}
        </button>
        <button type="button" aria-pressed={which === "history"} className={which === "history" ? "active" : ""} onClick={() => setWhich("history")}>
          历史{view ? ` · 未读 ${view.unread_history}` : ""}
        </button>
        <label className="muted">
          <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> 只看未读
        </label>
        <select aria-label="来源" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">全部来源</option>
          {CHANNELS.map((c) => (
            <option key={c} value={c}>
              {CHANNEL_LABEL[c]}
              {view?.channels[c] ? `（${view.channels[c]}）` : ""}
            </option>
          ))}
        </select>
        {view && view.items.some((i) => !i.read) && (
          <button
            type="button"
            onClick={() =>
              void api
                .readAllDigest(which, browserZone(), channel)
                .then(load)
                .catch((err) => setError(String(err)))
            }
          >
            全部标为已读
          </button>
        )}
        <button type="button" data-testid="digest-add" onClick={() => setAdding((v) => !v)}>
          {adding ? "取消" : "手动添加"}
        </button>
      </div>
      <p className="muted">
        时事、社团活动（IG / Discord）、群聊精华（微信转学群）都会进到这里；这些来源还没接上，现在可以先手动添加。
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {adding && (
        <form className="sched-form" aria-label="添加简报" onSubmit={(ev) => void add(ev)}>
          <label>
            类别{" "}
            <select name="channel" defaultValue="group">
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {CHANNEL_LABEL[c]}
                </option>
              ))}
            </select>
          </label>
          <label>
            来源 <input name="source" required maxLength={120} placeholder="例如：微信转学群" />
          </label>
          <label>
            标题 <input name="title" required maxLength={300} />
          </label>
          <label>
            要点 <textarea name="summary" maxLength={4000} rows={3} />
          </label>
          <label>
            原文 <textarea name="raw" maxLength={50000} rows={3} />
          </label>
          <label>
            链接 <input name="url" maxLength={2000} />
          </label>
          <label>
            <input type="checkbox" name="important" /> 重要
          </label>
          <button type="submit">保存</button>
        </form>
      )}
      {!view && !error && <p>加载中…</p>}
      {view && view.items.length === 0 && (
        <p className="muted">{which === "today" ? "今天还没有简报。" : "没有历史简报。"}</p>
      )}
      {view && (
        <ul className="memories">
          {view.items.map((i) => (
            <Item key={i.id} item={i} onRead={(id, v) => void read(id, v)} />
          ))}
        </ul>
      )}
    </section>
  );
}
