# ruff: noqa: RUF001  (user-facing Chinese text uses full-width punctuation on purpose)
"""Generate docs/progress.md from task cards and the merge history of main.

    uv run python -m tools.report --today 2026-11-17

Progress is measured by verified merges, not activity: a card counts as done when a
squash-merged PR on the measured ref (a first-parent commit whose subject ends in
"(#N)") names its id, or when a merge-commit PR ("Merge pull request #N ...") brings in
a commit whose subject ends in "(<card ids>)".

A hand-written 「今天」 block between TODAY_START and TODAY_END in the existing output
file is carried over unchanged, at the top. All git reads happen in `read_source`;
`render` is a pure function of the cards, that source, `--today` and that block, so the
same inputs give byte-identical output.
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "docs" / "tasks"
OUT = ROOT / "docs" / "progress.md"

STATUSES = ("todo", "in_progress", "review", "done", "blocked")
CARD_ID = re.compile(r"\b([A-Z][A-Z0-9]?-\d{2,4})\b")
PR_MERGE = re.compile(r"\(#\d+\)\s*$")
GITHUB_MERGE = re.compile(r"^Merge pull request #\d+ ")
# Branch commits brought in by a merge-commit PR: ids in a "(...)" that ends the subject.
# Looser than the squash rule, but such a commit really did reach the measured ref.
TRAILING_CARDS = re.compile(r"\(([^()]*)\)\s*$")
MERGED_CARDS = re.compile(r"\(([^()]*)\)\s*\(#\d+\)\s*$")
FIX_SUBJECT = re.compile(r"^fix(\([^)]*\))?!?:")
YAML_COMMENT = re.compile(r"\s+#(?:\s|$)")
TODAY_START = "<!-- today:start -->"
TODAY_END = "<!-- today:end -->"
TODAY_PLACEHOLDER = f"{TODAY_START}\n## 今天\n\n- （今天还没写）\n{TODAY_END}"


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    status: str
    depends_on: tuple[str, ...]
    path: str
    status_line: int


@dataclass(frozen=True)
class Problem:
    path: str
    message: str


@dataclass(frozen=True)
class Commit:
    sha: str
    day: date
    subject: str
    merged_in: tuple[str, ...] = ()  # cards brought in by a "Merge pull request" commit

    @property
    def card_ids(self) -> tuple[str, ...]:
        """Cards this merge delivers: those in the "(...)" just before "(#N)", or, for a
        merge-commit PR, those named by the commits it brought in."""
        if GITHUB_MERGE.match(self.subject):
            return self.merged_in
        match = MERGED_CARDS.search(self.subject)
        return tuple(dict.fromkeys(CARD_ID.findall(match.group(1)))) if match else ()

    @property
    def is_pr_merge(self) -> bool:
        return (
            PR_MERGE.search(self.subject) is not None
            or GITHUB_MERGE.match(self.subject) is not None
        )


@dataclass(frozen=True)
class Showcase:
    """Something the user can open and look at, shown once `requires` is on the ref."""

    requires: str
    what: str
    commands: tuple[str, ...]
    url: str


SHOWCASES = (
    Showcase(
        "apps/hub/main.py",
        "Hub 的接口文档页：能看到并试用所有接口",
        ("uv run python -m apps.hub",),
        "http://127.0.0.1:8765/docs",
    ),
    Showcase(
        "apps/web/package.json",
        "网页界面：看目标、项目、任务，新建和确认完成任务；在“记忆”页搜索和管理记忆",
        ("pnpm --dir apps/web build", "uv run python -m apps.hub"),
        "http://127.0.0.1:8765/",
    ),
)


@dataclass(frozen=True)
class Source:
    """The measured branch: its name, tip commit, history, and which showcases it has."""

    ref: str
    sha: str
    commits: tuple[Commit, ...]
    existing_paths: frozenset[str]


class SourceError(Exception):
    pass


@dataclass
class Report:
    today: date
    cards: list[Card]
    problems: list[Problem]
    source: Source
    merged_ids: set[str] = field(default_factory=set[str])
    rework: list[Commit] = field(default_factory=list[Commit])

    def is_done(self, card: Card) -> bool:
        return card.id in self.merged_ids

    def effective_status(self, card: Card) -> str:
        if self.is_done(card):
            return "done"
        return "todo" if card.status == "done" else card.status


def parse_card(text: str, path: str) -> Card | Problem:
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return Problem(path, "文件开头缺少用 --- 包起来的信息块（id、title、status 等）")
    end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() == "---"), None)
    if end is None:
        return Problem(path, "开头的信息块没有用 --- 结束")
    fields: dict[str, str] = {}
    lines_of: dict[str, int] = {}
    for number, line in enumerate(lines[1:end], 2):
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = YAML_COMMENT.split(value, maxsplit=1)[0].strip()
            lines_of[key.strip()] = number
    missing = [k for k in ("id", "title", "status") if not fields.get(k)]
    if missing:
        return Problem(path, f"信息块里缺少：{', '.join(missing)}")
    if fields["status"] not in STATUSES:
        return Problem(
            path,
            f"第 {lines_of['status']} 行状态写成了 {fields['status']}，"
            f"只能是 {' / '.join(STATUSES)} 之一",
        )
    raw_deps = fields.get("depends_on", "").strip("[]").split(",")
    deps = tuple(d.strip() for d in raw_deps if d.strip())
    return Card(fields["id"], fields["title"], fields["status"], deps, path, lines_of["status"])


def load_cards(tasks_dir: Path) -> tuple[list[Card], list[Problem]]:
    cards: list[Card] = []
    problems: list[Problem] = []
    for path in sorted(tasks_dir.glob("*.md")):
        rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.name
        parsed = parse_card(path.read_text(encoding="utf-8-sig"), rel)
        if isinstance(parsed, Card):
            cards.append(parsed)
        else:
            problems.append(parsed)
    return cards, problems


def branch_card_ids(subjects: list[str]) -> tuple[str, ...]:
    """Card ids at the end of branch commit subjects: "feat(hub): x (T-0005)", or
    "feat(hub): x (T-0019) (#25)" for a PR squash-merged into a stacked branch."""
    ids: list[str] = []
    for subject in subjects:
        match = MERGED_CARDS.search(subject) or TRAILING_CARDS.search(subject)
        if match:
            ids += CARD_ID.findall(match.group(1))
    return tuple(dict.fromkeys(ids))


def parse_git_log(text: str) -> tuple[Commit, ...]:
    """Parse `git log --format=%H%x1f%cs%x1f%s` output (newest first)."""
    commits: list[Commit] = []
    for line in text.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            commits.append(Commit(parts[0], date.fromisoformat(parts[1]), parts[2]))
    return tuple(commits)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False
    )


def read_source(ref: str | None) -> Source:
    candidates = [ref] if ref else ["origin/main", "main"]
    for name in candidates:
        tip = _git("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
        if tip.returncode == 0:
            log = _git("log", "--first-parent", name, "--format=%H%x1f%cs%x1f%s")
            commits = tuple(_with_merged_in(c) for c in parse_git_log(log.stdout))
            existing = frozenset(
                s.requires
                for s in SHOWCASES
                if _git("cat-file", "-e", f"{name}:{s.requires}").returncode == 0
            )
            return Source(name, tip.stdout.strip()[:7], commits, existing)
    raise SourceError(
        f"找不到 {' 或 '.join(candidates)}。请先运行 git fetch（或用 --ref 指定分支）再生成报告。"
    )


def _with_merged_in(commit: Commit) -> Commit:
    """For a merge-commit PR, record the cards named by the commits it brought in."""
    if not GITHUB_MERGE.match(commit.subject):
        return commit
    merged = _git("log", "--format=%s", f"{commit.sha}^1..{commit.sha}^2")
    if merged.returncode != 0:
        return commit
    ids = branch_card_ids(merged.stdout.splitlines())
    return Commit(commit.sha, commit.day, commit.subject, ids)


def read_today_note(path: Path) -> str | None:
    """The hand-written 「今天」 block of an existing report, markers included.

    Raises SourceError when the markers are broken, so a note is never silently lost.
    """
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = text.find(TODAY_START)
    end = text.find(TODAY_END, start) if start >= 0 else -1
    if start < 0 and TODAY_END not in text:
        return None
    if start < 0 or end < 0:
        raise SourceError(
            f"{path} 里的「今天」标记不完整（需要 {TODAY_START} 在前、{TODAY_END} 在后）。"
            "为了不丢掉手写的内容，这次没有生成报告；请先修好标记。"
        )
    return text[start : end + len(TODAY_END)]


def week_bounds(today: date) -> tuple[date, date]:
    """Monday..Sunday of the ISO week that contains `today`."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=6)


