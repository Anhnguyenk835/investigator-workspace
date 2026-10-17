from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from investigator.agents.investigation.schemas import (
    Blocker,
    CaseContext,
    ClarificationQuestion,
    Commitment,
    Conflict,
    Finding,
    Gap,
    InvestigationPlan,
    MentionedEntities,
    RecommendedAction,
    TimelineEvent,
    ValidationReport,
)
from investigator.connectors import EvidenceRecord, SourceCoverage
from investigator.llm import ChatMessage
from investigator.tools import CallOutcome, ToolEvent

# "resolved" is reached only after a person approved the customer draft; the id
# and time of that person are recorded. "blocked" means paused for a person's answer.
InvestigationStatus = Literal[
    "investigating", "blocked", "needs_review", "resolved", "failed"
]
DraftStatus = Literal[
    "none", "drafted", "changes_requested", "approved", "not_possible"
]

__all__ = ["DraftStatus", "InvestigationState", "InvestigationStatus"]


class InvestigationState(BaseModel):
    # ---- identity & scope
    question: str
    context: CaseContext = Field(default_factory=CaseContext)
    mentioned: MentionedEntities = Field(default_factory=MentionedEntities)
    plan: InvestigationPlan = Field(default_factory=InvestigationPlan)
    # How the case was narrowed, in words ("Matched from the question: ..."); None when it was not.
    scope_note: str | None = None
    status: InvestigationStatus = "investigating"
    error: str | None = None

    # ---- retrieval (harness-owned; state, not the transcript, is the source of truth)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    duplicate_of: dict[str, str] = Field(default_factory=dict)
    coverage: list[SourceCoverage] = Field(default_factory=list)
    seen_calls: dict[str, str] = Field(default_factory=dict)
    pending_cursors: dict[str, list[str]] = Field(default_factory=dict)
    call_outcomes: dict[str, CallOutcome] = Field(default_factory=dict)
    tool_events: list[ToolEvent] = Field(default_factory=list)
    calls_used: int = 0

    # ---- search loop
    messages: list[ChatMessage] = Field(default_factory=list)
    tool_rounds: int = 0
    stale_rounds: int = 0
    search_notes: str | None = None
    retrieval_loops: int = 0
    expanded_threads: list[str] = Field(default_factory=list)

    # ---- clarification
    clarification_needed: list[ClarificationQuestion] = Field(default_factory=list)
    clarification_asked: bool = False
    retryable_sources: list[str] = Field(default_factory=list)
    validation_rounds: int = 0

    # ---- analysis
    timeline: list[TimelineEvent] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)

    # ---- findings
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    # Claims the model made that cited nothing real; kept for the reviewer.
    rejected_findings: list[Finding] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    actions: list[RecommendedAction] = Field(default_factory=list)

    # ---- review & response
    review_decision: Literal["pending", "approved", "needs_more_evidence", "revise"] = (
        "pending"
    )
    reviewer_notes: list[str] = Field(default_factory=list)
    review_loops: int = 0
    draft: str = ""
    draft_warnings: list[str] = Field(default_factory=list)
    draft_status: DraftStatus = "none"
    draft_rounds: int = 0
    resolved_by: str | None = None
    resolved_at: datetime | None = None
