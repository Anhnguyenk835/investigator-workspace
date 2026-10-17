"""What the agent needs from a data source, and nothing about any one source.

A connector returns evidence plus an honest coverage status. "No matching
records" and "could not search" are different answers and must stay different.
Connectors enforce access; the harness re-checks scope as defence in depth.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from investigator.tools.context import AccessContext

CoverageStatus = Literal[
    "searched",
    "partial",
    "no_matches",
    "not_connected",
    "permission_denied",
    "failed",
]

TimestampPrecision = Literal["exact", "date_only", "unknown"]


class QuarantinedSpan(BaseModel):
    """Text in a record that reads as instructions to an AI. Positions index `excerpt`."""

    start: int
    end: int
    rule: str


Trust = Literal["normal", "flagged", "tainted"]


class EvidenceRecord(BaseModel):
    """One source record. `id` is stable; titles and positions are not."""

    id: str
    source: str
    title: str
    author: str | None = None
    occurred_at: datetime | None = None
    timestamp_precision: TimestampPrecision = "unknown"
    excerpt: str
    url: str | None = None
    thread_id: str | None = None
    customer_id: str | None = None
    project_id: str | None = None
    # Set by normalisation; equal hashes mean the same content (e.g. a forward).
    content_hash: str | None = None
    # Who wrote it, as the directory knows them. Absent when nobody matches.
    author_id: str | None = None  # an address, Slack user id or Jira account id
    author_side: Literal["customer", "internal", "third_party"] | None = None
    author_role: str | None = None
    participants: list[str] = Field(default_factory=list)
    # Where it came from (channel, project key, space): how a record is matched to a
    # project. Facts about the location only, never content.
    meta: dict[str, str] = Field(default_factory=dict)
    # Set by the injection guard, never by a connector. `excerpt` is always the full original
    # for people; the model sees `model_excerpt` (and `model_title`/`model_author`) when set.
    trust: Trust = "normal"
    quarantine: list[QuarantinedSpan] = Field(default_factory=list)
    model_excerpt: str | None = None
    model_title: str | None = None
    model_author: str | None = None


class SourceCoverage(BaseModel):
    source: str
    status: CoverageStatus
    detail: str | None = None


class SearchQuery(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    date_from: date | None = None
    date_to: date | None = None
    cursor: str | None = None


class SearchResult(BaseModel):
    """`no_matches` is only valid when the whole window was scanned; a source
    that could not say must return `partial` or `failed`."""

    coverage: SourceCoverage
    records: list[EvidenceRecord] = []
    next_cursor: str | None = None


class SourceConnector(Protocol):
    name: str

    async def search(self, query: SearchQuery, ctx: AccessContext) -> SearchResult: ...

    async def get_record(self, record_id: str, ctx: AccessContext) -> SearchResult: ...

    async def get_thread(self, thread_id: str, ctx: AccessContext) -> SearchResult: ...
