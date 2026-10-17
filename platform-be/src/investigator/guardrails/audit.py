"""Where LLM calls and guard decisions are recorded. Hashes, counts and sizes only:
this is not a content log, and it cannot replay a prompt."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field

from investigator.guardrails.events import GuardEvent

log = logging.getLogger(__name__)

CallStatus = str  # ok | blocked | error | degraded | killed


class LlmCall(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    run_id: str | None = None
    thread_id: str | None = None
    actor: str | None = None
    actor_verified: bool = False
    ip: str | None = None
    purpose: str = "unbound"
    method: str = ""
    route: str = ""
    model: str = ""
    policy_version: str = ""
    status: CallStatus = "ok"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_estimated: bool = False
    cost_usd: float = 0.0
    latency_ms: int = 0
    input_sha256: str = ""
    input_chars: int = 0
    output_chars: int = 0
    tool_call_names: list[str] = Field(default_factory=list)
    error_class: str | None = None


class AuditSink(Protocol):
    async def call(self, record: LlmCall) -> None: ...

    async def event(self, event: GuardEvent) -> None: ...

    async def summary(self, since: datetime) -> dict[str, Any]: ...

    async def recent_events(
        self, since: datetime, guard: str | None, run_id: str | None, limit: int
    ) -> list[GuardEvent]: ...


class MemoryAuditSink:
    def __init__(self) -> None:
        self.calls: list[LlmCall] = []
        self.events: list[GuardEvent] = []

    async def call(self, record: LlmCall) -> None:
        self.calls.append(record)

    async def event(self, event: GuardEvent) -> None:
        self.events.append(event)

    async def summary(self, since: datetime) -> dict[str, Any]:
        calls = [c for c in self.calls if c.at >= since]
        events = [e for e in self.events if e.at >= since]
        by_status: dict[str, int] = {}
        for c in calls:
            by_status[c.status] = by_status.get(c.status, 0) + 1
        rules: dict[tuple[str, str, bool], int] = {}
        for e in events:
            k = (e.guard, e.rule, e.enforced)
            rules[k] = rules.get(k, 0) + 1
        return {
            "calls": len(calls),
            "prompt_tokens": sum(c.prompt_tokens for c in calls),
            "completion_tokens": sum(c.completion_tokens for c in calls),
            "cost_usd": round(sum(c.cost_usd for c in calls), 4),
            "by_status": by_status,
            "rules": [
                {"guard": g, "rule": r, "enforced": en, "count": n}
                for (g, r, en), n in sorted(rules.items(), key=lambda kv: -kv[1])
            ],
            "top_ips": _top(c.ip for c in calls),
            "top_actors": _top(c.actor for c in calls),
        }

    async def recent_events(
        self, since: datetime, guard: str | None, run_id: str | None, limit: int
    ) -> list[GuardEvent]:
        found = [
            e
            for e in self.events
            if e.at >= since
            and (guard is None or e.guard == guard)
            and (run_id is None or e.run_id == run_id)
        ]
        return found[-limit:][::-1]


def _top(values: Any, n: int = 5) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:n]
    return [{"key": k, "calls": c} for k, c in ranked]


SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_call_audit (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    run_id TEXT, thread_id TEXT, actor TEXT, actor_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ip TEXT, purpose TEXT NOT NULL, method TEXT NOT NULL, route TEXT NOT NULL,
    model TEXT NOT NULL, policy_version TEXT NOT NULL, status TEXT NOT NULL,
    prompt_tokens INT NOT NULL, completion_tokens INT NOT NULL,
    usage_estimated BOOLEAN NOT NULL, cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0, latency_ms INT NOT NULL,
    input_sha256 TEXT NOT NULL, input_chars INT NOT NULL, output_chars INT NOT NULL,
    tool_call_names JSONB NOT NULL, error_class TEXT
);
ALTER TABLE llm_call_audit ADD COLUMN IF NOT EXISTS cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS llm_call_audit_at ON llm_call_audit (at DESC);
CREATE INDEX IF NOT EXISTS llm_call_audit_run ON llm_call_audit (run_id);
CREATE TABLE IF NOT EXISTS guard_event (
    id BIGSERIAL PRIMARY KEY,
    at TIMESTAMPTZ NOT NULL,
    run_id TEXT, actor TEXT, ip TEXT, route TEXT, guard TEXT NOT NULL, rule TEXT NOT NULL,
    action TEXT NOT NULL, enforced BOOLEAN NOT NULL, severity TEXT NOT NULL,
    record_id TEXT, detail TEXT, policy_version TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS guard_event_at ON guard_event (at DESC);
CREATE INDEX IF NOT EXISTS guard_event_run ON guard_event (run_id);
"""


_PG_SUMMARY = """
SELECT count(*) AS calls, coalesce(sum(prompt_tokens),0) AS pt,
       coalesce(sum(completion_tokens),0) AS ct, coalesce(sum(cost_usd),0) AS cost
FROM llm_call_audit WHERE at >= %s
"""