def build_report(today: date, cards: list[Card], problems: list[Problem], source: Source) -> Report:
    report = Report(today, cards, list(problems), source)
    seen: set[str] = set()
    for commit in reversed([c for c in source.commits if c.is_pr_merge]):
        if FIX_SUBJECT.match(commit.subject) and any(i in seen for i in commit.card_ids):
            report.rework.append(commit)
        seen.update(commit.card_ids)
    report.rework.reverse()
    report.merged_ids = seen

    known = {c.id for c in cards}
    first_path: dict[str, str] = {}
    for card in cards:
        if card.id in first_path:
            report.problems.append(
                Problem(card.path, f"编号 {card.id} 和 {first_path[card.id]} 重复")
            )
        first_path.setdefault(card.id, card.path)
        for dep in card.depends_on:
            if dep not in known:
                report.problems.append(Problem(card.path, f"依赖的 {dep} 没有对应的任务卡"))
        merged = card.id in seen
        if merged and card.status != "done":
            report.problems.append(
                Problem(
                    card.path,
                    f"已经合并进 main，但第 {card.status_line} 行还写着 status: {card.status}"
                    "（打开这个文件，改成 status: done）",
                )
            )
        if not merged and card.status == "done":
            report.problems.append(
                Problem(card.path, "卡片写着 done，但 main 上找不到对应的合并，按未完成计算")
            )
    return report


