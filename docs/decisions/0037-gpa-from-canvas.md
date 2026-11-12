# 0037: GPA management from Canvas

Status: accepted (2026-11-12). The user: build a GPA system around this term's 4 courses,
covering scores, assignment completion, all course materials, and everything that bears
on the GPA ("所有关乎到我的gpa的东西都要系统性的规整好，能够协助我管理gpa"); this summary is
built by the assistant; a live AI-over-API summary may come later.

## Findings (read-only spike on the user's Canvas)
- Every course exposes Canvas's computed current score and letter. Its "final" score
  counts ungraded work as 0, so it is far lower and must not be shown as the grade.
- ECON and MATH weight their assignment groups (ECON 25/25/25/25; MATH
  5/5/20/20/20/30). CIS and ENGL count total points.
- Modules list the course materials. Files are hidden from students in 3 of 5 courses,
  while modules are visible in all of them.

## Decision
- **Sync (T-0040).** The Canvas connector stores courses (score, letter, weights, groups),
  assignments (group, score, letter, graded time, missing, late, excused) and module
  materials (names and links) as synced items. No new tables; nothing is downloaded.
- **GPA module (T-0041).** Built from those items. For each course it shows: the current
  score and letter; per-group earned/possible and weight; completion (submitted, missing,
  late); upcoming work by weight; recent grades; materials by module; and what the
  remaining weight needs for each grade line. Grade lines and units are estimates until
  the user confirms them.
- **Later:** downloading materials (needs the user's go-ahead, and disk space on D),
  grade history over time, and assistant tools over grades.
