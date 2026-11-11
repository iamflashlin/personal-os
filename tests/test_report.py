# ruff: noqa: RUF001  (asserts on user-facing Chinese text with full-width punctuation)
from datetime import date
from pathlib import Path

import pytest

from tools import report as report_module
from tools.report import (
    Card,
    Problem,
    Source,
    build_report,
    load_cards,
    main,
    parse_card,
    parse_git_log,
    render,
    week_bounds,
)

TODAY = date(2026, 11, 17)


def card_text(card_id: str, status: str = "todo", deps: str = "[]", title: str = "Title") -> str:
    return (
        f"---\nid: {card_id}\ntitle: {title}\nstatus: {status}            # a comment\n"
        f"depends_on: {deps}\n---\n## Goal\n"
    )


def ok(text: str) -> Card:
    parsed = parse_card(text, f"docs/tasks/{text.split()[2]}.md")
    assert isinstance(parsed, Card), parsed
    return parsed


FIXTURE_LOG = "\n".join(
    [
        "c8\x1f2026-11-18\x1fdocs(tasks): plan T-0004 card, unblocks T-0003 (#12)",
        "c7\x1f2026-11-18\x1ffix(hub): crash on empty list (T-0005) (#11)",
        "c6\x1f2026-11-17\x1ffix(hub): repair export (T-0003) (#10)",
        "c5\x1f2026-11-17\x1fdocs(tasks): plan T-0004 card",
        "c4\x1f2026-11-16\x1ffeat(hub): export and import (T-0003) (#9)",
        "c3\x1f2026-11-10\x1ffeat(hub): hub skeleton (T-0001) (#2)",
        "c2\x1f2026-11-09\x1fchore: bootstrap (D0-01, D0-03) (#1)",
        "garbage line without separators",
    ]
)


def source(log: str = FIXTURE_LOG, paths: frozenset[str] = frozenset()) -> Source:
    return Source("origin/main", "abc1234", parse_git_log(log), paths)


def test_cards_are_grouped_by_status() -> None:
    cards = [
        ok(card_text("T-0001", "done")),
        ok(card_text("T-0002", "in_progress")),
        ok(card_text("T-0003", "blocked")),
        ok(card_text("T-0004", "todo", "[T-0001]")),
    ]
    text = render(
        build_report(TODAY, cards, [], source("c1\x1f2026-11-10\x1ffeat: x (T-0001) (#2)"))
    )
    assert "已完成 1，进行中 1，待审核 0，卡住 1，未开始 1" in text
    assert "### 进行中\n\n- **T-0002**" in text
    assert "### 卡住了\n\n- **T-0003**" in text
    assert "可以马上开始的卡：\n\n- **T-0004**" in text


def test_comments_are_stripped_but_hash_inside_titles_is_kept() -> None:
    parsed = ok(card_text("T-0001", "review", title="Fix crash on #12 in C# client"))
    assert parsed.status == "review"
    assert parsed.title == "Fix crash on #12 in C# client"


def test_bom_and_padded_fences_are_accepted() -> None:
    text = "﻿--- \nid: T-0009\ntitle: t\nstatus: todo\n---  \n"
    assert ok(text).id == "T-0009"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("## no frontmatter\n", "缺少用 --- 包起来的信息块"),
        ("---\nid: T-1\ntitle: t\nstatus: todo\n", "没有用 --- 结束"),
        ("---\nid: T-1\nstatus: todo\n---\n", "信息块里缺少：title"),
        ("---\nid: T-1\ntitle: t\nstatus: finished\n---\n", "第 4 行状态写成了 finished"),
    ],
)
def test_malformed_card_is_reported_not_raised(text: str, message: str) -> None:
    parsed = parse_card(text, "docs/tasks/bad.md")
    assert isinstance(parsed, Problem)
    assert message in parsed.message


def test_malformed_card_appears_in_report_alongside_good_ones(tmp_path: Path) -> None:
    (tmp_path / "T-0001.md").write_text(card_text("T-0001"), encoding="utf-8")
    (tmp_path / "broken.md").write_text("no frontmatter here", encoding="utf-8")
    cards, problems = load_cards(tmp_path)
    assert [c.id for c in cards] == ["T-0001"]
    text = render(build_report(TODAY, cards, problems, source("")))
    assert "broken.md`：文件开头缺少用 --- 包起来的信息块" in text


