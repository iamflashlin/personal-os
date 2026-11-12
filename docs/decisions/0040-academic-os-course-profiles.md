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
  - **Percent so far** with own categories: each category's average (missing work as 0)
    times its weight, over the categories with graded or missing work. That is what a
    syllabus's "zyBooks 30%" means, and Canvas computes it the same way.
  - **Grade lines**: the average the open work needs for the whole-course total to reach
    a letter. The lines shown are around the current letter (two above, one below).
  - Category patterns match the whole title with `#` (a number) and `*` (anything), e.g.
    `ZB#` and `ZB# Lab`. They are never user regular expressions, so a pattern cannot
    freeze the Hub.
  - Every scale goes down to 0, so a failing course gets F and never drops out of the GPA.
  - Missing work counts as 0 in both the shown percent and the grade lines, so the two
    agree. When Canvas's current score leaves missing work out, the page says so.
  - A missing item is treated as a copy of handed-in work when it has the same title and
    sits in another Canvas group (combined classes import work there, sometimes with other
    points), or has the same points and due time in the same group. It is left out and
    named on the page. A weekly title with its own due date stays missing.
  - Disagreements (Canvas's letter versus the syllabus's letter) are shown, not resolved.
- **Profiles come from an import.** `scripts/academic/import_profiles.py` reads a JSON file
  kept outside the repo. The assistant wrote this term's file by reading the syllabi on
  the PC (the assistant is a cloud model; the Hub itself calls no AI API). Nothing was sent to DeepSeek.
- **Units come from the web when the syllabus has none.** MATH 1A is 5 units according to
  2026 De Anza MATH 1A syllabi. ENGL C1000 is 5 units according to a De Anza instructor
  page. Each profile says which source it used.

## Next
- Course knowledge map (concepts, sources with pages, prerequisites, assessment links).
- Exam center.
- Mastery states.
- The redesigned UI.
