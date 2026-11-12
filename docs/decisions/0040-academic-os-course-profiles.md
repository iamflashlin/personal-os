# 0040: Academic OS, step 1 - course profiles from the syllabus

Status: accepted (2026-11-12). The user asked for a full Academic OS. It has four connected
parts: course knowledge, learning execution, grade management, and GPA decisions. Their
framework is the reference for this and the next cards.

Reading all four syllabi showed that the grade page (T-0041) was wrong in ways Canvas
cannot show:
- each course has its own letter scale (ECON A ≥94, CIS A ≥92, MATH A ≥90 and A+ ≥97), and
  De Anza counts plus and minus (A- is 3.7);
- CIS's Canvas course has one unweighted group, while the syllabus weights it 30/20/25/25;
- rules that decide outcomes live only in the syllabus: no late work, a missed exam is
  replaced by the final's percent, a portfolio gate, no AI writing;
- missing copies of work in combined classes made a real A- look like a B-.

## Decision
- **The syllabus is the authority; Canvas is data.** A new module `apps/hub/academic`
  owns `course_profile` (migration 0016). It has one row per owner and course code, and
  holds:
  - units, with where they come from;
  - the letter scale;
  - optional own categories (name, weight, a title pattern that picks Canvas assignments);
  - rules, each with its syllabus words;
  - open questions (待确认);
  - the syllabus file name.
- **The user confirms each profile once.** A changed profile goes back to 待你确认.
- **The grade engine (gpa) follows the profile.**
  - It uses its own categories when the profile has them; otherwise it uses Canvas's
    score for the graded part.
  - The letter comes from the profile's scale and the points from De Anza's table.
  - The GPA is weighted by units once every course has them.
  - Missing work counts as 0 in both the shown percent and the grade lines, so the two
    agree. When Canvas's current score leaves missing work out, the page says so.
  - A missing item named like work that was already handed in is treated as a copy. It
    is left out and named on the page.
  - Disagreements (Canvas's letter versus the syllabus's letter) are shown, not resolved.
- **Profiles come from an import.** `scripts/academic/import_profiles.py` reads a JSON file
  kept outside the repo. The assistant wrote this term's file by reading the syllabi on
  the PC. Nothing was sent to an outside AI.
- **Units come from the web when the syllabus has none.** MATH 1A is 5 units according to
  2026 De Anza MATH 1A syllabi. ENGL C1000 is 5 units according to a De Anza instructor
  page. Each profile says which source it used.

## Next
- Course knowledge map (concepts, sources with pages, prerequisites, assessment links).
- Exam center.
- Mastery states.
- The redesigned UI.
