import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  type Api,
  ApiError,
  type Memory,
  type MemoryKind,
  type Provenance,
  type Sensitivity,
} from "./api";

const KIND: Record<MemoryKind, string> = {
  preference: "偏好",
  fact: "事实",
  decision: "决定",
  experience: "经历",
};

const PROVENANCE: Record<Provenance, string> = {
  raw: "原话",
  user_confirmed: "已确认",
  ai_inferred: "AI 推测",
  verified: "有证据",
};

const SENSITIVITY: Record<Sensitivity, string> = {
  normal: "普通",
  private: "私密",
  secret: "机密",
};

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const hint = err.status === 409 ? "（这条记忆刚被改过，列表已刷新，请再试一次）" : "";
    return `操作失败（${err.status}）：${err.detail}${hint}`;
  }
  return String(err);
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("zh-CN");
}

export function MemoryView({ api }: { api: Api }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const latest = useRef(0);
  // The query that is on screen now; actions refresh with this, not the one they began with.
  const queryRef = useRef(activeQuery);
  queryRef.current = activeQuery;

  const reload = useCallback(
    async (q: string) => {
      const ticket = ++latest.current;
      try {
        const found = q.trim()
          ? (await api.searchMemories(q.trim())).map((hit) => hit.memory)
          : await api.memories();
        if (ticket === latest.current) {
          setMemories(found);
          setLoadError(null);
        }
      } catch (err) {
        if (ticket === latest.current) setLoadError(`连不上 Hub：${errorText(err)}`);
      }
    },
    [api],
  );

  useEffect(() => {
    void reload(activeQuery);
  }, [reload, activeQuery]);

  /** Runs one user action, then refreshes the list either way; true only on success. */
  const run = async (action: () => Promise<unknown>): Promise<boolean> => {
    try {
      await action();
      setActionError(null);
      return true;
    } catch (err) {
      setActionError(errorText(err));
      return false;
    } finally {
      await reload(queryRef.current);
    }
  };

  const search = (event: FormEvent) => {
    event.preventDefault();
    setActionError(null);
    setActiveQuery(query);
  };

  const error = actionError ?? loadError;
  return (
    <section data-testid="memories">
      <h2>记忆</h2>
      <p className="muted">
        {"Personal OS 记住的关于你的事。“AI 推测”的内容在你确认或改正前只作参考；"}
        {"机密内容不出现在搜索结果里（在“显示全部”里能看到）。"}
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <form className="memory-search" onSubmit={search} role="search">
        <label>
          <span className="label">搜索（中英文都可以，空格分开的词都要出现）</span>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="例如：学习" />
        </label>
        <button type="submit">搜索</button>
        {activeQuery && (
          <button
            type="button"
            onClick={() => {
              setQuery("");
              setActionError(null);
              setActiveQuery("");
            }}
          >
            显示全部
          </button>
        )}
      </form>
      <NewMemoryForm onCreate={(m) => run(() => api.createMemory(m))} />
      {memories === null && !loadError && <p>加载中…</p>}
      {memories?.length === 0 && (
        <p className="muted">
          {activeQuery ? "没有找到匹配的记忆（机密内容不参与搜索）" : "还没有记忆"}
        </p>
      )}
      <ul className="memories">
        {memories?.map((m) => (
          <MemoryRow
            key={m.id}
            memory={m}
            onConfirm={() => run(() => api.confirmMemory(m))}
            onCorrect={(body) => run(() => api.correctMemory(m, body))}
            onDelete={() => run(() => api.deleteMemory(m))}
          />
        ))}
      </ul>
    </section>
  );
}

