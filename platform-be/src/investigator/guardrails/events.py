"""What a guard decided, and the errors a guard raises."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from investigator.llm import LlmError

Action = Literal[
    "allow", "redact", "quarantine", "downgrade", "block", "degrade", "truncate"
]
Severity = Literal["info", "low", "medium", "high"]


class GuardEvent(BaseModel):
    """One decision. `enforced=False` means monitor mode: it would have acted, and did not."""

    guard: str
    rule: str
    action: Action
    enforced: bool
    severity: Severity = "info"
    run_id: str | None = None
    actor: str | None = None
    ip: str | None = None
    route: str | None = None
    record_id: str | None = None
    detail: str | None = Field(default=None, max_length=160)
    policy_version: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class GuardBlocked(LlmError):
    """A guard stopped the call. It is an `LlmError`, so every place that already handles a
    model failure (a run that ends in an error, a claim left unchecked) handles this too.
    `str(exc)` is written for the person reading it."""

    def __init__(self, message: str, *, guard: str = "", rule: str = "") -> None:
        super().__init__(message)
        self.guard = guard
        self.rule = rule


class GuardDegraded(GuardBlocked):
    """Refused for budget reasons. Optional work stops; essential work may still go on."""
