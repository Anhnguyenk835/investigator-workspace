"""Investigation records. The graph checkpointer stores run internals; this
stores what the API shows: one row per investigation, with its latest result."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from investigator.agents.investigation.schemas import CaseContext
from investigator.agents.investigation.state import InvestigationState
from investigator.investigations.models import (
    RESULT_FIELDS,
    Awaiting,
    Investigation,
    InvestigationRunStatus,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id uuid PRIMARY KEY,
    question text NOT NULL,
    status text NOT NULL,
    result jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS awaiting text;
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS pending jsonb;
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS owner text;
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS owner_id text;
CREATE INDEX IF NOT EXISTS investigations_owner_idx ON investigations (owner_id, created_at DESC);
ALTER TABLE investigations ADD COLUMN IF NOT EXISTS run_no int NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS investigations_created_idx ON investigations (created_at DESC);
"""


class InvestigationStore(Protocol):
    async def create(
        self, question: str, context: CaseContext, owner_id: str | None = None
    ) -> Investigation: ...
    async def get(self, investigation_id: UUID) -> Investigation | None: ...
    async def list(
        self, limit: int = 50, owner_ids: Sequence[str | None] | None = None
    ) -> list[Investigation]:
        """`owner_ids` limits to those accounts' investigations (None in it: made before
        sign-in); omitted means everyone's, which only the system itself may ask for."""
        ...

    async def count_by_owner(self, owner_id: str) -> int: ...

    async def delete_owned(self, owner_id: str) -> int:
        """Remove everything an account made: investigations, their events and notes."""
        ...

    async def set_status(
        self, investigation_id: UUID, status: InvestigationRunStatus
    ) -> None:
        """Also clears `awaiting`/`pending`: a run that is moving is not waiting."""
        ...

    async def save_result(
        self,
        investigation_id: UUID,
        state: InvestigationState,
        *,
        status: InvestigationRunStatus,
        awaiting: Awaiting | None = None,
        pending: dict[str, Any] | None = None,
    ) -> None: ...

    async def fail(self, investigation_id: UUID, error: str) -> None: ...
    async def fail_unfinished(self, error: str) -> int: ...
    async def set_owner(self, investigation_id: UUID, owner: str | None) -> None: ...
    async def next_run(self, investigation_id: UUID) -> int:
        """Start another run of the same investigation: queued again, run number up by one."""
        ...


