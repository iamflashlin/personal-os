import { useState } from "react";
import type { TriageGroup, TriageView } from "./api";
import { MailLine, type MailRow } from "./MailView";

const PREVIEW = 3; // mails shown in a group before 「展开全部」

/** Groups worth a click first: the ones that ask something of the user come first. */
export function groupHint(g: TriageGroup): string {
  if (g.kind === "due_soon") return "先处理这几封";
  if (g.kind === "overdue") return "截止已过：去 Canvas 确认交了没有，再全部标为已处理";
  if (g.kind === "grades") return "只是成绩通知，看一眼就可以全部标为已处理";
  return "";
}

export function TriagePanel({
  view,
  rows,
  onHandled,
  busy,
  onHandle,
  onUndo,
  onRule,
}: {
  view: TriageView;
  rows: Map<string, MailRow>;
  onHandled: (itemId: string, handled: boolean) => void;
  busy: boolean;
  onHandle: (group: TriageGroup, saveRule: boolean) => void;
  onUndo: (batchId: string) => void;
  onRule: (ruleId: string, enabled: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saveRule, setSaveRule] = useState<Record<string, boolean>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const lastApplied = view.recent.find((b) => b.status === "applied");
  return (
    <section className="triage" data-testid="triage">
      <div className="triage-head">
        <strong data-testid="triage-open">未处理 {view.open_count} 封</strong>
        <button
          type="button"
          data-testid="triage-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "收起整理" : "帮我整理"}
        </button>
        {lastApplied && (
          <button
            type="button"
            data-testid="triage-undo"
            disabled={busy}
            onClick={() => onUndo(lastApplied.id)}
          >
            撤销「{lastApplied.label}」（{lastApplied.count} 封）
          </button>
        )}
      </div>
      {open && (
        <>
          {view.groups.length === 0 && <p className="muted">没有未处理的邮件了。</p>}
          <ul className="triage-groups">
            {view.groups.map((g) => (
              <li key={g.key} className="triage-group" data-testid="triage-group">
                <div>
                  <strong>{g.label}</strong> <span className="badge">{g.count} 封</span>
                </div>
                {groupHint(g) && <p className="muted">{groupHint(g)}</p>}
                {/* The group's own mails, each opens like in the list below. */}
                <ul className="memories triage-mails" data-testid="triage-mails">
                  {(expanded[g.key] ? g.item_ids : g.item_ids.slice(0, PREVIEW)).map((id) => {
                    const row = rows.get(id);
                    return row ? (
                      <MailLine key={id} row={row} onHandled={onHandled} />
                    ) : (
                      <li key={id} className="muted">
                        （这封邮件不在当前列表里）
                      </li>
                    );
                  })}
                </ul>
                {g.count > PREVIEW && (
                  <button
                    type="button"
                    className="link-button"
                    data-testid="triage-expand"
                    aria-expanded={!!expanded[g.key]}
                    onClick={() => setExpanded((e) => ({ ...e, [g.key]: !e[g.key] }))}
                  >
                    {expanded[g.key] ? "收起" : `展开全部 ${g.count} 封`}
                  </button>
                )}
                <div className="triage-actions">
                  <button
                    type="button"
                    data-testid="triage-handle"
                    disabled={busy}
                    onClick={() => onHandle(g, !!saveRule[g.key])}
                  >
                    全部标为已处理（{g.count}）
                  </button>
                  {g.rule !== null && (
                    <label className="muted">
                      <input
                        type="checkbox"
                        data-testid="triage-save-rule"
                        checked={!!saveRule[g.key]}
                        disabled={busy}
                        onChange={(e) => setSaveRule((s) => ({ ...s, [g.key]: e.target.checked }))}
                      />
                      以后也这样（{g.rule_description}）
                    </label>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {view.rules.length > 0 && (
            <div className="triage-rules" data-testid="triage-rules">
              <strong>规则</strong>
              <ul>
                {view.rules.map((r) => (
                  <li key={r.id}>
                    <label>
                      <input
                        type="checkbox"
                        checked={r.enabled}
                        disabled={busy}
                        onChange={(e) => onRule(r.id, e.target.checked)}
                      />
                      {r.description}（现在覆盖 {r.matched} 封）
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
