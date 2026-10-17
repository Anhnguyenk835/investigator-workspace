from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

JobKind = Literal["start", "resume", "rerun"]


class Job(BaseModel):
    id: UUID
    kind: JobKind
    investigation_id: UUID
    payload: dict[str, Any] = Field(default_factory=dict)
    # How many times a worker has picked it up. More than one means an earlier worker died.
    attempts: int = 1
    max_attempts: int = 3
