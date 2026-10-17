"""Analysis artefacts. Every one carries evidence ids; none is valid without them.

`*Draft` types are what the model returns. The final types add what code
derives (stable ids, times from evidence, computed status).
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from investigator.connectors import TimestampPrecision
from investigator.directory import SourceFilter


def stable_id(prefix: str, *parts: str) -> str:
    """Same content, same id: re-runs map onto earlier reviewed work."""
    raw = "\x1f".join(p.strip().lower() for p in parts)
    return f"{prefix}_{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


# ---- support: does the cited record say what the claim says ---------------------------

SupportVerdict = Literal["supported", "partial", "unsupported"]
SupportStatus = Literal["unchecked", "supported", "partial", "unsupported"]


class SupportCheck(BaseModel):
    """One cited record, judged against the claim that cites it."""

    evidence_id: str
    verdict: SupportVerdict
    # Copied verbatim from the record (code confirms it); None when nothing supports.
    quote: str | None = None


class SupportItemDraft(BaseModel):
    evidence_id: str
    verdict: SupportVerdict
    quote: str = ""


class SupportDraft(BaseModel):
    checks: list[SupportItemDraft] = []


# ---- case context & plan --------------------------------------------------------


class CaseContext(BaseModel):
    """Scope the user (or a clarification) set for this case. Filters, not guesses."""

    customer_id: str | None = None
    project_id: str | None = None
    ticket_ids: list[str] = Field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    sources: list[str] | None = None
    # What the person chose to search inside each source. Empty filter: all of it.
    source_filters: dict[str, SourceFilter] = Field(default_factory=dict)


class MentionedEntities(BaseModel):
    """Verbatim from the problem statement. Used to write queries, never as filters."""

    customers: list[str] = []
    projects: list[str] = []
    ticket_ids: list[str] = []
    people: list[str] = []
    date_hints: list[str] = []


class InvestigationPlan(BaseModel):
    questions: list[str] = Field(default=[], max_length=6)
    queries: list[str] = Field(default=[], max_length=5)


class ClarificationQuestion(BaseModel):
    key: Literal["project_id", "customer_id", "source_scope"]
    question: str
    options: list[str]
    # source_scope: which source this is about, and that several options may be chosen.
    source: str = ""
    multi: bool = False
    # Readable names for the option values (ids), when the directory knows them.
    labels: dict[str, str] = Field(default_factory=dict)


# ---- timeline -------------------------------------------------------------------

EventType = Literal[
    "customer_request",
    "internal_discussion",
    "commitment",
    "assignment",
    "status_change",
    "document_update",
    "blocker",
    "deadline_change",
    "delivery",
    "escalation",
    "other",
]


class TimelineEventDraft(BaseModel):
    title: str
    event_type: EventType = "other"
    actor: str | None = None
    summary: str
    evidence_ids: list[str] = Field(min_length=1)


class TimelineDraft(BaseModel):
    events: list[TimelineEventDraft] = []


class TimelineEvent(BaseModel):
    support: list[SupportCheck] = Field(default_factory=list)
    support_status: SupportStatus = "unchecked"
    id: str
    title: str
    event_type: EventType
    actor: str | None = None
    summary: str
    # Taken from the cited evidence by code, never written by the model.
    occurred_at: datetime | None = None
    timestamp_precision: TimestampPrecision = "unknown"
    evidence_ids: list[str] = Field(min_length=1)


# ---- commitments & blockers -----------------------------------------------------

CommitmentStatus = Literal["confirmed", "fulfilled", "at_risk", "overdue", "unverified"]


class CommitmentDraft(BaseModel):
    description: str
    committed_by: str | None = None
    owner: str | None = None
    due_date: date | None = None  # only as stated in the evidence
    basis: Literal["explicit", "inferred"]
    evidence_ids: list[str] = Field(min_length=1)
    fulfilled_by_evidence_ids: list[str] = []


class CommitmentsDraft(BaseModel):
    commitments: list[CommitmentDraft] = []


class Commitment(BaseModel):
    support: list[SupportCheck] = Field(default_factory=list)
    support_status: SupportStatus = "unchecked"
    id: str
    description: str
    committed_by: str | None = None
    owner: str | None = None  # None renders as "Owner not confirmed"
    promised_at: datetime | None = None
    due_date: date | None = None
    basis: Literal["explicit", "inferred"]
    status: CommitmentStatus  # computed by code from due_date, today and fulfilment
    evidence_ids: list[str] = Field(min_length=1)
    fulfilled_by_evidence_ids: list[str] = []


class BlockerDraft(BaseModel):
    description: str
    kind: Literal["blocker", "dependency", "probable_cause"]
    basis: Literal["stated", "inferred"]
    evidence_ids: list[str] = Field(min_length=1)


class BlockersDraft(BaseModel):
    blockers: list[BlockerDraft] = []


class Blocker(BlockerDraft):
    id: str


# ---- conflicts & gaps -----------------------------------------------------------


class ClaimSide(BaseModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class ConflictDraft(BaseModel):
    claim_a: ClaimSide
    claim_b: ClaimSide
    why: str


class GapDraft(BaseModel):
    what_missing: str
    why_it_matters: str
    resolving_evidence: str
    follow_up: str


class CrossCheckDraft(BaseModel):
    conflicts: list[ConflictDraft] = []
    gaps: list[GapDraft] = []


class Conflict(ConflictDraft):
    id: str
    # Only a person resolves a conflict.
    resolution: Literal["unresolved", "resolved"] = "unresolved"


class Gap(GapDraft):
    id: str
    origin: Literal["coverage", "analysis", "quality"]


# ---- findings, actions ----------------------------------------------------------

FindingStatus = Literal["verified", "needs_verification", "conflicting", "unknown"]


class FindingDraft(BaseModel):
    title: str
    claim: str
    explanation: str = ""
    status: FindingStatus
    supporting_evidence_ids: list[str] = []
    contradicting_evidence_ids: list[str] = []
    reasoning_type: Literal["direct", "inference"]


class SynthesisDraft(BaseModel):
    summary: str
    findings: list[FindingDraft] = []


class Finding(FindingDraft):
    support: list[SupportCheck] = Field(default_factory=list)
    support_status: SupportStatus = "unchecked"
    id: str
    # Set when a person has reviewed it; re-runs keep it.
    reviewer_note: str | None = None
    # Why this should be looked at before it is believed (set by validation).
    review_flag: str | None = None


class ActionDraft(BaseModel):
    title: str
    rationale: str
    owner: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    related_finding_ids: list[str] = []
    evidence_ids: list[str] = []


class ActionsDraft(BaseModel):
    actions: list[ActionDraft] = []


class RecommendedAction(ActionDraft):
    id: str
    status: Literal["suggested"] = "suggested"


IssueFix = Literal[
    "drop_ids", "drop_finding", "force_conflicting", "downgrade", "flag_tainted", "none"
]


class ValidationIssue(BaseModel):
    """One problem a validation check found. `error` blocks; `warning` informs."""

    finding_id: str | None = None
    code: str
    severity: Literal["error", "warning"]
    detail: str
    fix: IssueFix = "none"
    ids: list[str] = []


class ValidationReport(BaseModel):
    passed: bool = True
    issues: list[ValidationIssue] = []
    repaired: int = 0
    dropped: int = 0


# ---- human checkpoints ----------------------------------------------------------


class ReviewResume(BaseModel):
    decision: Literal["approved", "needs_more_evidence", "revise"]
    note: str = ""


class ClarificationResume(BaseModel):
    project_id: str | None = None
    customer_id: str | None = None
    # Source -> what to search in it. An empty list means all of that source.
    scope: dict[str, list[str]] = Field(default_factory=dict)
    note: str = ""


class DraftResume(BaseModel):
    approved: bool
    draft: str | None = None  # the user's edited text, if any
    note: str = ""


class DraftPlan(BaseModel):
    """What the model writes for the customer update."""

    text: str
