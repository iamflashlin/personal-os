"""Whitelisted actions. Each one does its work and then verifies it (ADR 0014)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from apps.desktop_agent.controller import WindowInfo
from packages.contracts.actions import ActionEvidenceKind, ActionStatus, EvidenceItem


@dataclass(frozen=True)
class Done:
    status: ActionStatus
    message: str
    evidence: list[EvidenceItem] = field(default_factory=list[EvidenceItem])


def window_evidence(window: WindowInfo, summary: str) -> EvidenceItem:
    return EvidenceItem(
        kind=ActionEvidenceKind.window,
        summary=summary,
        data={"title": window.title, "pid": window.pid},
        captured_at=datetime.now(UTC),
    )
