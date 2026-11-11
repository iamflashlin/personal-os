"""Domain types shared by every Hub module: who is acting, and how a request is refused."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Actor:
    owner_id: str
    source: str = "api"
    device_id: str | None = None  # set when a paired desktop agent is the one acting

    @property
    def name(self) -> str:
        return f"device:{self.device_id}" if self.device_id else f"owner:{self.owner_id}"


class DomainError(Exception):
    """A request the domain refuses; `result` is what the audit log records."""

    result = "error"


class NotFound(DomainError):
    result = "not_found"


class Conflict(DomainError):
    result = "conflict"


class Invalid(DomainError):
    result = "invalid"


class Forbidden(DomainError):
    result = "forbidden"


class Unavailable(DomainError):
    result = "unavailable"
