import { useCallback, useEffect, useRef, useState } from "react";
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
import { shortCode } from "./GpaView";

export const MASTERY: Record<MasteryState, string> = {
  not_tested: "未测试",
  seen: "已接触",
  practicing: "还不稳",
  verified: "已掌握",
  needs_review: "要复习",
};

const SOURCE_ZH: Record<string, string> = { syllabus: "课程大纲" };

const SUGGESTED_SHOWN = 8; // the rest behind 展开全部: a long list is not a plan

const MASTERY_ORDER: MasteryState[] = ["needs_review", "practicing", "seen", "not_tested", "verified"];

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

/** The last column of a section row: its graded work in one short phrase. */
export function workText(s: Pick<MapConcept, "assessments">): string {
  const scored = s.assessments.map((a) => a.percent).filter((p): p is number => p !== null);
  if (scored.length === 0) return s.assessments.length > 0 ? `${s.assessments.length} 项未出分` : "";
  const avg = Math.round(scored.reduce((a, b) => a + b, 0) / scored.length);
  return `${scored.length} 项 · ${avg}%`;
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
    <li className={open ? "km-section open" : "km-section"} data-testid="km-section">
      <button type="button" className="km-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {/* A concept (a prerequisite like "U4-fiscal") shows the section it belongs to. */}
        <span className="km-key">{s.kind === "concept" ? s.parent : s.key}</span>
        <span className="km-title">
          {s.title_zh || s.title}
          {why && <span className="km-why">{why}</span>}
        </span>
        <span className="km-work">{workText(s)}</span>
        <span className={`km-state mastery-${m?.state ?? "none"}`}>{m ? MASTERY[m.state] : ""}</span>
      </button>
      {/* The notes page link stays visible: it is what a student opens to study. */}
      {s.page !== null && (
        <div className="km-notes">
          {s.material_url ? (
            <Ext href={s.material_url}>讲义 第 {s.page} 页</Ext>
          ) : (
            <span>讲义 第 {s.page} 页</span>
          )}
        </div>
      )}
      {open && (
        <div className="km-detail" data-testid="km-detail">
          {s.title_zh && <p className="km-en">{s.title}</p>}
          {concepts.length > 0 && (
            <ul className="km-concepts">
              {concepts.map((c) => (
                <li key={c.key}>
                  {c.title_zh || c.title}
                  {c.page !== null && <span className="muted"> · 第 {c.page} 页</span>}
                </li>
              ))}
            </ul>
          )}
          {s.prereq.length > 0 && (
            <p>
              <span className="km-label">要先会</span>
              {s.prereq.map((p) => byKey.get(p)?.title_zh || byKey.get(p)?.title || p).join("、")}
              <span className="muted">（{s.prereq_origin === "ai" ? "AI 补充" : "老师"}）</span>
            </p>
          )}
          {(s.resources.length > 0 || s.assessments.length > 0) && (
            <ul className="km-links">
              {s.resources.map((r) => (
                <li key={r.url + r.title}>
                  <Ext href={r.url}>{r.title}</Ext>
                </li>
              ))}
              {s.assessments.map((a) => (
                <li key={a.url + a.title}>
                  <Ext href={a.url}>{a.title}</Ext>
                  <span className="km-score">{a.percent !== null ? `${a.percent}%` : "未出分"}</span>
                </li>
              ))}
            </ul>
          )}
          <label className="km-set">
            <span className="km-label">我的掌握情况</span>
            <select
              value={m?.source === "user" ? m.state : ""}
              onChange={(e) => onMastery(s.key, e.target.value as MasteryState | "")}
            >
              <option value="">自动判断{m && m.source !== "user" && m.note ? `（${m.note}）` : ""}</option>
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

function ExamRow({ e, onOpen }: { e: MapExam; onOpen: () => void }) {
  const done = e.days_left !== null && e.days_left < 0;
  const soon = !done && e.days_left !== null && e.days_left <= 7;
  return (
    <li data-testid="exam-card">
      <button
        type="button"
        className={`exam-row${done ? " past" : ""}`}
        aria-label={`打开复习地图：${e.name}`}
        onClick={onOpen}
      >
        <span className="exam-name">{e.name}</span>
        <span className="exam-when">{when(e.at)}</span>
        <span className={soon ? "exam-left soon" : "exam-left"}>
          {done && e.grade?.percent != null ? `${e.grade.percent}%` : countdown(e.days_left)}
        </span>
        <span className="exam-go" aria-hidden="true">
          复习地图 →
        </span>
      </button>
    </li>
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
  const first = showAll ? exam.suggested : exam.suggested.slice(0, SUGGESTED_SHOWN);
  return (
    <div className="exam-map" data-testid="exam-map">
      <button type="button" className="g-more" onClick={onBack}>
        ← {shortCode(map.course_code)}
      </button>
      <div className="exam-head">
        <h2>{e.name}</h2>
        <p>
          {[when(e.at), countdown(e.days_left), `${exam.sections.length} 节`].filter(Boolean).join(" · ")}
        </p>
        {e.resources.length > 0 && (
          <p className="exam-res">
            {e.resources.map((r) => (
              <Ext key={r.url + r.title} href={r.url}>
                {r.title}
              </Ext>
            ))}
          </p>
        )}
      </div>

      <h3 className="km-group">先复习这些</h3>
      {exam.suggested.length === 0 ? (
        <p className="muted">范围内每一节的练习都很好。考前做一遍复习题，再看下面的清单。</p>
      ) : (
        <ol className="exam-first">
          {first.map((k) => (
            <li key={k}>
              <span className="km-key">{k}</span>
              <span>{byKey.get(k)?.title_zh || byKey.get(k)?.title}</span>
              <span className="exam-why">{exam.why[k]}</span>
            </li>
          ))}
        </ol>
      )}
      {exam.suggested.length > SUGGESTED_SHOWN && (
        <button type="button" className="g-more" onClick={() => setShowAll((v) => !v)}>
          {showAll ? "只看前几项" : `展开全部 ${exam.suggested.length} 项`}
        </button>
      )}

      {exam.checklist.length > 0 && (
        <>
          <h3 className="km-group">考前清单</h3>
          <ul className="exam-check">
            {exam.checklist.map((c, i) => (
              <li key={`${i}-${c.text.slice(0, 12)}`} title={c.source ? `原文：${c.source}` : undefined}>
                {c.text}
              </li>
            ))}
          </ul>
          {exam.checklist.some((c) => c.source) && (
            <details className="exam-src">
              <summary>老师原文</summary>
              <ul>
                {exam.checklist
                  .filter((c) => c.source)
                  .map((c, i) => (
                    <li key={`${i}-${c.source.slice(0, 12)}`}>{c.source}</li>
                  ))}
              </ul>
            </details>
          )}
        </>
      )}

      <h3 className="km-group">考试范围</h3>
      <ul className="km-list">
        {exam.sections.map((s) => (
          <SectionRow key={s.key} s={s} concepts={concepts(s.key)} byKey={byKey} onMastery={onMastery} />
        ))}
      </ul>

      {exam.prerequisites.length > 0 && (
        <>
          <h3 className="km-group">范围外，但要先会</h3>
          <ul className="km-list" data-testid="exam-prereqs">
            {exam.prerequisites.map((s) => (
              <SectionRow key={s.key} s={s} concepts={[]} byKey={byKey} onMastery={onMastery} />
            ))}
          </ul>
        </>
      )}
      {e.scope_source && (
        <p className="km-foot">范围来源：{SOURCE_ZH[e.scope_source] ?? e.scope_source}</p>
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

  const loadCodes = useCallback(async () => {
    try {
      const cs = await api.courseMaps();
      setCodes(cs);
      if (cs.length > 0) setCode((c) => c || cs[0]);
      setError(null);
    } catch (err) {
      fail(err);
    }
  }, [api]);
  useEffect(() => {
    void loadCodes();
  }, [loadCodes]);

  const latest = useRef("");
  const load = useCallback(async () => {
    if (!code) return;
    latest.current = code;
    try {
      const m = await api.courseMap(code);
      if (latest.current !== code) return; // the user switched course meanwhile
      setMap(m);
      setError(null);
    } catch (err) {
      if (latest.current === code) fail(err);
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

  const banner = error && (
    <p className="error" role="alert">
      {error}{" "}
      <button
        type="button"
        onClick={() => {
          setError(null);
          void (codes === null ? loadCodes() : load());
        }}
      >
        重试
      </button>
    </p>
  );
  if (codes === null) return banner || <p>加载中…</p>;
  if (codes.length === 0)
    return <p className="muted">还没有课程知识地图。整理好一门课的讲义后，这里会显示它的章节和考试复习地图。</p>;
  if (!map) return banner || <p>加载中…</p>;
  const byKey = new Map(map.concepts.map((c) => [c.key, c]));
  if (exam)
    return (
      <div className="course">
        {banner}
        <ExamView
          exam={exam}
          map={map}
          byKey={byKey}
          onBack={() => setExam(null)}
          onMastery={(k, s) => void mastery(k, s)}
        />
      </div>
    );

  const chapters = map.concepts.filter((c) => c.kind === "chapter");
  const sections = map.concepts.filter((c) => c.kind === "section");
  const chapterKeys = new Set(chapters.map((c) => c.key));
  const orphans = sections.filter((s) => !chapterKeys.has(s.parent));
  const counts = MASTERY_ORDER.map((st) => [st, sections.filter((s) => s.mastery?.state === st).length] as const)
    .filter(([, n]) => n > 0)
    .map(([st, n]) => `${MASTERY[st]} ${n}`);
  const groups: [string, string, MapConcept[]][] = [
    ...chapters.map((ch): [string, string, MapConcept[]] => [
      ch.key,
      ch.title_zh || ch.title,
      sections.filter((s) => s.parent === ch.key),
    ]),
    ...(orphans.length > 0 ? [["", "其他", orphans] as [string, string, MapConcept[]]] : []),
  ];
  return (
    <div className="course" data-testid="course">
      {banner}
      {codes.length > 1 && (
        <div className="seg" role="group" aria-label="课程">
          {codes.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={c === code}
              className={c === code ? "active" : ""}
              onClick={() => {
                setExam(null);
                setCode(c);
              }}
            >
              {shortCode(c)}
            </button>
          ))}
        </div>
      )}
      <p className="course-sum">
        {sections.length} 节{counts.length > 0 && ` · ${counts.join(" · ")}`}
      </p>
      {map.exams.length > 0 && (
        <>
          <h3 className="km-group">考试</h3>
          <ul className="exam-list">
            {map.exams.map((e) => (
              <ExamRow key={e.name} e={e} onOpen={() => void openExam(e.name)} />
            ))}
          </ul>
        </>
      )}
      {groups.map(([key, title, list]) => (
        <section key={key || "other"} className="km-chapter" data-testid="km-chapter">
          <h3 className="km-group">{title}</h3>
          <ul className="km-list">
            {list.map((s) => (
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
      <details className="km-foot">
        <summary>这些内容从哪来</summary>
        <p>
          章节、知识点和页码来自老师的讲义和 Canvas；“要先会”标着来源（AI 补充或老师）。掌握情况按你的小测和作业成绩推断，点开一节可以自己改。
          {map.note && ` ${map.note}`}
        </p>
      </details>
    </div>
  );
}
