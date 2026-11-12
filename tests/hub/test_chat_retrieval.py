# ruff: noqa: RUF001  (full-width text is the point of these tests)
from datetime import UTC, date, datetime, timedelta

from apps.hub.chat.retrieval import Candidate, select, tokens
from packages.contracts.summaries import EmailSummary, Importance, SummaryStatus

TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 17, 0, tzinfo=UTC)


def summary(
    gist: str, deadline: date | None = None, points: list[str] | None = None
) -> EmailSummary:
    return EmailSummary(
        id="s",
        item_id="i",
        status=SummaryStatus.ok,
        gist=gist,
        points=points or [],
        action_needed=False,
        action="",
        deadline_text="",
        deadline_date=deadline,
        importance=Importance.normal,
        model="fake",
        prompt_version=3,
        error="",
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def cand(
    i: int, gist: str, hours_ago: float, deadline: date | None = None, subject: str = ""
) -> Candidate:
    return Candidate(
        item_id=f"id{i}",
        received=NOW - timedelta(hours=hours_ago),
        sender="Someone <a@b.c>",
        subject=subject or f"subject {i}",
        summary=summary(gist, deadline),
    )


def ids(chosen: list[Candidate]) -> list[str]:
    return [c.item_id for c in chosen]


def test_tokens_are_ascii_words_and_cjk_pairs() -> None:
    assert tokens("这周有哪些作业要交") == {
        "这周",
        "周有",
        "有哪",
        "哪些",
        "些作",
        "作业",
        "业要",
        "要交",
    }
    assert tokens("CIS22A Lab 5，交") == {"cis22a", "lab"}  # a lone CJK char is ignored
    assert tokens("ＣＩＳ") == {"cis"}  # full-width letters are normalised


def test_a_keyword_match_is_found_beyond_the_newest() -> None:
    pool = [cand(i, f"普通通知 {i}", hours_ago=i) for i in range(100)]
    pool.append(cand(999, "图书馆还书提醒", hours_ago=500))
    chosen = select("图书馆什么时候还书", "", pool, TODAY, recent=5, upcoming=0, cap=10)
    assert "id999" in ids(chosen)


def test_the_newest_are_always_included_and_the_cap_holds() -> None:
    pool = [cand(i, f"图书馆 {i}", hours_ago=i) for i in range(200)]
    chosen = select("图书馆", "", pool, TODAY, recent=20, cap=60)
    assert len(chosen) == 60
    assert {f"id{i}" for i in range(20)} <= set(ids(chosen))
    received = [c.received for c in chosen if c.received is not None]
    assert received == sorted(received, reverse=True)  # newest first


def test_a_deadline_soon_is_included_without_a_keyword() -> None:
    pool = [cand(i, f"无关 {i}", hours_ago=i) for i in range(50)]
    pool.append(cand(77, "实验报告", hours_ago=900, deadline=TODAY + timedelta(days=3)))
    pool.append(cand(78, "很久以后", hours_ago=900, deadline=TODAY + timedelta(days=40)))
    chosen = select("这周有什么要交", "", pool, TODAY, recent=5, upcoming=10, cap=20)
    assert "id77" in ids(chosen) and "id78" not in ids(chosen)


def test_common_words_count_less_than_rare_ones() -> None:
    pool = [cand(i, f"邮件通知 {i}", hours_ago=i) for i in range(30)]
    pool.append(cand(50, "邮件通知 助学金", hours_ago=800))
    pool.append(cand(51, "邮件通知", hours_ago=801))
    chosen = select("助学金邮件", "", pool, TODAY, recent=0, upcoming=0, cap=1)
    assert ids(chosen) == ["id50"]


def test_the_previous_question_still_helps_a_follow_up() -> None:
    pool = [cand(i, f"无关 {i}", hours_ago=i) for i in range(30)]
    pool.append(cand(60, "助学金材料", hours_ago=900))
    chosen = select("那什么时候截止", "助学金要交什么", pool, TODAY, recent=0, upcoming=0, cap=3)
    assert "id60" in ids(chosen)


def test_no_pool_means_nothing() -> None:
    assert select("任何问题", "", [], TODAY) == []