def test_only_pr_merges_count_and_lagging_cards_are_flagged() -> None:
    commits = parse_git_log(FIXTURE_LOG)
    assert [c.sha for c in commits] == ["c8", "c7", "c6", "c5", "c4", "c3", "c2"]
    assert commits[6].card_ids == ("D0-01", "D0-03")
    assert commits[0].card_ids == ()

    cards = [ok(card_text(i)) for i in ("T-0001", "T-0003", "T-0004", "D0-01")]
    text = render(build_report(TODAY, cards, [], source()))
    assert "已完成 3" in text
    assert "**T-0004**" in text.split("## 下一步")[1].split("## 本周")[0]
    assert "已经合并进 main，但第 4 行还写着 status: todo" in text


def test_rework_needs_an_earlier_merge_of_the_same_card() -> None:
    cards = [ok(card_text(i, "done")) for i in ("T-0003", "T-0005")]
    report = build_report(TODAY, cards, [], source())
    assert [c.sha for c in report.rework] == ["c6"]
    rework = render(report).split("## 返工", 1)[1].split("##", 1)[0]
    assert "repair export (T-0003)" in rework
    assert "T-0005" not in rework


def test_done_card_without_a_merge_is_not_counted() -> None:
    text = render(build_report(TODAY, [ok(card_text("T-0042", "done"))], [], source()))
    assert "已完成 0" in text
    assert "卡片写着 done，但 main 上找不到对应的合并" in text


def test_duplicate_ids_and_unknown_dependencies_are_flagged() -> None:
    cards = [ok(card_text("T-0001")), ok(card_text("T-0001", deps="[T-0999]"))]
    text = render(build_report(TODAY, cards, [], source("")))
    assert "编号 T-0001 和 docs/tasks/T-0001.md 重复" in text
    assert "依赖的 T-0999 没有对应的任务卡" in text


def test_this_week_comes_from_today_not_the_clock() -> None:
    cards = [ok(card_text(i)) for i in ("D0-01", "D0-03", "T-0001", "T-0003", "T-0005")]
    this_week = render(build_report(TODAY, cards, [], source()))
    assert "本周合并（2026-11-16 至 2026-11-22）" in this_week
    assert "本周合并了 2 张任务卡：T-0003, T-0005。" in this_week
    assert "docs(tasks): plan T-0004 card\n" not in this_week
    assert "plan T-0004 card, unblocks T-0003 (#12)" in this_week

    week_before = render(build_report(date(2026, 11, 10), cards, [], source()))
    assert "本周合并（2026-11-09 至 2026-11-15）" in week_before
    assert "本周合并了 3 张任务卡：D0-01, D0-03, T-0001。" in week_before


def test_week_bounds_are_monday_to_sunday() -> None:
    assert week_bounds(date(2026, 11, 22)) == (date(2026, 11, 16), date(2026, 11, 22))
    assert week_bounds(date(2026, 11, 16)) == (date(2026, 11, 16), date(2026, 11, 22))


def test_showcases_follow_the_measured_ref_and_the_source_is_named() -> None:
    without = render(build_report(TODAY, [], [], source()))
    assert "统计依据：origin/main @ abc1234" in without
    assert "main 上还没有可以打开的界面" in without

    with_hub = render(build_report(TODAY, [], [], source(paths=frozenset({"apps/hub/main.py"}))))
    assert "1. `uv run python -m apps.hub`\n2. 浏览器打开 http://127.0.0.1:8765/docs" in with_hub
    assert "网页界面" not in with_hub

    both = frozenset({"apps/hub/main.py", "apps/web/package.json"})
    with_web = render(build_report(TODAY, [], [], source(paths=both)))
    assert (
        "1. `pnpm --dir apps/web build`\n2. `uv run python -m apps.hub`\n"
        "3. 浏览器打开 http://127.0.0.1:8765/"
    ) in with_web


def test_same_inputs_give_byte_identical_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "T-0001.md").write_text(card_text("T-0001"), encoding="utf-8")
    monkeypatch.setattr(report_module, "read_source", lambda _ref: source())

    first, second = tmp_path / "a.md", tmp_path / "b.md"
    argv = ["--today", "2026-11-17", "--tasks-dir", str(tasks), "--out"]
    assert main([*argv, str(first)]) == 0
    assert main([*argv, str(second)]) == 0
    assert first.read_bytes() == second.read_bytes()


def test_missing_ref_gives_a_plain_message_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "x.md"
    code = main(["--today", "2026-11-17", "--ref", "no-such-branch-xyz", "--out", str(out)])
    assert code == 2
    assert "找不到 no-such-branch-xyz" in capsys.readouterr().err
    assert not out.exists()
