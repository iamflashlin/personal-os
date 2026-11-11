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

export function MemoryView({ api }: { api: Api }) {
  const [memories, setMemories] = useState<Memory[] | null>(null);
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const latest = useRef(0);

  const reload = useCallback(
    async (q: string) => {
      const ticket = ++latest.current;
      try {
        const found = q.trim()
          ? (await api.searchMemories(q.trim())).map((hit) => hit.memory)
          : await api.memories();
        if (ticket === latest.current) setMemories(found);
      } catch (err) {
        setError(errorText(err));
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
      setError(null);
      return true;
    } catch (err) {
      setError(errorText(err));
      return false;
    } finally {
      await reload(activeQuery);
    }
  };

  const search = (event: FormEvent) => {
    event.preventDefault();
    setActiveQuery(query);
  };

  return (
    <section data-testid="memories">
      <h2>记忆</h2>
      <p className="muted">
        Personal OS 记住的关于你的事。“AI 推测”的内容在你确认前只作参考；机密内容不会出现在搜索结果里。
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
              setActiveQuery("");
            }}
          >
            显示全部
          </button>
        )}
      </form>
      <NewMemoryForm onCreate={(m) => run(() => api.createMemory(m))} />
      {memories === null && <p>加载中…</p>}
      {memories?.length === 0 && (
        <p className="muted">{activeQuery ? "没有找到匹配的记忆" : "还没有记忆"}</p>
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
  onCreate: (memory: { kind: MemoryKind; body: string; sensitivity: Sensitivity }) => Promise<boolean>;
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
    if (ok) setBody("");
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
  const [draft, setDraft] = useState(memory.body);
  const [revealed, setRevealed] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [pending, setPending] = useState(false);
  const masked = memory.sensitivity === "secret" && !revealed;
  const confirmable = memory.provenance === "raw" || memory.provenance === "ai_inferred";

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
          <span className="memory-body">{masked ? "••••••（机密）" : memory.body}</span>
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
      </div>
      <div className="memory-actions">
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
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                setDraft(memory.body);
                setEditing(true);
              }}
            >
              改正
            </button>
            {confirmingDelete ? (
              <>
                <button type="button" className="danger" disabled={pending} onClick={() => act(onDelete)}>
                  确定删除
                </button>
                <button type="button" disabled={pending} onClick={() => setConfirmingDelete(false)}>
                  不删
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