def _to_model(row: dict[str, Any]) -> Investigation:
    return Investigation(
        id=row["id"],
        question=row["question"],
        status=row["status"],
        owner=row["owner"],
        owner_id=row.get("owner_id"),
        run_no=row["run_no"],
        awaiting=row["awaiting"],
        pending=row["pending"],
        error=row["error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        **(row["result"] or {}),
    )


class PostgresInvestigationStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def _one(self, sql: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(sql, params)
            row: dict[str, Any] | None = await cur.fetchone()
            return row

    async def create(
        self, question: str, context: CaseContext, owner_id: str | None = None
    ) -> Investigation:
        row = await self._one(
            "INSERT INTO investigations (id, question, status, result, owner_id) "
            "VALUES (%s, %s, 'queued', %s, %s) RETURNING *",
            (
                uuid4(),
                question,
                Jsonb({"context": context.model_dump(mode="json")}),
                owner_id,
            ),
        )
        assert row is not None
        return _to_model(row)

    async def get(self, investigation_id: UUID) -> Investigation | None:
        row = await self._one(
            "SELECT * FROM investigations WHERE id = %s", (investigation_id,)
        )
        return _to_model(row) if row else None

    async def list(
        self, limit: int = 50, owner_ids: Sequence[str | None] | None = None
    ) -> list[Investigation]:
        where = ""
        params: list[Any] = [limit]
        if owner_ids is not None:
            ids = [o for o in owner_ids if o is not None]
            where = "WHERE owner_id = ANY(%s)" + (
                " OR owner_id IS NULL" if None in owner_ids else ""
            )
            params = [ids, limit]
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                f"SELECT * FROM investigations {where} ORDER BY created_at DESC LIMIT %s",
                params,
            )
            return [_to_model(r) for r in await cur.fetchall()]

    async def delete_owned(self, owner_id: str) -> int:
        async with self._pool.connection() as conn:
            ids = "(SELECT id FROM investigations WHERE owner_id = %s)"
            await conn.execute(
                f"DELETE FROM investigation_events WHERE investigation_id IN {ids}",
                (owner_id,),
            )
            await conn.execute(
                f"DELETE FROM annotations WHERE investigation_id IN {ids}",
                (owner_id,),
            )
            await conn.execute(
                f"DELETE FROM chat_messages WHERE investigation_id IN {ids}",
                (owner_id,),
            )
            await conn.execute(
                f"DELETE FROM chat_conversations WHERE investigation_id IN {ids}",
                (owner_id,),
            )
            cur = await conn.execute(
                "DELETE FROM investigations WHERE owner_id = %s", (owner_id,)
            )
            return int(cur.rowcount)

    async def count_by_owner(self, owner_id: str) -> int:
        row = await self._one(
            "SELECT count(*) AS n FROM investigations WHERE owner_id = %s", (owner_id,)
        )
        return int(row["n"]) if row else 0

    async def set_status(
        self, investigation_id: UUID, status: InvestigationRunStatus
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE investigations SET status = %s, awaiting = NULL, pending = NULL, "
                "updated_at = now() WHERE id = %s",
                (status, investigation_id),
            )

    async def save_result(
        self,
        investigation_id: UUID,
        state: InvestigationState,
        *,
        status: InvestigationRunStatus,
        awaiting: Awaiting | None = None,
        pending: dict[str, Any] | None = None,
    ) -> None:
        result = state.model_dump(mode="json", include=RESULT_FIELDS)
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE investigations SET status = %s, awaiting = %s, pending = %s, "
                "result = %s, error = %s, updated_at = now() WHERE id = %s",
                (
                    status,
                    awaiting,
                    Jsonb(pending) if pending is not None else None,
                    Jsonb(result),
                    state.error,
                    investigation_id,
                ),
            )

    async def fail(self, investigation_id: UUID, error: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE investigations SET status = 'failed', awaiting = NULL, pending = NULL, "
                "error = %s, updated_at = now() WHERE id = %s",
                (error, investigation_id),
            )

    async def fail_unfinished(self, error: str) -> int:
        """Runs live in this process; after a restart a queued or running one is gone.
        Paused runs (blocked, needs_review) survive: their state is in the checkpointer."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE investigations SET status = 'failed', error = %s, updated_at = now() "
                "WHERE status IN ('queued', 'investigating')",
                (error,),
            )
            return int(cur.rowcount)

    async def set_owner(self, investigation_id: UUID, owner: str | None) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE investigations SET owner = %s, updated_at = now() WHERE id = %s",
                (owner, investigation_id),
            )

    async def next_run(self, investigation_id: UUID) -> int:
        row = await self._one(
            "UPDATE investigations SET run_no = run_no + 1, status = 'queued', awaiting = NULL, "
            "pending = NULL, error = NULL, updated_at = now() WHERE id = %s RETURNING run_no",
            (investigation_id,),
        )
        assert row is not None
        return int(row["run_no"])

    async def fail_orphans(self, error: str) -> int:
        """Runs that look active but have no job behind them, e.g. from before the queue."""
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE investigations i SET status = 'failed', error = %s, updated_at = now() "
                "WHERE i.status IN ('queued', 'investigating') AND i.updated_at < now() - interval '1 minute' AND NOT EXISTS ("
                "SELECT 1 FROM jobs j WHERE j.investigation_id = i.id AND j.status IN ('queued', 'running'))",
                (error,),
            )
            return int(cur.rowcount)
