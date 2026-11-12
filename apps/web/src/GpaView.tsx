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

const STATE_LABEL: Record<string, string> = {
  missing: "缺交",
  late: "迟交",
  submitted: "已提交",
  graded: "已评分",
  excused: "免做",
  upcoming: "未交",
  open: "未交",
  awaiting_grade: "待评分",
};

const LINE_STATUS: Record<string, string> = {
  safe: "已稳",
  reachable: "可达",
  out_of_reach: "难以达到",
  done: "已定",
};

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

function Work({ w }: { w: WorkItem }) {
  const link = safeLink(w.url);
  const score = w.score !== null && w.points ? ` ${w.score}/${w.points}` : "";
  return (
    <li className="gpa-work">
      <span className={`badge ${w.state === "missing" ? "submission-缺交" : ""}`}>
        {STATE_LABEL[w.state] ?? w.state}
      </span>{" "}
      {link ? (
        <a href={link} target="_blank" rel="noreferrer noopener">
          {w.title}
        </a>
      ) : (
        w.title
      )}
      <span className="muted">
        {" "}
        {when(w.due)}
        {w.group && ` · ${w.group}`}
        {score}
      </span>
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
  syllabus: "按大纲的权重算",
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
      <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {open ? "收起规则卡" : `规则卡（${p.rules.length} 条，来自大纲）`}
      </button>
      {p.confirmed_at ? (
        <span className="badge ok">已确认</span>
      ) : (
        <span className="badge warn">待你确认</span>
      )}
      {open && (
        <div className="rules-body">
          <p className="muted">
            {p.units !== null && `${p.units} 学分（${p.units_source}）`}
            <br />
            分数线：{p.scale.map((b) => `${b.letter} ≥${b.min}`).join("　")}（{p.scale_source}）
          </p>
          {p.categories.length > 0 && (
            <p className="muted">
              按大纲的类别算：{p.categories.map((c) => `${c.name} ${c.weight}%`).join("、")}
            </p>
          )}
          <ul className="rules">
            {p.rules.map((r) => (
              <li key={r.text}>
                <span className={`badge rule-${r.kind}`}>{RULE_KIND[r.kind] ?? r.kind}</span> {r.text}
                {r.source && <div className="rule-source">原文：{r.source}</div>}
              </li>
            ))}
          </ul>
          {p.open_questions.length > 0 && (
            <div className="rules-open">
              <strong>待确认</strong>
              <ul>
                {p.open_questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="muted">来源：{p.syllabus_source}</p>
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

function Course({
  c,
  profile,
  onConfirm,
}: {
  c: CourseGpa;
  profile?: CourseProfile;
  onConfirm: (p: CourseProfile) => void;
}) {
  const [showMaterials, setShowMaterials] = useState(false);
  const done = c.completion;
  return (
    <section className="gpa-course" data-testid="gpa-course">
      <div className="gpa-head">
        <h2>{c.code}</h2>
        <strong className="gpa-grade">{c.letter || "—"}</strong>
        <span>{c.percent !== null ? `${c.percent}%` : "还没有成绩"}</span>
        <span className="muted">
          {BASIS[c.basis] ?? c.basis}
          {c.units !== null && ` · ${c.units} 学分`}
          {c.letter_source === "syllabus" ? " · 等级按大纲分数线" : ""}
        </span>
      </div>
      {c.notes.length > 0 && (
        <ul className="gpa-notes" data-testid="gpa-notes">
          {c.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {profile && <RulesCard p={profile} onConfirm={onConfirm} />}
      <p className="muted">
        作业完成 {done.done}/{done.due_so_far}
        {done.missing > 0 && `，缺交 ${done.missing}`}
        {done.late > 0 && `，迟交 ${done.late}`}
        {c.weighted ? "　按类别加权" : "　按总分计算"}
      </p>
      {c.groups.length > 0 && (
        <table className="gpa-groups">
          <tbody>
            {c.groups
              .filter((g) => g.total > 0 || g.weight > 0)
              .map((g, i) => (
                <tr key={`${i}-${g.name}`}>
                  <td>{g.name}</td>
                  <td>{c.weighted ? `${g.weight}%` : ""}</td>
                  <td>{g.percent !== null ? `${g.percent}%` : "—"}</td>
                  <td className="muted">
                    已评 {g.graded}/{g.total}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      <div className="gpa-lines">
        {c.lines.map((l) => (
          <span key={l.label} className="badge">
            {l.label}：
            {l.needed !== null ? `剩下的平均要 ${l.needed}%` : "已无待评分项"}（{LINE_STATUS[l.status] ?? l.status}）
          </span>
        ))}
      </div>
      {c.missing.length > 0 && (
        <div data-testid="gpa-missing">
          <h3>缺交</h3>
          <ul>
            {c.missing.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </div>
      )}
      {c.upcoming.length > 0 && (
        <div>
          <h3>接下来 14 天</h3>
          <ul>
            {c.upcoming.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </div>
      )}
      {c.recent.length > 0 && (
        <div>
          <h3>最近出分</h3>
          <ul>
            {c.recent.map((w) => (
              <Work key={w.item_id} w={w} />
            ))}
          </ul>
        </div>
      )}
      {c.materials.length > 0 && (
        <div>
          <button type="button" className="link-button" onClick={() => setShowMaterials((v) => !v)}>
            {showMaterials ? "收起课件" : `课件（${c.materials.length}）`}
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
      <p className="headline">
        <strong>本学期 GPA 估算：{view.gpa !== null ? view.gpa.toFixed(2) : "—"}</strong>
        <span className="muted">
          {" "}
          {view.gpa_weighted && view.units_total !== null && `（共 ${view.units_total} 学分）`}
          {view.gpa_note}
        </span>
      </p>
      <p className="muted">
        有规则卡的课按大纲的分数线和权重算；只算已评分的作业，缺交的按 0 分。“剩下的平均要多少”是估算。
      </p>
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
  );
}
