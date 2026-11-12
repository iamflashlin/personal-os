import { useCallback, useEffect, useState } from "react";
import {
  type Api,
  ApiError,
  type CourseGpa,
  type CourseProfile,
  type GpaView as Gpa,
  type WorkItem,
} from "./api";
import { safeLink } from "./ConnectionsView";

function when(at: string | null): string {
  if (!at) return "";
  return new Date(at).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "MATH D001A" -> "MATH 1A", "CIS D022A" -> "CIS 22A", "ECON C2002" -> "ECON 2002". */
export function shortCode(code: string): string {
  const m = /^([A-Z]+)\s+[A-Z]?0*(\d+[A-Z]?)$/.exec(code.trim());
  return m ? `${m[1]} ${m[2]}` : code;
}

/** The last column of a course's line: what the remaining work must average to keep
 * the letter it has now ("" when there is no letter or no such target). */
export function keepLine(c: Pick<CourseGpa, "letter" | "lines">): string {
  const line = c.lines.find((l) => l.label.startsWith(`${c.letter}（`));
  if (!c.letter || !line) return "";
  if (line.status === "safe" || line.status === "done") return "已稳";
  if (line.needed === null) return "";
  return line.status === "out_of_reach" ? `${line.needed}%，很难` : `${line.needed}%`;
}

function Work({ w }: { w: WorkItem }) {
  const link = safeLink(w.url);
  const score = w.score !== null && w.points ? `${w.score}/${w.points}` : "";
  const flag = w.state === "missing" ? "缺交" : w.state === "late" ? "迟交" : "";
  return (
    <li className="g-work">
      <span className="g-work-title">
        {link ? (
          <a href={link} target="_blank" rel="noreferrer noopener">
            {w.title}
          </a>
        ) : (
          w.title
        )}
        {flag && <span className="g-flag"> {flag}</span>}
      </span>
      <span className="g-work-meta">{score || when(w.due)}</span>
    </li>
  );
}

/** Materials grouped by module, in Canvas order. */
export function byModule(c: CourseGpa): [string, CourseGpa["materials"]][] {
  const groups = new Map<string, CourseGpa["materials"]>();
  for (const m of c.materials) {
    const key = m.module || "其他";
    groups.set(key, [...(groups.get(key) ?? []), m]);
  }
  return [...groups.entries()];
}

export const RULE_KIND: Record<string, string> = {
  grading: "评分",
  late: "迟交",
  makeup: "补考",
  exam: "考试",
  gate: "硬门槛",
  integrity: "诚信",
  other: "其他",
};

export const BASIS: Record<string, string> = {
  syllabus: "按大纲的类别加权",
  canvas: "Canvas 的当前分",
  none: "还没有成绩",
};

function RulesCard({
  p,
  onConfirm,
}: {
  p: CourseProfile;
  onConfirm: (p: CourseProfile) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rules-card" data-testid="rules-card">
      <button type="button" className="g-more" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        规则卡
        <span className="g-more-note">{p.confirmed_at ? "已确认" : "待你确认"}</span>
      </button>
      {open && (
        <div className="rules-body">
          <p className="muted">
            {p.units !== null && `${p.units} 学分（${p.units_source}）`}
            <br />
            分数线：{p.scale.map((b) => `${b.letter} ≥${b.min}`).join("　")}（{p.scale_source}）
          </p>
          {p.categories.length > 0 && (
            <p className="muted">类别：{p.categories.map((c) => `${c.name} ${c.weight}%`).join("、")}</p>
          )}
          <ul className="rules">
            {p.rules.map((r, i) => (
              <li key={`${i}-${r.kind}`}>
                <span className="rule-kind">{RULE_KIND[r.kind] ?? r.kind}</span>
                {r.text}
                {r.source && <div className="rule-source">{r.source}</div>}
              </li>
            ))}
          </ul>
          {p.open_questions.length > 0 && (
            <ul className="rules-open">
              {p.open_questions.map((q, i) => (
                <li key={`${i}-${q.slice(0, 20)}`}>待确认：{q}</li>
              ))}
            </ul>
          )}
          <p className="rule-source">来源：{p.syllabus_source}</p>
          {!p.confirmed_at && (
            <button type="button" onClick={() => onConfirm(p)}>
              我对照过大纲，没问题
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="g-block">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

function Detail({
  c,
  profile,
  onConfirm,
}: {
  c: CourseGpa;
  profile?: CourseProfile;
  onConfirm: (p: CourseProfile) => void;
}) {
  const [showMaterials, setShowMaterials] = useState(false);
  const groups = c.basis === "syllabus" ? [] : c.groups.filter((g) => g.total > 0 || g.weight > 0);
  return (
    <div className="g-detail">
      {c.missing.length > 0 && (
        <div className="g-block" data-testid="gpa-missing">
          <h3>缺交</h3>
          <ul>
            {c.missing.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </div>
      )}
      {c.upcoming.length > 0 && (
        <Block title="接下来两周">
          <ul>
            {c.upcoming.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </Block>
      )}
      {c.lines.length > 0 && (
        <Block title="想拿到，之后平均要">
          <ul className="g-targets">
            {c.lines.map((l) => (
              <li key={l.label} className={l.status === "out_of_reach" ? "g-far" : undefined}>
                <span>{l.label}</span>
                <strong>{l.needed !== null ? `${l.needed}%` : "—"}</strong>
              </li>
            ))}
          </ul>
        </Block>
      )}
      {groups.length > 0 && (
        <Block title="成绩构成">
          <table className="gpa-groups">
            <tbody>
              {groups.map((g, i) => (
                <tr key={`${i}-${g.name}`}>
                  <td>{g.name}</td>
                  <td className="muted">{c.weighted ? `占 ${g.weight}%` : ""}</td>
                  <td>{g.percent !== null ? `${g.percent}%` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Block>
      )}
      {c.recent.length > 0 && (
        <Block title="最近出分">
          <ul>
            {c.recent.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </Block>
      )}
      {c.notes.length > 0 && (
        <Block title="要留意">
          <ul className="gpa-notes" data-testid="gpa-notes">
            {c.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Block>
      )}
      <div className="g-foot">
        <span className="muted">
          {BASIS[c.basis] ?? c.basis}
          {c.units !== null && ` · ${c.units} 学分`}
          {c.completion.late > 0 && ` · 迟交过 ${c.completion.late} 次`}
        </span>
        {profile && <RulesCard p={profile} onConfirm={onConfirm} />}
        {c.materials.length > 0 && (
          <div>
            <button
              type="button"
              className="g-more"
              aria-expanded={showMaterials}
              onClick={() => setShowMaterials((v) => !v)}
            >
              课件<span className="g-more-note">{c.materials.length}</span>
            </button>
            {showMaterials &&
              byModule(c).map(([module, items]) => (
                <div key={module} className="gpa-module">
                  <strong>{module}</strong>
                  <ul>
                    {items.map((m) => {
                      const link = safeLink(m.url);
                      return (
                        <li key={`${module}-${m.title}-${m.url}`}>
                          {link ? (
                            <a href={link} target="_blank" rel="noreferrer noopener">
                              {m.title}
                            </a>
                          ) : (
                            m.title
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Course({
  c,
  profile,
  onConfirm,
}: {
  c: CourseGpa;
  profile?: CourseProfile;
  onConfirm: (p: CourseProfile) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className={open ? "gpa-course open" : "gpa-course"} data-testid="gpa-course">
      <button
        type="button"
        className="gpa-head"
        aria-expanded={open}
        title={c.code}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="g-name">{shortCode(c.code)}</span>
        <strong className="gpa-grade">{c.letter || "—"}</strong>
        <span className="g-percent">{c.percent !== null ? `${c.percent}%` : ""}</span>
        <span className="g-line">
          {c.completion.missing > 0 && <span className="g-flag">缺交 {c.completion.missing}　</span>}
          {keepLine(c) && <span className="g-keep">{keepLine(c)}</span>}
        </span>
      </button>
      {open && <Detail c={c} profile={profile} onConfirm={onConfirm} />}
    </section>
  );
}

export function GpaView({ api }: { api: Api }) {
  const [view, setView] = useState<Gpa | null>(null);
  const [profiles, setProfiles] = useState<CourseProfile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const [gpa, ps] = await Promise.all([api.gpa(), api.profiles()]);
      setView(gpa);
      setProfiles(ps);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? `（${err.status}）${err.detail}` : String(err));
    }
  }, [api]);
  useEffect(() => {
    void load();
  }, [load]);

  if (error)
    return (
      <p className="error" role="alert">
        连不上 Hub：{error}
      </p>
    );
  if (!view) return <p>加载中…</p>;
  if (view.courses.length === 0)
    return <p className="muted">还没有课程成绩。在“连接”页接入 Canvas 后，这里会按课程整理成绩和作业。</p>;
  return (
    <div className="gpa" data-testid="gpa">
      <div className="g-hero">
        <strong>{view.gpa !== null ? view.gpa.toFixed(2) : "—"}</strong>
        <span>
          本学期 GPA
          {view.gpa_weighted && view.units_total !== null && ` · ${view.units_total} 学分`}
        </span>
      </div>
      <div className="g-list">
        <div className="gpa-head g-cols" aria-hidden="true">
          <span>课程</span>
          <span>等级</span>
          <span className="g-percent">现在</span>
          <span className="g-line">保住等级，之后平均要</span>
        </div>
        {view.courses.map((c) => (
          <Course
            key={c.integration_item_id}
            c={c}
            profile={profiles.find((p) => p.code === c.code)}
            onConfirm={(p) =>
              void api
                .confirmProfile(p.code, p.version)
                .then(load)
                .catch((err) => setError(err instanceof ApiError ? err.detail : String(err)))
            }
          />
        ))}
      </div>
      <details className="g-how">
        <summary>这些数字怎么算的</summary>
        <p>
          {view.gpa_note}
          只算已评分的作业，缺交按 0 分；“之后平均要多少”是估算。
        </p>
      </details>
    </div>
  );
}
