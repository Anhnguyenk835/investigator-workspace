from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, computed_field

from investigator.agents.investigation.schemas import (
    Blocker,
    CaseContext,
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
from investigator.agents.investigation.state import DraftStatus
from investigator.auth.access import is_sample
from investigator.connectors import EvidenceRecord, SourceCoverage
from investigator.tools import ToolEvent

# "queued" exists only here: it is the state before the graph has started.
InvestigationRunStatus = Literal[
    "queued", "investigating", "blocked", "needs_review", "resolved", "failed"
]
# What a paused run is waiting for; each maps to one resume payload.
Awaiting = Literal["clarification", "review", "draft_approval"]

# The parts of the graph state the API exposes.
RESULT_FIELDS = {
    "context",
    "mentioned",
    "plan",
    "scope_note",
    "coverage",
    "evidence",
    "tool_events",
    "search_notes",
    "timeline",
    "commitments",
    "blockers",
    "conflicts",
    "gaps",
    "summary",
    "findings",
    "rejected_findings",
    "validation",
    "actions",
    "review_decision",
    "reviewer_notes",
    "draft",
    "draft_warnings",
    "draft_status",
    "resolved_by",
    "resolved_at",
}


class Investigation(BaseModel):
    id: UUID
    question: str
    status: InvestigationRunStatus
    # Who is looking after it (a name, set by a person; not a login).
    owner: str | None = None
    # The account that started it (None: made before sign-in existed).
    owner_id: str | None = None
    # Run number: a re-run starts a new run of the same investigation.
    run_no: int = 1
    awaiting: Awaiting | None = None
    pending: dict[str, Any] | None = None  # what the person is being asked
    context: CaseContext = Field(default_factory=CaseContext)
    mentioned: MentionedEntities = Field(default_factory=MentionedEntities)
    plan: InvestigationPlan = Field(default_factory=InvestigationPlan)
    scope_note: str | None = None
    coverage: list[SourceCoverage] = Field(default_factory=list)
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    rejected_findings: list[Finding] = Field(default_factory=list)
    validation: ValidationReport = Field(default_factory=ValidationReport)
    actions: list[RecommendedAction] = Field(default_factory=list)
    review_decision: str = "pending"
    reviewer_notes: list[str] = Field(default_factory=list)
    draft: str = ""
    draft_warnings: list[str] = Field(default_factory=list)
    draft_status: DraftStatus = "none"
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    search_notes: str | None = None
    tool_events: list[ToolEvent] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sample(self) -> bool:
        """A shared example everyone in the demo may read; nobody changes it."""
        return is_sample(self.owner_id)
