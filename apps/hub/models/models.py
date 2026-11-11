from sqlalchemy import Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from apps.hub.core.base import Base, Entity


class ModelCallRow(Entity, Base):
    """One language-model call: who asked, which prompt, tokens and cost (HANDOFF §4.3).

    It never stores prompt or email text. A row is written as `reserved` at its upper-bound
    estimate before the request, so a crash mid-call still counts against the budget.
    """

    __tablename__ = "model_call"
    __table_args__ = (Index("ix_model_call_owner_id_created_at", "owner_id", "created_at"),)

    vendor: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    ref: Mapped[str] = mapped_column(String(64), default="")
    prompt_name: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[int] = mapped_column(Integer)
    prompt_sha: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # reserved | ok | error
    error_kind: Mapped[str] = mapped_column(String(16), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimate_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro_usd: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    finish_reason: Mapped[str] = mapped_column(String(32), default="")
    request_id: Mapped[str] = mapped_column(String(100), default="")
