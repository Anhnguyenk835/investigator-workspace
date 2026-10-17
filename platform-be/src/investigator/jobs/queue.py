"""A durable queue of investigation runs, kept in Postgres.

A run no longer lives and dies with the API process: the API writes a job, any worker
claims it with a lease, and a worker that dies lets its lease run out so another one
picks the run up again (from its last checkpoint)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from investigator.jobs.models import Job, JobKind

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY,
    kind text NOT NULL,
    investigation_id uuid NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'queued',
    attempts int NOT NULL DEFAULT 0,
    max_attempts int NOT NULL DEFAULT 3,
    locked_by text,
    locked_until timestamptz,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS jobs_claim_idx ON jobs (status, created_at);
CREATE INDEX IF NOT EXISTS jobs_investigation_idx ON jobs (investigation_id);
"""


class JobQueue(Protocol):
    async def enqueue(
        self, kind: JobKind, investigation_id: UUID, payload: dict[str, Any]
    ) -> UUID: ...

    async def claim(self, worker_id: str, lease_s: float) -> Job | None:
        """The next queued job, or one whose worker's lease ran out."""
        ...

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_s: float) -> bool:
        """Extend the lease; False when this worker no longer holds the job."""
        ...

    async def complete(self, job_id: UUID, worker_id: str) -> None: ...
    async def fail(self, job_id: UUID, worker_id: str, error: str) -> None: ...

    async def has_active(self, investigation_id: UUID) -> bool: ...


class PostgresJobQueue:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def enqueue(
        self, kind: JobKind, investigation_id: UUID, payload: dict[str, Any]
    ) -> UUID:
        job_id = uuid4()
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO jobs (id, kind, investigation_id, payload) VALUES (%s, %s, %s, %s)",
                (job_id, kind, investigation_id, Jsonb(payload)),
            )
        return job_id

    async def claim(self, worker_id: str, lease_s: float) -> Job | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            # A job that has already used its attempts is finished off, not retried forever.
            await cur.execute(
                "UPDATE jobs SET status = 'failed', error = 'Gave up after repeated worker failures.', "
                "updated_at = now() WHERE status = 'running' AND locked_until < now() "
                "AND attempts >= max_attempts"
            )
            await cur.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, locked_by = %s, "
                "locked_until = now() + make_interval(secs => %s), updated_at = now() "
                "WHERE id = (SELECT id FROM jobs WHERE status = 'queued' "
                "OR (status = 'running' AND locked_until < now()) "
                "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING *",
                (worker_id, lease_s),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return Job(
            id=row["id"],
            kind=row["kind"],
            investigation_id=row["investigation_id"],
            payload=row["payload"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
        )

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_s: float) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "UPDATE jobs SET locked_until = now() + make_interval(secs => %s), updated_at = now() "
                "WHERE id = %s AND locked_by = %s AND status = 'running'",
                (lease_s, job_id, worker_id),
            )
            return bool(cur.rowcount > 0)

    async def complete(self, job_id: UUID, worker_id: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'done', locked_until = NULL, updated_at = now() "
                "WHERE id = %s AND locked_by = %s",
                (job_id, worker_id),
            )

    async def fail(self, job_id: UUID, worker_id: str, error: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE jobs SET status = 'failed', error = %s, locked_until = NULL, "
                "updated_at = now() WHERE id = %s AND locked_by = %s",
                (error, job_id, worker_id),
            )

    async def has_active(self, investigation_id: UUID) -> bool:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT 1 AS x FROM jobs WHERE investigation_id = %s "
                "AND status IN ('queued', 'running') LIMIT 1",
                (investigation_id,),
            )
            return await cur.fetchone() is not None


class MemoryJobQueue:
    """For tests and single-process development. Same lease rules as Postgres."""

    def __init__(self, now: Any = lambda: datetime.now(UTC)) -> None:
        self._now = now
        self.rows: dict[UUID, dict[str, Any]] = {}

    async def enqueue(
        self, kind: JobKind, investigation_id: UUID, payload: dict[str, Any]
    ) -> UUID:
        job_id = uuid4()
        self.rows[job_id] = {
            "id": job_id,
            "kind": kind,
            "investigation_id": investigation_id,
            "payload": payload,
            "status": "queued",
            "attempts": 0,
            "max_attempts": 3,
            "locked_by": None,
            "locked_until": None,
            "error": None,
            "seq": len(self.rows),
        }
        return job_id

    async def claim(self, worker_id: str, lease_s: float) -> Job | None:
        now = self._now()
        for row in self.rows.values():
            if (
                row["status"] == "running"
                and row["locked_until"] < now
                and row["attempts"] >= row["max_attempts"]
            ):
                row.update(
                    status="failed", error="Gave up after repeated worker failures."
                )
        for row in sorted(self.rows.values(), key=lambda r: r["seq"]):
            claimable = row["status"] == "queued" or (
                row["status"] == "running" and row["locked_until"] < now
            )
            if claimable:
                row.update(
                    status="running",
                    attempts=row["attempts"] + 1,
                    locked_by=worker_id,
                    locked_until=now + timedelta(seconds=lease_s),
                )
                return Job(
                    id=row["id"],
                    kind=row["kind"],
                    investigation_id=row["investigation_id"],
                    payload=row["payload"],
                    attempts=row["attempts"],
                    max_attempts=row["max_attempts"],
                )
        return None

    async def heartbeat(self, job_id: UUID, worker_id: str, lease_s: float) -> bool:
        row = self.rows.get(job_id)
        if row is None or row["locked_by"] != worker_id or row["status"] != "running":
            return False
        row["locked_until"] = self._now() + timedelta(seconds=lease_s)
        return True

    async def complete(self, job_id: UUID, worker_id: str) -> None:
        row = self.rows.get(job_id)
        if row and row["locked_by"] == worker_id:
            row.update(status="done", locked_until=None)

    async def fail(self, job_id: UUID, worker_id: str, error: str) -> None:
        row = self.rows.get(job_id)
        if row and row["locked_by"] == worker_id:
            row.update(status="failed", error=error, locked_until=None)

    async def has_active(self, investigation_id: UUID) -> bool:
        return any(
            r["investigation_id"] == investigation_id
            and r["status"] in ("queued", "running")
            for r in self.rows.values()
        )
