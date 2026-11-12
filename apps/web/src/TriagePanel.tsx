import { useState } from "react";
import type { TriageGroup, TriageView } from "./api";

const PREVIEW = 3;

/** Groups worth a click first: the ones that ask something of the user come first. */
export function groupHint(g: TriageGroup): string {
  if (g.kind === "due_soon") return "先处理这几封";
  if (g.kind === "overdue") return "截止已过：去 Canvas 确认交了没有，再全部标为已处理";
  if (g.kind === "grades") return "只是成绩通知，看一眼就可以全部标为已处理";
  return "";
}

export function TriagePanel({
  view,
  titles,
  busy,
  onHandle,
  onUndo,
  onRule,
}: {
  view: TriageView;
  titles: Map<string, string>;
  busy: boolean;
  onHandle: (group: TriageGroup, saveRule: boolean) => void;
  onUndo: (batchId: string) => void;
  onRule: (ruleId: string, enabled: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saveRule, setSaveRule] = useState<Record<string, boolean>>({});
  const lastApplied = view.recent.find((b) => b.status === "applied");
  return (
    <section className="triage" data-testid="triage">
      <div className="triage-head">
        <strong data-testid="triage-open">未处理 {view.open_count} 封</strong>
        <span className="muted">（未读 {view.unread_count} 封）</span>
        <button type="button" data-testid="triage-toggle" onClick={() => setOpen((v) => !v)}>
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
                <ul className="triage-preview">
                  {g.item_ids.slice(0, PREVIEW).map((id) => (
                    <li key={id}>{titles.get(id) ?? "（邮件）"}</li>
                  ))}
                  {g.count > PREVIEW && <li className="muted">…还有 {g.count - PREVIEW} 封</li>}
                </ul>
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
