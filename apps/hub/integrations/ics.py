"""A small iCalendar (RFC 5545) reader: enough for calendar feeds such as Canvas's.

It reads VEVENTs with UID, SUMMARY, DESCRIPTION, LOCATION, URL, DTSTART and DTEND.
Recurrence rules are not expanded. Named time zones resolve through the `tzdata` package
(Windows has no system tz database); a TZID that still cannot be resolved keeps the raw
value and is flagged.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DATE = re.compile(r"\d{8}")
_DATETIME = re.compile(r"\d{8}T\d{6}Z?")


def _zone(tzid: str) -> ZoneInfo | None:
    """The zone a TZID names, or None. Accepts a vendor prefix such as Thunderbird's
    `/mozilla.org/20050126_1/America/Los_Angeles` by trying ever shorter tails."""
    parts = [p for p in tzid.strip().split("/") if p]
    for start in range(len(parts)):
        candidate = "/".join(parts[start:])
        try:
            return ZoneInfo(candidate)
        # OSError: with tzdata installed, a folder name such as "America" is a directory.
        except (ZoneInfoNotFoundError, ValueError, OSError):
            continue
    return None


class NotACalendar(ValueError):
    pass


@dataclass(frozen=True)
class Event:
    uid: str
    summary: str
    description: str
    location: str
    url: str
    starts_at: datetime | None
    ends_at: datetime | None
    all_day: bool
    flags: dict[str, str] = field(default_factory=dict[str, str])


def _unfold(text: str) -> list[str]:
    # Pieces are joined once per logical line: appending to a growing string would make
    # a hostile feed of continuation lines quadratic.
    logical: list[list[str]] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and logical:
            logical[-1].append(raw[1:])
        elif raw:
            logical.append([raw])
    return ["".join(pieces) for pieces in logical]


def _unescape(value: str) -> str:
    out: list[str] = []
    chars = iter(value)
    for c in chars:
        if c == "\\":
            nxt = next(chars, "")
            out.append("\n" if nxt in "nN" else nxt)
        else:
            out.append(c)
    return "".join(out)


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    parsed = {}
    for p in params:
        key, _, val = p.partition("=")
        parsed[key.upper()] = val.strip('"')
    return name.upper(), parsed, value


def _when(
    params: dict[str, str], value: str, flags: dict[str, str]
) -> tuple[datetime | None, bool]:
    """(UTC datetime, all-day). None with a flag when the value cannot be placed in time:
    one bad date must not fail the whole feed. The first flag of a kind is kept."""
    value = value.strip()
    try:
        if params.get("VALUE") == "DATE" or (len(value) == 8 and value.isdigit()):
            if not _DATE.fullmatch(value):
                raise ValueError(value)
            day = date(int(value[:4]), int(value[4:6]), int(value[6:8]))
            return datetime.combine(day, time(), tzinfo=UTC), True
        if not _DATETIME.fullmatch(value):
            raise ValueError(value)
        stamp = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    except ValueError:
        flags.setdefault("bad_time", value[:100])
        return None, False
    if value.endswith("Z"):
        return stamp.replace(tzinfo=UTC), False
    tzid = params.get("TZID")
    if tzid:
        zone = _zone(tzid)
        if zone is None:
            flags.setdefault("timezone_unresolved", f"{tzid[:100]} {value}")
            return None, False
        # fold=0: an ambiguous local time is its first occurrence, as RFC 5545 §3.3.5 says.
        return stamp.replace(tzinfo=zone).astimezone(UTC), False
    flags.setdefault("floating_time", value)  # no zone: "local time wherever you are"
    return None, False


def parse(text: str) -> list[Event]:
    return parse_feed(text)[0]


def parse_feed(text: str) -> tuple[list[Event], bool]:
    """The events, and whether the file really ended (`END:VCALENDAR` outside any event).
    A download cut short still yields the events before the cut, but is not complete."""
    lines = _unfold(text.lstrip("\ufeff"))
    if not lines or lines[0].strip().upper() != "BEGIN:VCALENDAR":
        raise NotACalendar("the feed is not an iCalendar file")
    events: list[Event] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None
    depth = 0  # VALARM and friends nest inside VEVENT
    for line in lines:
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            current, depth = {}, 0
        elif current is not None and name == "BEGIN":
            depth += 1
        elif current is not None and name == "END" and value.upper() != "VEVENT":
            depth -= 1
        elif current is not None and name == "END":
            events.extend(_event(current))
            current = None
        elif current is not None and depth == 0 and name not in current:
            current[name] = (params, value)
    ended = current is None and lines[-1].strip().upper() == "END:VCALENDAR"
    return events, ended


def _event(props: dict[str, tuple[dict[str, str], str]]) -> list[Event]:
    if "UID" not in props:
        return []  # nothing to recognise it by on the next sync
    flags: dict[str, str] = {}
    starts_at, all_day = (None, False)
    if "DTSTART" in props:
        starts_at, all_day = _when(*props["DTSTART"], flags)
    ends_at = _when(*props["DTEND"], flags)[0] if "DTEND" in props else None
    if "RRULE" in props:
        flags["recurrence_not_expanded"] = props["RRULE"][1]

    def text(key: str) -> str:
        return _unescape(props[key][1]) if key in props else ""

    return [
        Event(
            uid=text("UID"),
            summary=text("SUMMARY"),
            description=text("DESCRIPTION"),
            location=text("LOCATION"),
            url=text("URL"),
            starts_at=starts_at,
            ends_at=ends_at,
            all_day=all_day,
            flags=flags,
        )
    ]
