import importlib.metadata
import time
from datetime import UTC, datetime

import pytest

from apps.hub.integrations.ics import NotACalendar, parse

FEED = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Instructure//Canvas//EN\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:event-assignment-101\r\n"
    "SUMMARY:CIS 22A Lab 3\\, part 1 [CIS-22A]\r\n"
    "DESCRIPTION:Read chapter 4\\nthen submit the\r\n"
    "  lab on Canvas\r\n"
    "DTSTART:20261112T075900Z\r\n"
    "DTEND:20261112T075900Z\r\n"
    "URL:https://canvas.example.edu/courses/1/assignments/101\r\n"
    "BEGIN:VALARM\r\n"
    "SUMMARY:alarm text must not replace the event's\r\n"
    "END:VALARM\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:holiday-1\r\n"
    "SUMMARY:No class\r\n"
    "DTSTART;VALUE=DATE:20261126\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:office-hours\r\n"
    "SUMMARY:Office hours\r\n"
    "DTSTART;TZID=Mars/Olympus_Mons:20261113T150000\r\n"
    "RRULE:FREQ=WEEKLY\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "SUMMARY:no uid, skipped\r\n"
    "DTSTART:20261113T150000Z\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_a_canvas_style_feed_is_read() -> None:
    lab, holiday, office = parse(FEED)

    assert lab.uid == "event-assignment-101"
    assert lab.summary == "CIS 22A Lab 3, part 1 [CIS-22A]"
    assert lab.description == "Read chapter 4\nthen submit the lab on Canvas"
    assert lab.starts_at == datetime(2026, 11, 12, 7, 59, tzinfo=UTC)
    assert lab.url.endswith("/assignments/101")
    assert not lab.all_day and lab.flags == {}

    assert holiday.all_day
    assert holiday.starts_at == datetime(2026, 11, 26, tzinfo=UTC)

    assert office.starts_at is None
    assert office.flags["timezone_unresolved"] == "Mars/Olympus_Mons 20261113T150000"
    assert office.flags["recurrence_not_expanded"] == "FREQ=WEEKLY"


def test_lf_only_line_endings_also_work() -> None:
    (lab, *_) = parse(FEED.replace("\r\n", "\n"))
    assert lab.description.endswith("lab on Canvas")


@pytest.mark.parametrize("text", ["", "<html>login</html>", "BEGIN:VCARD\nEND:VCARD"])
def test_anything_but_a_calendar_is_refused(text: str) -> None:
    with pytest.raises(NotACalendar):
        parse(text)


def test_a_bad_time_is_flagged_and_the_rest_of_the_feed_still_reads() -> None:
    feed = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:bad\r\nDTSTART:20261110T100000.5Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:dashes\r\nDTSTART;VALUE=DATE:2026-11-26\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:short\r\nDTSTART:20261110T1000Z\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:good\r\nDTSTART:20261110T100000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    bad, dashes, short, good = parse(feed)
    assert bad.starts_at is None and bad.flags["bad_time"] == "20261110T100000.5Z"
    assert dashes.starts_at is None and "bad_time" in dashes.flags
    assert short.starts_at is None and "bad_time" in short.flags
    assert good.starts_at == datetime(2026, 11, 10, 10, tzinfo=UTC)


def test_the_first_unresolved_zone_is_kept() -> None:
    feed = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:x\r\n"
        "DTSTART;TZID=Mars/Olympus_Mons:20261113T150000\r\n"
        "DTEND;TZID=Mars/Olympus_Mons:20261113T160000\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    (only,) = parse(feed)
    assert only.flags["timezone_unresolved"].endswith("T150000")


def test_a_byte_order_mark_is_ignored() -> None:
    assert len(parse("\ufeff" + FEED)) == 3


def test_a_feed_of_continuation_lines_reads_in_linear_time() -> None:
    hostile = "BEGIN:VCALENDAR\r\nX-JUNK:a\r\n" + " b\r\n" * 1_500_000 + "END:VCALENDAR\r\n"
    started = time.monotonic()
    assert parse(hostile) == []
    assert time.monotonic() - started < 5


def test_a_named_time_zone_gives_the_exact_utc_time_across_daylight_saving() -> None:
    feed = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\nUID:winter\r\n"
        "DTSTART;TZID=America/Los_Angeles:20261113T150000\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:summer\r\n"
        "DTSTART;TZID=America/Los_Angeles:20260715T150000\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    winter, summer = parse(feed)
    assert winter.starts_at == datetime(2026, 11, 13, 23, 0, tzinfo=UTC)  # PST, UTC-8
    assert summer.starts_at == datetime(2026, 7, 15, 22, 0, tzinfo=UTC)  # PDT, UTC-7
    assert winter.flags == {} and summer.flags == {}


def test_tzdata_is_installed_so_windows_can_resolve_zones() -> None:
    # On Linux zoneinfo would fall back to /usr/share/zoneinfo; this keeps the dependency
    # honest on every platform.
    assert importlib.metadata.version("tzdata")


@pytest.mark.parametrize(
    ("tzid", "resolved"),
    [
        ("/mozilla.org/20050126_1/America/Los_Angeles", True),  # Thunderbird prefix
        ("America", False),  # a folder in the tz database: was a crash
        ("Pacific Standard Time", False),  # Windows/Outlook name: flagged, not guessed
        ("../../etc/passwd", False),
        ("X" * 300, False),
    ],
)
def test_odd_tzids_never_break_the_feed(tzid: str, resolved: bool) -> None:
    feed = (
        "BEGIN:VCALENDAR\r\n"
        f"BEGIN:VEVENT\r\nUID:odd\r\nDTSTART;TZID={tzid}:20261113T150000\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nUID:next\r\nDTSTART:20261113T150000Z\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    odd, following = parse(feed)
    assert following.starts_at == datetime(2026, 11, 13, 15, tzinfo=UTC)
    if resolved:
        assert odd.starts_at == datetime(2026, 11, 13, 23, tzinfo=UTC)
    else:
        assert odd.starts_at is None
        assert len(odd.flags["timezone_unresolved"]) <= 116


@pytest.mark.parametrize(
    ("local", "utc_hour"),
    [
        ("20261101T013000", 8),  # happens twice when clocks go back: the first, PDT
        ("20260308T023000", 10),  # never happens when clocks go forward: read as PST
    ],
)
def test_daylight_saving_edges_follow_rfc_5545(local: str, utc_hour: int) -> None:
    feed = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:edge\r\n"
        f"DTSTART;TZID=America/Los_Angeles:{local}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    (edge,) = parse(feed)
    assert edge.starts_at is not None
    assert (edge.starts_at.hour, edge.starts_at.minute) == (utc_hour, 30)
