"""Questions about the user's mail, answered from stored summaries (ADR 0033).

Stateless: the browser keeps the conversation and sends its last turns with each question.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.contracts.integrations import SyncedItem
from packages.contracts.summaries import EmailSummary

MAX_QUESTION = 500
MAX_TURN = 1000
MAX_HISTORY = 6
MAX_CITED = 8


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(min_length=1, max_length=MAX_TURN)]


class ChatAsk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: Annotated[str, Field(min_length=1, max_length=MAX_QUESTION)]
    history: Annotated[list[ChatTurn], Field(max_length=MAX_HISTORY)] = []
    time_zone: Annotated[str, Field(max_length=64)] = ""  # IANA; "" = the Hub PC's zone


class CitedMail(BaseModel):
    item: SyncedItem
    summary: EmailSummary


class ChatAnswer(BaseModel):
    answer: str
    cited: list[CitedMail]  # at most MAX_CITED, only mails that were given to the model
    considered: int  # mails given to the model
    unsummarised: int  # mails not summarised yet, so not searchable
