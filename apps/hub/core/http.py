"""FastAPI plumbing shared by every module's `api.py`."""

from collections.abc import Awaitable, Callable, Iterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from apps.hub.core.db import run_in_session
from apps.hub.core.domain import (
    Actor,
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    Unavailable,
)

__all__ = ["ActorDep", "SessionDep", "acall", "call", "run_in_session"]

_STATUS: dict[type[DomainError], int] = {
    NotFound: 404,
    Conflict: 409,
    Invalid: 422,
    Forbidden: 403,
    Unavailable: 503,
}


def _session(request: Request) -> Iterator[Session]:
    with Session(request.app.state.engine, expire_on_commit=False) as session:
        yield session


def _actor(request: Request) -> Actor:
    return Actor(owner_id=request.app.state.settings.owner_id)


SessionDep = Annotated[Session, Depends(_session)]
ActorDep = Annotated[Actor, Depends(_actor)]


def call[T](fn: Callable[[], T]) -> T:
    """Run a service call, turning a refused request into its HTTP status."""
    try:
        return fn()
    except DomainError as exc:
        # Any other refusal is still the client's request being refused: 400.
        status = next((_STATUS[c] for c in type(exc).__mro__ if c in _STATUS), 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc


async def acall[T](work: Awaitable[T]) -> T:
    """`call` for async service functions."""
    try:
        return await work
    except DomainError as exc:
        status = next((_STATUS[c] for c in type(exc).__mro__ if c in _STATUS), 400)
        raise HTTPException(status_code=status, detail=str(exc)) from exc
