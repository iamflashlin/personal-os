from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.types import TypeDecorator
from ulid import ULID


def new_id() -> str:
    return str(ULID())


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Stores UTC; rejects naive datetimes and always returns tz-aware UTC.

    SQLite has no timezone type, so without this a round trip silently drops tzinfo.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime; pass a timezone-aware value")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    pass


class Entity:
    """Common columns every Hub table carries (HANDOFF §4.3).

    `version` is SQLAlchemy's optimistic-lock counter: a stale UPDATE raises
    `StaleDataError` instead of overwriting a newer row. A subclass that needs its own
    `__mapper_args__` must merge into `Entity.__mapper_args__`, not replace it.
    """

    id: Mapped[str] = mapped_column(String(26), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    source: Mapped[str] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}
