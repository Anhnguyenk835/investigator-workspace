"""Progress events of an investigation run.

The graph reports each step as it finishes; the runner stores those events so a
browser that connects late, reconnects or reloads sees the same history. The SSE
endpoint replays stored events and then follows new ones. Events never carry
record content, only what happened (a step, a search, a status change)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

EventKind = Literal["run", "step", "tool", "status", "error", "done"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigation_events (
    id bigserial PRIMARY KEY,
    investigation_id uuid NOT NULL,
    kind text NOT NULL,
    data jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS investigation_events_inv_idx
    ON investigation_events (investigation_id, id);
"""

# Plain-language names for the graph's nodes, in the order a run meets them.
STEP_LABELS: dict[str, str] = {
    "intake": "Reading the question",
    "resolve_context": "Picking out customers, projects and dates",
    "plan_investigation": "Planning the search",
    "retrieve_evidence": "Searching sources",
    "seed_search": "Searching every connected source",
    "expand_threads": "Reading whole conversations and issues",
    "agent": "Following leads",
    "tools": "Reading more records",
    "wrap_up": "Noting what could not be retrieved",
    "normalize_dedupe": "Ordering records and removing duplicates",
    "assess_evidence": "Checking what was covered",
    "request_clarification": "Asking which case you mean",
    "analyze_evidence": "Analysing the evidence",
    "reconstruct_timeline": "Building the timeline",
    "extract_commitments": "Finding commitments",
    "analyze_blockers": "Finding blockers",
    "detect_contradictions": "Looking for contradictions and gaps",
    "synthesize_findings": "Writing findings",
    "verify_claims": "Checking that each cited record says what the claim says",
    "support_check": "Applying the support verdicts",
    "validate_claims": "Checking every claim against its evidence",
    "repair_findings": "Removing claims the evidence does not support",
    "recommend_actions": "Suggesting next steps",
    "human_review": "Waiting for your review",
    "reset_for_more_evidence": "Preparing another search",
    "draft_response": "Drafting the customer update",
    "human_approval": "Waiting for your approval",
    "complete_investigation": "Recording your sign-off",
    "finalize": "Finishing",
}


class RunEvent(BaseModel):
    id: int
    kind: EventKind
    data: dict[str, Any] = Field(default_factory=dict)
    at: datetime


class EventStore(Protocol):
    async def append(
        self, investigation_id: UUID, kind: EventKind, data: Mapping[str, Any]
    ) -> None: ...

    async def after(
        self, investigation_id: UUID, last_id: int, limit: int = 200
    ) -> list[RunEvent]: ...


class PostgresEventStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def append(
        self, investigation_id: UUID, kind: EventKind, data: Mapping[str, Any]
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO investigation_events (investigation_id, kind, data) "
                "VALUES (%s, %s, %s)",
                (investigation_id, kind, Jsonb(dict(data))),
            )

    async def after(
        self, investigation_id: UUID, last_id: int, limit: int = 200
    ) -> list[RunEvent]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT id, kind, data, created_at FROM investigation_events "
                "WHERE investigation_id = %s AND id > %s ORDER BY id LIMIT %s",
                (investigation_id, last_id, limit),
            )
            return [
                RunEvent(id=r["id"], kind=r["kind"], data=r["data"], at=r["created_at"])
                for r in await cur.fetchall()
            ]


class MemoryEventStore:
    """For tests and single-process development."""

    def __init__(self) -> None:
        self._events: list[tuple[UUID, RunEvent]] = []

    async def append(
        self, investigation_id: UUID, kind: EventKind, data: Mapping[str, Any]
    ) -> None:
        event = RunEvent(
            id=len(self._events) + 1, kind=kind, data=dict(data), at=datetime.now(UTC)
        )
        self._events.append((investigation_id, event))

    async def after(
        self, investigation_id: UUID, last_id: int, limit: int = 200
    ) -> list[RunEvent]:
        mine = [e for i, e in self._events if i == investigation_id and e.id > last_id]
        return mine[:limit]
