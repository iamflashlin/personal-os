import { useCallback, useEffect, useState } from "react";
import {
  type Api,
  ApiError,
  type CourseMap,
  type ExamMap,
  type MapConcept,
  type MapExam,
  type MasteryState,
} from "./api";
import { safeLink } from "./ConnectionsView";

export const MASTERY: Record<MasteryState, string> = {
  not_tested: "未测试",
  seen: "已接触",
  practicing: "还不稳",
  verified: "已掌握",
  needs_review: "要复习",
};

const SUGGESTED_SHOWN = 8; // the rest behind 展开全部: a long list is not a plan

const MASTERY_ORDER: MasteryState[] = ["not_tested", "seen", "practicing", "verified", "needs_review"];

function Ext({ href, children }: { href: string; children: React.ReactNode }) {
  const link = safeLink(href);
  if (!link) return <>{children}</>;
  return (
    <a href={link} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  );
}

function when(at: string | null): string {
  return at
    ? new Date(at).toLocaleString("zh-CN", {
        month: "numeric",
        day: "numeric",
        weekday: "short",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "时间待定";
}

export function countdown(days: number | null): string {
  if (days === null) return "";
  if (days < 0) return "已考";
  if (days === 0) return "今天";
  return `还有 ${days} 天`;
}

function SectionRow({
  s,
  concepts,
  byKey,
  onMastery,
  why,
}: {
  s: MapConcept;
  concepts: MapConcept[];
  byKey: Map<string, MapConcept>;
  onMastery: (key: string, state: MasteryState | "") => void;
  why?: string;
}) {
  const [open, setOpen] = useState(false);
  const m = s.mastery;
  return (
    <li className={`km-section mastery-${m?.state ?? "none"}`} data-testid="km-section">
      <button type="button" className="km-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span className="km-key">{s.key}</span>
        <span className="km-title">
          {s.title_zh || s.title}
          {s.title_zh && <span className="muted"> · {s.title}</span>}
        </span>
        {m && <span className={`badge mastery mastery-${m.state}`}>{MASTERY[m.state]}</span>}
      </button>
      {why && <p className="km-why">{why}</p>}
      <div className="km-meta">
        {s.page !== null && s.material_url && (
          <Ext href={s.material_url}>讲义 第 {s.page} 页</Ext>
        )}
        {s.page !== null && !s.material_url && <span className="muted">讲义 第 {s.page} 页</span>}
        {s.resources.map((r) => (
          <Ext key={r.url + r.title} href={r.url}>
            <span className="chip">{r.title}</span>
          </Ext>
        ))}
        {s.assessments.map((a) => (
          <Ext key={a.url + a.title} href={a.url}>
            <span className={`chip score${a.percent === null ? "" : a.percent >= 90 ? " good" : a.percent < 70 ? " bad" : ""}`}>
              {a.title}
              {a.percent !== null && ` · ${a.percent}%`}
            </span>
          </Ext>
        ))}
      </div>
      {open && (
        <div className="km-detail" data-testid="km-detail">
          {m && <p className="muted">{m.source === "user" ? "你自己标的" : m.note}</p>}
          {concepts.length > 0 && (
            <ul className="km-concepts">
              {concepts.map((c) => (
                <li key={c.key}>
                  {c.title_zh || c.title}
                  {c.title_zh && <span className="muted"> · {c.title}</span>}
                  {c.page !== null && <span className="muted"> · 第 {c.page} 页</span>}
                </li>
              ))}
            </ul>
          )}
          {s.prereq.length > 0 && (
            <p className="muted">
              要先会：
              {s.prereq.map((p) => byKey.get(p)?.title_zh || byKey.get(p)?.title || p).join("、")}
              {s.prereq_origin === "ai" && <span className="badge ai">AI 补充</span>}
            </p>
          )}
          <label className="km-set">
            <span className="label">我的掌握情况</span>
            <select
              value={m?.source === "user" ? m.state : ""}
              onChange={(e) => onMastery(s.key, e.target.value as MasteryState | "")}
            >
              <option value="">按练习成绩自动判断</option>
              {MASTERY_ORDER.map((st) => (
                <option key={st} value={st}>
                  {MASTERY[st]}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </li>
  );
}

function ExamCard({ e, onOpen }: { e: MapExam; onOpen: () => void }) {
  const done = e.days_left !== null && e.days_left < 0;
  return (
    <div className={`exam-card${done ? " past" : ""}`} data-testid="exam-card">
      <div className="exam-top">
        <strong>{e.name}</strong>
        <span className={`badge${!done && e.days_left !== null && e.days_left <= 7 ? " warn" : ""}`}>
          {countdown(e.days_left)}
        </span>
      </div>
      <div className="muted">{when(e.at)}</div>
      <div className="muted">范围 {e.scope.length} 节</div>
      {e.grade?.percent !== null && e.grade?.percent !== undefined && (
        <div>成绩 {e.grade.percent}%</div>
      )}
      <button type="button" className="primary" onClick={onOpen}>
        打开复习地图
      </button>
    </div>
  );
}

function ExamView({
  exam,
  map,
  byKey,
  onBack,
  onMastery,
}: {
  exam: ExamMap;
  map: CourseMap;
  byKey: Map<string, MapConcept>;
  onBack: () => void;
  onMastery: (key: string, state: MasteryState | "") => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const concepts = (key: string) => map.concepts.filter((c) => c.parent === key && c.kind === "concept");
  const e = exam.exam;
  return (
    <div className="exam-map" data-testid="exam-map">
      <button type="button" className="link-button" onClick={onBack}>
        ← 返回课程
      </button>
      <section className="exam-hero">
        <div>
          <h2>{e.name} 复习地图</h2>
          <p className="muted">
            {[when(e.at), countdown(e.days_left), e.scope_source && `范围来源：${e.scope_source}`]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="exam-links">
          {e.resources.map((r) => (
            <Ext key={r.url + r.title} href={r.url}>
              <span className="chip">{r.title}</span>
            </Ext>
          ))}
        </div>
      </section>
      <div className="exam-grid">
        <section>
          <h2>建议先复习</h2>
          {exam.suggested.length === 0 ? (
            <p className="muted">范围内每一节的练习成绩都很好。考前做一遍复习题，再看下面的检查清单。</p>
          ) : (
            <ol className="suggested">
              {(showAll ? exam.suggested : exam.suggested.slice(0, SUGGESTED_SHOWN)).map((k) => (
                <li key={k}>
                  <strong>
                    {k} {byKey.get(k)?.title_zh || byKey.get(k)?.title}
                  </strong>
                  <div className="muted">{exam.why[k]}</div>
                </li>
              ))}
            </ol>
          )}
          {exam.suggested.length > SUGGESTED_SHOWN && (
            <button type="button" className="link-button" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "只看前几项" : `展开全部 ${exam.suggested.length} 项`}
            </button>
          )}
        </section>
        <section>
          <h2>考前检查清单</h2>
          <ul className="checklist">
            {exam.checklist.map((c, i) => (
              <li key={`${i}-${c.text.slice(0, 12)}`}>
                {c.text}
                {c.source && <div className="rule-source">原文：{c.source}</div>}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section>
        <h2>考试范围（{exam.sections.length} 节）</h2>
        <ul className="km-list">
          {exam.sections.map((s) => (
            <SectionRow
              key={s.key}
              s={s}
              concepts={concepts(s.key)}
              byKey={byKey}
              onMastery={onMastery}
              why={exam.why[s.key]}
            />
          ))}
        </ul>
      </section>
      {exam.prerequisites.length > 0 && (
        <section>
          <h2>范围外，但要先会的</h2>
          <p className="muted">这些不在考试范围里，但考试范围内的内容用得上（前置关系是 AI 补充的）。</p>
          <ul className="km-list">
            {exam.prerequisites.map((s) => (
              <SectionRow key={s.key} s={s} concepts={[]} byKey={byKey} onMastery={onMastery} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export function CourseView({ api }: { api: Api }) {
  const [codes, setCodes] = useState<string[] | null>(null);
  const [code, setCode] = useState("");
  const [map, setMap] = useState<CourseMap | null>(null);
  const [exam, setExam] = useState<ExamMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fail = (err: unknown) => setError(err instanceof ApiError ? err.detail : String(err));

  useEffect(() => {
    api
      .courseMaps()
      .then((cs) => {
        setCodes(cs);
        if (cs.length > 0) setCode((c) => c || cs[0]);
      })
      .catch(fail);
  }, [api]);

  const load = useCallback(async () => {
    if (!code) return;
    try {
      setMap(await api.courseMap(code));
      setError(null);
    } catch (err) {
      fail(err);
    }
  }, [api, code]);
  useEffect(() => {
    void load();
  }, [load]);

  async function openExam(name: string) {
    try {
      setExam(await api.examMap(code, name));
    } catch (err) {
      fail(err);
    }
  }

  async function mastery(key: string, state: MasteryState | "") {
    try {
      if (state) await api.setMastery(code, key, state);
      else await api.clearMastery(code, key);
      await load();
      if (exam) setExam(await api.examMap(code, exam.exam.name));
    } catch (err) {
      fail(err);
    }
  }

  if (error)
    return (
      <p className="error" role="alert">
        {error}
      </p>
    );
  if (codes === null) return <p>加载中…</p>;
  if (codes.length === 0)
    return <p className="muted">还没有课程知识地图。整理好一门课的讲义后，这里会显示它的章节、知识点和考试复习地图。</p>;
  if (!map) return <p>加载中…</p>;
  const byKey = new Map(map.concepts.map((c) => [c.key, c]));
  if (exam) return <ExamView exam={exam} map={map} byKey={byKey} onBack={() => setExam(null)} onMastery={(k, s) => void mastery(k, s)} />;

  const chapters = map.concepts.filter((c) => c.kind === "chapter");
  const sections = map.concepts.filter((c) => c.kind === "section");
  const counts = MASTERY_ORDER.map((st) => [st, sections.filter((s) => s.mastery?.state === st).length] as const);
  return (
    <div className="course" data-testid="course">
      {codes.length > 1 && (
        <div className="mail-filters" role="group" aria-label="课程">
          {codes.map((c) => (
            <button key={c} type="button" className={c === code ? "active" : ""} onClick={() => { setExam(null); setCode(c); }}>
              {c}
            </button>
          ))}
        </div>
      )}
      <section className="course-hero">
        <div>
          <h2>{map.course_code}</h2>
          <p className="muted">
            {sections.length} 节 · 讲义：{map.material || "—"}
          </p>
        </div>
        <div className="mastery-bar" aria-label="掌握情况">
          {counts
            .filter(([, n]) => n > 0)
            .map(([st, n]) => (
              <span key={st} className={`badge mastery mastery-${st}`}>
                {MASTERY[st]} {n}
              </span>
            ))}
        </div>
      </section>
      {map.exams.length > 0 && (
        <div className="exam-strip">
          {map.exams.map((e) => (
            <ExamCard key={e.name} e={e} onOpen={() => void openExam(e.name)} />
          ))}
        </div>
      )}
      {chapters.map((ch) => (
        <section key={ch.key} data-testid="km-chapter">
          <h2>
            {ch.title_zh || ch.title}
            {ch.title_zh && <span className="muted"> · {ch.title}</span>}
          </h2>
          <ul className="km-list">
            {sections
              .filter((s) => s.parent === ch.key)
              .map((s) => (
                <SectionRow
                  key={s.key}
                  s={s}
                  concepts={map.concepts.filter((c) => c.parent === s.key && c.kind === "concept")}
                  byKey={byKey}
                  onMastery={(k, st) => void mastery(k, st)}
                />
              ))}
          </ul>
        </section>
      ))}
      <p className="muted">
        章节、知识点和页码来自老师的讲义；“要先会”的前置关系是 AI 补充的。掌握情况按你的小测和作业成绩推断，你可以自己改。
      </p>
    </div>
  );
}
