# 0041: Academic OS, step 2 - the course knowledge map, mastery and exam maps

Status: accepted (2026-11-12). This step follows the user's Academic OS framework: course
knowledge + learning + grades + GPA decisions, connected through the course structure.
The first course is MATH 1A, as the framework recommends. Its notes, syllabus and exam
reviews are all on Canvas.

## Decision
- **Two tables in `apps/hub/academic`** (migration 0017):
  - `course_map` holds one row per course: the teaching structure (chapters, sections,
    concepts), the main material's file name, the exams, and the exam checklist. An import
    replaces it as a whole.
  - `concept_mastery` holds the user's own state per concept or section.
  - They are kept apart on purpose. Course knowledge is objective; mastery is personal.
    Replacing the map never touches mastery.
- **Every item says where it comes from.**
  - Sections keep the teacher's numbering, titles, order and the page in the notes. The
    page links to the synced Canvas file.
  - Concepts are the notes' own definitions, rules and theorems (`origin: teacher`).
  - Prerequisites are inferred by the assistant (`prereq_origin: ai`), and the page says so.
- **Assessments are linked by what their Canvas titles say.**
  - "Quiz #4 (3.2 to 3.4)" and "Sections 3.5 to 3.11, and 4.1" are expanded in teaching
    order. Nothing is guessed from content.
  - Exams are matched by their own title pattern (as in ADR 0040, at most three wildcards).
    The pattern is required, so an exam is shown on the exam and never counted as practice.
  - A course that does not number its work (ECON: "Homework - Monetary Policy") gives each
    section whole-title patterns instead (`match`, T-0053). They follow the same rules as
    grade-category patterns and link assignments and module items alike.
  - A range covers every section of the map that falls inside it by number ("3.8 to 3.10"
    covers 3.9 and 3.10 when 3.8 is not taught). Exam resources match the exam's name as a
    whole word ("Exam 1" never matches "Exam 10").
- **Mastery is evidence-based and honest.**
  - The user's own setting wins.
  - Otherwise it is inferred from linked graded work: an average of 90% or more over at
    least two items is verified (one good quiz is a good sign, not proof), 70% or more is
    practicing, lower needs review. The basis is shown ("根据 2 项
    已评分的练习推断，平均 84%").
  - With no graded work it is "not tested". There is no false precision.
- **Exam maps.**
  - The map is cut to the exam's scope, with chapters expanded.
  - Prerequisites outside the scope are listed.
  - A suggested order puts the weakest first (needs review, then not tested, then
    practicing), each with its reason.
  - The exam's own grade is shown once it is posted, with the course's exam checklist
    ("show your work", "box the answer", "no calculator").
- **The Hub calls no AI API.** The assistant (Claude, a cloud model working on this PC at the
  user's request) read the teacher's notes and exam reviews and wrote the MATH 1A map. It was
  imported with `scripts/academic/import_map.py`. The file is kept in `D:\dev-cache`, outside
  the repo. Nothing was sent to DeepSeek.
- **Imports replace the map, and the last write wins** (there is no version check). That is
  fine for an import; the user's mastery is never part of it.

## Not yet
- The web pages: 课程 (the map), 考试中心 (exam maps).
- Practice generation and error analysis by question. These need the user's graded papers;
  the system asks for them and never invents causes.
- Maps for ENGL (ECON is imported; the user does not want maps for MATH beyond this one
  or for CIS: they know that material. Their homework and GPA stay).