def _card_line(card: Card) -> str:
    return f"- **{card.id}** {card.title}"


def render(report: Report, today_note: str | None = None) -> str:
    by_status: dict[str, list[Card]] = {s: [] for s in STATUSES}
    for card in sorted(report.cards, key=lambda c: (c.id, c.path)):
        by_status[report.effective_status(card)].append(card)
    done_ids = {c.id for c in by_status["done"]}
    ready = [c for c in by_status["todo"] if all(d in done_ids for d in c.depends_on)]
    waiting = [c for c in by_status["todo"] if c not in ready]

    source = report.source
    monday, sunday = week_bounds(report.today)
    this_week = [c for c in source.commits if c.is_pr_merge and monday <= c.day <= sunday]
    known = {c.id for c in report.cards}
    cards_this_week = sorted({i for c in this_week for i in c.card_ids if i in known})

    out: list[str] = [
        "# 进度报告",
        "",
        today_note or TODAY_PLACEHOLDER,
        "",
        f"> 由 `uv run python -m tools.report --today {report.today.isoformat()}` 生成，"
        "「今天」以外请不要手改。进度只按“合并进 main 的、验证过的改动”计算。",
        f"> 统计依据：{source.ref} @ {source.sha}"
        "（如果刚在 GitHub 上合并过 PR，先运行 `git fetch` 再生成）。",
        "",
        "## 现在做到哪",
        "",
        f"共 {len(report.cards)} 张任务卡：已完成 {len(by_status['done'])}，"
        f"进行中 {len(by_status['in_progress'])}，待审核 {len(by_status['review'])}，"
        f"卡住 {len(by_status['blocked'])}，未开始 {len(by_status['todo'])}。",
        "",
        "### 已完成",
        "",
        *([_card_line(c) for c in by_status["done"]] or ["- （还没有）"]),
        "",
    ]
    for status, heading in (("in_progress", "进行中"), ("review", "待审核"), ("blocked", "卡住了")):
        if by_status[status]:
            out += [f"### {heading}", "", *[_card_line(c) for c in by_status[status]], ""]

    out += [
        "## 下一步",
        "",
        "前置任务都已完成、可以马上开始的卡：",
        "",
        *([_card_line(c) for c in ready] or ["- （没有，先完成上面进行中的卡）"]),
        "",
    ]
    if waiting:
        out += ["还在等前置任务的卡：", ""]
        for card in waiting:
            pending = ", ".join(d for d in card.depends_on if d not in done_ids)
            out.append(f"{_card_line(card)}（等 {pending}）")
        out.append("")

    headline = (
        f"本周合并了 {len(cards_this_week)} 张任务卡：{', '.join(cards_this_week)}。"
        if cards_this_week
        else "本周还没有合并任务卡。"
    )
    out += [
        f"## 本周合并（{monday.isoformat()} 至 {sunday.isoformat()}）",
        "",
        headline,
        "",
        *[f"- {c.day.isoformat()} {c.subject}" for c in this_week],
        *([""] if this_week else []),
        "## 返工",
        "",
        "以 `fix:` 开头、修的是之前已经合并过的任务卡的提交：",
        "",
        *([f"- {c.day.isoformat()} {c.subject}" for c in report.rework] or ["- （没有）"]),
        "",
        "## 我能看到什么",
        "",
    ]
    visible = [s for s in SHOWCASES if s.requires in source.existing_paths]
    for show in visible:
        out += [f"**{show.what}**", ""]
        out += [f"{i}. `{cmd}`" for i, cmd in enumerate(show.commands, 1)]
        out += [f"{len(show.commands) + 1}. 浏览器打开 {show.url}", ""]
    if not visible:
        out += ["- （main 上还没有可以打开的界面）", ""]

    if report.problems:
        out += ["## 需要注意", ""]
        out += [
            f"- `{p.path}`：{p.message}"
            for p in sorted(report.problems, key=lambda p: (p.path, p.message))
        ]
        out.append("")
    return "\n".join(out)


def _utf8_console() -> None:
    """Windows pipes default to the ANSI code page, which turns Chinese into \\u escapes."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    parser.add_argument("--ref", help="branch to measure (default: origin/main, else main)")
    parser.add_argument("--tasks-dir", type=Path, default=TASKS_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)

    try:
        source = read_source(args.ref)
        note = read_today_note(args.out)
    except SourceError as exc:
        print(exc, file=sys.stderr)
        return 2
    cards, problems = load_cards(args.tasks_dir.resolve())
    text = render(build_report(args.today, cards, problems, source), note)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    summary = f"{len(cards)} cards, {len(problems)} malformed, {source.ref} @ {source.sha}"
    print(f"wrote {args.out}: {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
