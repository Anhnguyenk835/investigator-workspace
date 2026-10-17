"""Stop calling a model that is failing, and stop all calling on request."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

log = logging.getLogger(__name__)
State = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Opens after `threshold` failures in a row, stays open for a cooldown that doubles
    each time it re-opens (up to `max_cooldown`), then lets one probe call through."""

    def __init__(
        self,
        threshold: int = 5,
        cooldown: float = 30.0,
        max_cooldown: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.threshold = threshold
        self.base = cooldown
        self.max_cooldown = max_cooldown
        self._clock = clock
        self._failures = 0
        self._opened_at = 0.0
        self._cooldown = cooldown
        self._probing = False
        self._open = False

    @property
    def state(self) -> State:
        if not self._open:
            return "closed"
        if self._clock() - self._opened_at >= self._cooldown:
            return "half_open"
        return "open"

    def retry_after(self) -> int:
        return max(0, int(self._cooldown - (self._clock() - self._opened_at)) + 1)

    def allow(self) -> bool:
        state = self.state
        if state == "closed":
            return True
        if state == "half_open" and not self._probing:
            self._probing = True  # exactly one probe
            return True
        return False

    def success(self) -> None:
        self._failures = 0
        self._open = False
        self._probing = False
        self._cooldown = self.base

    def failure(self) -> None:
        if self._open:  # a failed probe: back off longer
            self._cooldown = min(self._cooldown * 2, self.max_cooldown)
            self._opened_at = self._clock()
            self._probing = False
            return
        self._failures += 1
        if self._failures >= self.threshold:
            self._open = True
            self._opened_at = self._clock()
            self._probing = False

    def release_probe(self) -> None:
        """The probe ended without telling us anything (not a gateway failure)."""
        self._probing = False


class Breakers:
    def __init__(self, factory: Callable[[], CircuitBreaker] | None = None) -> None:
        self._factory = factory or CircuitBreaker
        self._by_route: dict[str, CircuitBreaker] = {}

    def of(self, route: str) -> CircuitBreaker:
        if route not in self._by_route:
            self._by_route[route] = self._factory()
        return self._by_route[route]

    def states(self) -> dict[str, State]:
        return {r: b.state for r, b in self._by_route.items()}


class Flag(BaseModel):
    name: str  # "all" | "route:<name>" | "purpose:<name>"
    reason: str = ""
    set_by: str = ""
    set_at: datetime


class FlagStore(Protocol):
    async def all(self) -> list[Flag]: ...

    async def set(self, name: str, reason: str, set_by: str) -> None: ...

    async def clear(self, name: str) -> None: ...


class MemoryFlagStore:
    def __init__(self) -> None:
        self.flags: dict[str, Flag] = {}

    async def all(self) -> list[Flag]:
        return list(self.flags.values())

    async def set(self, name: str, reason: str, set_by: str) -> None:
        self.flags[name] = Flag(
            name=name, reason=reason, set_by=set_by, set_at=datetime.now(UTC)
        )

    async def clear(self, name: str) -> None:
        self.flags.pop(name, None)


FLAGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS guard_flags (
    name TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT '',
    set_by TEXT NOT NULL DEFAULT '', set_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


class PostgresFlagStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(FLAGS_SCHEMA)

    async def all(self) -> list[Flag]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT name, reason, set_by, set_at FROM guard_flags"
            )
            return [Flag(**r) for r in await cur.fetchall()]

    async def set(self, name: str, reason: str, set_by: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO guard_flags (name, reason, set_by, set_at) VALUES (%s,%s,%s,now()) "
                "ON CONFLICT (name) DO UPDATE SET reason = EXCLUDED.reason, "
                "set_by = EXCLUDED.set_by, set_at = now()",
                (name, reason, set_by),
            )

    async def clear(self, name: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM guard_flags WHERE name = %s", (name,))


@dataclass
class KillSwitch:
    """An administrator's off switch. A flag in the database reaches every process within
    `ttl` seconds; `forced` is the process-level switch from settings. If the database
    cannot be read the last known flags stay in force."""

    store: FlagStore
    forced: bool = False
    ttl: float = 5.0
    clock: Callable[[], float] = time.monotonic

    def __post_init__(self) -> None:
        self._cache: list[Flag] = []
        self._read_at = -1e9

    async def _flags(self) -> list[Flag]:
        if self.clock() - self._read_at >= self.ttl:
            try:
                self._cache = await self.store.all()
            except Exception:
                log.exception("could not read the kill-switch flags")
            self._read_at = self.clock()
        return self._cache

    async def refresh(self) -> None:
        self._read_at = -1e9

    async def reason(self, route: str, purpose: str) -> str | None:
        """Why this call must not go ahead, or None."""
        if self.forced:
            return "paused by configuration"
        for f in await self._flags():
            if f.name == "all":
                return f.reason or "paused by an administrator"
            if f.name == f"route:{route}" or f.name == f"purpose:{purpose}":
                return f.reason or f"{f.name} paused by an administrator"
        return None

    async def active(self) -> list[Flag]:
        await self.refresh()
        return await self._flags()
