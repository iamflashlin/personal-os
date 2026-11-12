import { useCallback, useEffect, useState } from "react";
import { type Api, ApiError, type CourseGpa, type GpaView as Gpa, type WorkItem } from "./api";
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

function Course({ c }: { c: CourseGpa }) {
  const [showMaterials, setShowMaterials] = useState(false);
  const done = c.completion;
  return (
    <section className="gpa-course" data-testid="gpa-course">
      <div className="gpa-head">
        <h2>{c.code}</h2>
        <strong className="gpa-grade">{c.current_grade || "—"}</strong>
        <span>{c.current_score !== null ? `${c.current_score}%` : "还没有成绩"}</span>
        <span className="muted">{c.name}</span>
      </div>
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
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setView(await api.gpa());
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
        <span className="muted"> {view.gpa_note}</span>
      </p>
      <p className="muted">
        分数是 Canvas 的“当前分”（只算已评分的作业）。“剩下的平均要多少”是估算：缺交的作业按 0 分算，分数线（A 90% 等）是常见标准，以教学大纲为准。
      </p>
      {view.courses.map((c) => (
        <Course key={c.integration_item_id} c={c} />
      ))}
    </div>
  );
}
