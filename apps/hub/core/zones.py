"""Time zones named by the browser (IANA); "" means the Hub PC's own zone."""

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class UnknownZone(ValueError):
    pass


def zone_or_local(name: str) -> tzinfo:
    if not name:
        local = datetime.now().astimezone().tzinfo
        return local or UTC
    try:
        return ZoneInfo(name)
    # A key like "America" names a tzdata folder and raises an OSError, not NotFound.
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise UnknownZone(name) from None
