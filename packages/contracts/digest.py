"""The 简报 (ADR 0039): outside information worth knowing - news for investing, club events
(IG, Discord), useful tips from group chats (WeChat transfer group) - in one place, with
today vs history and read/unread. The original text is kept; a summary is never treated as
the original fact."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Channel = Literal["news", "club", "group", "other"]
CHANNEL_LABEL = {"news": "时事", "club": "社团活动", "group": "群聊精华", "other": "其他"}


class NewDigestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Channel
    source_name: Annotated[str, Field(min_length=1, max_length=120)]  # "微信转学群", "Reuters"
    title: Annotated[str, Field(min_length=1, max_length=300)]
    summary: Annotated[str, Field(max_length=4000)] = ""  # the distilled points
    raw_text: Annotated[str, Field(max_length=50_000)] = ""  # the original, kept as is
    url: Annotated[str, Field(max_length=2000)] = ""
    topics: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=40)]], Field(max_length=10)
    ] = []
    published_at: datetime | None = None  # when the source posted it; now when unknown
    happens_at: datetime | None = None  # an event's own time (a club meeting), if any
    important: bool = False


class DigestItem(BaseModel):
    id: str
    channel: Channel
    source_name: str
    title: str
    summary: str
    raw_text: str
    url: str
    topics: list[str]
    published_at: datetime
    happens_at: datetime | None
    important: bool
    read: bool
    read_at: datetime | None
    origin: str  # manual | connector name (later) | ai (later)
    created_at: datetime
    version: int


class DigestView(BaseModel):
    view: Literal["today", "history"]
    items: list[DigestItem]
    unread_today: int
    unread_history: int
    channels: dict[str, int]  # unread per channel in this view


class ReadMark(BaseModel):
    model_config = ConfigDict(extra="forbid")
    read: bool
