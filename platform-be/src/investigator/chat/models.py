from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from investigator.connectors import EvidenceRecord

DEFAULT_TITLE = "New chat"


class Conversation(BaseModel):
    """One thread of questions and answers about an investigation. An investigation can
    have many; each is independent (the assistant sees only its own earlier turns)."""

    id: UUID
    investigation_id: UUID
    # Whose conversation: the account that started it (None: before sign-in existed).
    owner_id: str | None = None
    title: str = DEFAULT_TITLE
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


def title_from(text: str) -> str:
    """A conversation is named after its first question."""
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:59].rstrip() + "…"


class StoredMessage(BaseModel):
    id: UUID
    investigation_id: UUID
    conversation_id: UUID | None = None
    role: Literal["user", "assistant"]
    content: str
    # Assistant messages only.
    citations: list[str] = Field(default_factory=list)
    # Records the answer found by searching again; they are not in the investigation.
    new_evidence: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