class _PostgresReads:
    _pool: AsyncConnectionPool[Any]

    async def summary(self, since: datetime) -> dict[str, Any]:
        async with self._pool.connection() as conn:
            row = await (await conn.execute(_PG_SUMMARY, (since,))).fetchone()
            status = await (
                await conn.execute(
                    "SELECT status, count(*) AS n FROM llm_call_audit WHERE at >= %s GROUP BY status",
                    (since,),
                )
            ).fetchall()
            rules = await (
                await conn.execute(
                    "SELECT guard, rule, enforced, count(*) AS n FROM guard_event WHERE at >= %s "
                    "GROUP BY guard, rule, enforced ORDER BY n DESC LIMIT 50",
                    (since,),
                )
            ).fetchall()
            ips = await (
                await conn.execute(
                    "SELECT ip AS key, count(*) AS calls FROM llm_call_audit WHERE at >= %s "
                    "AND ip IS NOT NULL GROUP BY ip ORDER BY calls DESC LIMIT 5",
                    (since,),
                )
            ).fetchall()
            actors = await (
                await conn.execute(
                    "SELECT actor AS key, count(*) AS calls FROM llm_call_audit WHERE at >= %s "
                    "AND actor IS NOT NULL GROUP BY actor ORDER BY calls DESC LIMIT 5",
                    (since,),
                )
            ).fetchall()
        assert row is not None
        return {
            "calls": row["calls"],
            "prompt_tokens": int(row["pt"]),
            "completion_tokens": int(row["ct"]),
            "cost_usd": round(float(row["cost"]), 4),
            "by_status": {r["status"]: r["n"] for r in status},
            "rules": [
                {
                    "guard": r["guard"],
                    "rule": r["rule"],
                    "enforced": r["enforced"],
                    "count": r["n"],
                }
                for r in rules
            ],
            "top_ips": [dict(r) for r in ips],
            "top_actors": [dict(r) for r in actors],
        }

    async def recent_events(
        self, since: datetime, guard: str | None, run_id: str | None, limit: int
    ) -> list[GuardEvent]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT at, run_id, actor, ip, route, guard, rule, action, enforced, severity, "
                "record_id, detail, policy_version FROM guard_event WHERE at >= %s "
                "AND (%s::text IS NULL OR guard = %s) AND (%s::text IS NULL OR run_id = %s) "
                "ORDER BY id DESC LIMIT %s",
                (since, guard, guard, run_id, run_id, limit),
            )
            return [GuardEvent(**r) for r in await cur.fetchall()]


class PostgresAuditSink(_PostgresReads):
    """Expects a pool opened with autocommit=True."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def purge_older_than(self, days: int) -> int:
        """Delete audit rows older than `days`. Retention policy is decided elsewhere; this is
        the hook it calls."""
        async with self._pool.connection() as conn:
            n = 0
            for table in ("llm_call_audit", "guard_event"):
                cur = await conn.execute(
                    f"DELETE FROM {table} WHERE at < now() - make_interval(days => %s)",
                    (days,),
                )
                n += cur.rowcount
            return n

    async def call(self, r: LlmCall) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO llm_call_audit (at, run_id, thread_id, actor, actor_verified, ip, "
                "purpose, method, route, model, policy_version, status, prompt_tokens, "
                "completion_tokens, usage_estimated, cost_usd, latency_ms, input_sha256, input_chars, "
                "output_chars, tool_call_names, error_class) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    r.at, r.run_id, r.thread_id, r.actor, r.actor_verified, r.ip,
                    r.purpose, r.method, r.route, r.model, r.policy_version, r.status,
                    r.prompt_tokens, r.completion_tokens, r.usage_estimated, r.cost_usd, r.latency_ms,
                    r.input_sha256, r.input_chars, r.output_chars,
                    Jsonb(r.tool_call_names), r.error_class,
                ),
            )  # fmt: skip

    async def event(self, e: GuardEvent) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO guard_event (at, run_id, actor, ip, route, guard, rule, action, "
                "enforced, severity, record_id, detail, policy_version) VALUES "
                "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    e.at, e.run_id, e.actor, e.ip, e.route, e.guard, e.rule, e.action,
                    e.enforced, e.severity, e.record_id, e.detail, e.policy_version,
                ),
            )  # fmt: skip


class BufferedAuditSink:
    """Writes in the background so an audit store that is slow or down never slows a call.
    The queue is bounded: when it is full the oldest item is dropped and counted."""

    def __init__(self, inner: AuditSink, maxsize: int = 2000) -> None:
        self._inner = inner
        self._queue: asyncio.Queue[LlmCall | GuardEvent] = asyncio.Queue(maxsize)
        self._task: asyncio.Task[None] | None = None
        self.dropped = 0
        self.failed = 0

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._drain())

    async def aclose(self) -> None:
        """Flush what is queued, then stop."""
        if self._task is None:
            return
        await self._queue.join()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def _put(self, item: LlmCall | GuardEvent) -> None:
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
                self._queue.task_done()
            self.dropped += 1
        self._queue.put_nowait(item)

    async def call(self, record: LlmCall) -> None:
        self._put(record)

    async def event(self, event: GuardEvent) -> None:
        self._put(event)

    async def summary(self, since: datetime) -> dict[str, Any]:
        out = await self._inner.summary(since)
        out["audit_queue"] = {"dropped": self.dropped, "failed": self.failed}
        return out

    async def recent_events(
        self, since: datetime, guard: str | None, run_id: str | None, limit: int
    ) -> list[GuardEvent]:
        return await self._inner.recent_events(since, guard, run_id, limit)

    async def _drain(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if isinstance(item, LlmCall):
                    await self._inner.call(item)
                else:
                    await self._inner.event(item)
            except Exception:  # audit must not take the service down
                self.failed += 1
                log.exception("audit write failed")
            finally:
                self._queue.task_done()