function NewMemoryForm({
  onCreate,
}: {
  onCreate: (memory: {
    kind: MemoryKind;
    body: string;
    sensitivity: Sensitivity;
  }) => Promise<boolean>;
}) {
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<MemoryKind>("fact");
  const [sensitivity, setSensitivity] = useState<Sensitivity>("normal");
  const [pending, setPending] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (pending || !body.trim()) return;
    setPending(true);
    const ok = await onCreate({ kind, body: body.trim(), sensitivity });
    setPending(false);
    if (ok) {
      setBody("");
      setSensitivity("normal");
    }
  };

  return (
    <form className="new-memory" onSubmit={submit} aria-label="添加记忆">
      <label>
        <span className="label">要记住的内容</span>
        <input
          required
          pattern=".*\S.*"
          title="内容不能只有空格"
          placeholder="例如：我更喜欢早上学习"
          value={body}
          onChange={(e) => setBody(e.target.value)}
        />
      </label>
      <label>
        <span className="label">类型</span>
        <select value={kind} onChange={(e) => setKind(e.target.value as MemoryKind)}>
          {Object.entries(KIND).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span className="label">敏感度</span>
        <select
          value={sensitivity}
          onChange={(e) => setSensitivity(e.target.value as Sensitivity)}
        >
          {Object.entries(SENSITIVITY).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <button type="submit" disabled={pending}>
        {pending ? "保存中…" : "记住"}
      </button>
    </form>
  );
}

function SourceLine({ memory }: { memory: Memory }) {
  const ref = memory.source_ref.trim();
  const isLink = /^https?:\/\//i.test(ref);
  return (
    <span className="muted memory-source">
      {formatDate(memory.created_at)} 记下
      {ref && " · 来源："}
      {ref &&
        (isLink ? (
          <a href={ref} target="_blank" rel="noreferrer noopener">
            {ref}
          </a>
        ) : (
          ref
        ))}
    </span>
  );
}

function MemoryRow({
  memory,
  onConfirm,
  onCorrect,
  onDelete,
}: {
  memory: Memory;
  onConfirm: () => Promise<boolean>;
  onCorrect: (body: string) => Promise<boolean>;
  onDelete: () => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [pending, setPending] = useState(false);
  const masked = memory.sensitivity === "secret" && !revealed;
  const bodyId = `memory-body-${memory.id}`;
  // A memory backed by evidence is not edited by hand; an AI guess is the one to confirm.
  const editable = memory.provenance !== "verified";
  const confirmable = memory.provenance === "ai_inferred";

  const act = async (action: () => Promise<boolean>, after?: () => void) => {
    if (pending) return;
    setPending(true);
    const ok = await action();
    setPending(false);
    if (ok) after?.();
  };

  return (
    <li className="memory" data-testid={`memory-${memory.id}`}>
      <div className="memory-main">
        {editing ? (
          <label className="grow">
            <span className="label">改正为</span>
            <input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} />
          </label>
        ) : (
          <span className="memory-body" id={bodyId} data-testid="memory-body">
            {masked ? (
              <>
                <span aria-hidden="true">••••••</span>（机密，按“显示”查看）
              </>
            ) : (
              memory.body
            )}
          </span>
        )}
        <span className="badge">{KIND[memory.kind]}</span>
        <span
          className={`badge provenance-${memory.provenance}`}
          data-testid="memory-provenance"
          title={`可信度 ${Math.round(memory.confidence * 100)}%`}
        >
          {PROVENANCE[memory.provenance]} · {Math.round(memory.confidence * 100)}%
        </span>
        {memory.sensitivity !== "normal" && (
          <span className="badge">{SENSITIVITY[memory.sensitivity]}</span>
        )}
        <SourceLine memory={memory} />
      </div>
      <div className="memory-actions" aria-describedby={masked ? undefined : bodyId}>
        {memory.sensitivity === "secret" && !editing && (
          <button type="button" onClick={() => setRevealed(!revealed)}>
            {revealed ? "隐藏" : "显示"}
          </button>
        )}
        {editing ? (
          <>
            <button
              type="button"
              className="primary"
              disabled={pending || !draft.trim()}
              onClick={() => act(() => onCorrect(draft.trim()), () => setEditing(false))}
            >
              保存改正
            </button>
            <button type="button" disabled={pending} onClick={() => setEditing(false)}>
              取消
            </button>
          </>
        ) : (
          <>
            {confirmable && (
              <button type="button" disabled={pending} onClick={() => act(onConfirm)}>
                确认没错
              </button>
            )}
            {editable && (
              <button
                type="button"
                disabled={pending || masked}
                title={masked ? "先按“显示”再改正" : undefined}
                onClick={() => {
                  setDraft(memory.body);
                  setEditing(true);
                }}
              >
                改正
              </button>
            )}
            {confirmingDelete ? (
              <>
                {/* "不删" takes the spot where "删除" was, so a double-click cannot delete. */}
                <button type="button" disabled={pending} onClick={() => setConfirmingDelete(false)}>
                  不删
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={pending}
                  onClick={() => act(onDelete)}
                >
                  确定删除
                </button>
              </>
            ) : (
              <button type="button" disabled={pending} onClick={() => setConfirmingDelete(true)}>
                删除
              </button>
            )}
          </>
        )}
      </div>
    </li>
  );
}
