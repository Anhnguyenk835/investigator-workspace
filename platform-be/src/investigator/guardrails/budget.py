"""Token, cost and call budgets.

Per run (and per chat turn) the counters live in this process. Per-day totals keyed by
IP, by the self-declared actor and for the whole deployment live in a store shared by
every process. Several calls in flight at once can overshoot a limit slightly: this is
accounting for protection, not a billing system.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from investigator.guardrails.context import GuardContext

# Work a run can do without: cut first when the budget runs low, so the essential steps
# (turning evidence into findings, writing the draft) still have room to finish.
OPTIONAL_PURPOSES = frozenset({"investigation.tools", "support.check", "classifier"})
SOFT_FRACTION = 0.8


class Usage(BaseModel):
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0

    def plus(self, tokens: int, cost: float) -> Usage:
        return Usage(
            calls=self.calls + 1,
            tokens=self.tokens + tokens,
            cost_usd=self.cost_usd + cost,
        )


class RunLimits(BaseModel, extra="forbid"):
    calls: int
    tokens: int
    cost_usd: float


class BudgetLimits(BaseModel, frozen=True, extra="forbid"):
    max_input_tokens: int = 150_000
    run: RunLimits = RunLimits(calls=600, tokens=4_000_000, cost_usd=6.0)
    chat_turn: RunLimits = RunLimits(calls=30, tokens=400_000, cost_usd=1.0)
    ip_day_tokens: int = 20_000_000
    ip_day_cost_usd: float = 40.0
    actor_day_cost_usd: float = 40.0
    global_day_cost_usd: float = 200.0
    demo_day_cost_usd: float = 10.0
    max_classifier_calls_per_run: int = 60
    max_output_tokens: int | None = None
    # Estimated dollars per million tokens (input, output), by gateway route. These are
    # estimates for protection, not a bill: change them to match the contract.
    pricing: dict[str, tuple[float, float]] = {
        "fast": (0.25, 2.0),
        "strong": (1.25, 10.0),
    }


def price(limits: BudgetLimits, route: str, prompt: int, completion: int) -> float:
    cheap, dear = limits.pricing.get("fast"), limits.pricing.get("strong")
    p_in, p_out = limits.pricing.get(route) or dear or cheap or (0.0, 0.0)
    return (prompt * p_in + completion * p_out) / 1_000_000


def estimate_tokens(chars: int) -> int:
    return int(chars / 3.5) + 1


class Violation(BaseModel):
    rule: str
    message: str
    # Optional work is refused at the soft limit; everything is refused at the hard one.
    hard: bool


class UsageStore(Protocol):
    async def totals(
        self, day: date, ip: str | None, actor: str | None, demo: bool = False
    ) -> dict[str, Usage]: ...

    async def add(
        self,
        day: date,
        ip: str | None,
        actor: str | None,
        usage: Usage,
        demo: bool = False,
    ) -> None: ...


def _keys(
    ip: str | None, actor: str | None, demo: bool = False
) -> list[tuple[str, str]]:
    keys = [("global", "*")]
    if demo:
        keys.append(("demo", "*"))
    if ip:
        keys.append(("ip", ip))
    if actor:
        keys.append(("actor", actor))
    return keys


class MemoryUsageStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[date, str, str], Usage] = {}

    async def totals(
        self, day: date, ip: str | None, actor: str | None, demo: bool = False
    ) -> dict[str, Usage]:
        return {
            kind: self.rows.get((day, kind, key), Usage())
            for kind, key in _keys(ip, actor, demo)
        }

    async def add(
        self,
        day: date,
        ip: str | None,
        actor: str | None,
        usage: Usage,
        demo: bool = False,
    ) -> None:
        for kind, key in _keys(ip, actor, demo):
            now = self.rows.get((day, kind, key), Usage())
            self.rows[(day, kind, key)] = Usage(
                calls=now.calls + usage.calls,
                tokens=now.tokens + usage.tokens,
                cost_usd=now.cost_usd + usage.cost_usd,
            )


USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_usage_daily (
    day DATE NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
    calls BIGINT NOT NULL DEFAULT 0, tokens BIGINT NOT NULL DEFAULT 0,
    cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind, key)
);
"""


class PostgresUsageStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(USAGE_SCHEMA)

    async def totals(
        self, day: date, ip: str | None, actor: str | None, demo: bool = False
    ) -> dict[str, Usage]:
        keys = _keys(ip, actor, demo)
        out = {kind: Usage() for kind, _ in keys}
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT kind, key, calls, tokens, cost_usd FROM llm_usage_daily "
                "WHERE day = %s AND (kind, key) IN (SELECT * FROM unnest(%s::text[], %s::text[]))",
                (day, [k for k, _ in keys], [v for _, v in keys]),
            )
            for r in await cur.fetchall():
                out[r["kind"]] = Usage(
                    calls=r["calls"], tokens=r["tokens"], cost_usd=r["cost_usd"]
                )
        return out

    async def add(
        self,
        day: date,
        ip: str | None,
        actor: str | None,
        usage: Usage,
        demo: bool = False,
    ) -> None:
        async with self._pool.connection() as conn:
            for kind, key in _keys(ip, actor, demo):
                await conn.execute(
                    "INSERT INTO llm_usage_daily (day, kind, key, calls, tokens, cost_usd) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (day, kind, key) DO UPDATE SET "
                    "calls = llm_usage_daily.calls + EXCLUDED.calls, "
                    "tokens = llm_usage_daily.tokens + EXCLUDED.tokens, "
                    "cost_usd = llm_usage_daily.cost_usd + EXCLUDED.cost_usd",
                    (day, kind, key, usage.calls, usage.tokens, usage.cost_usd),
                )


def run_key(ctx: GuardContext) -> str | None:
    """A chat turn has its own thread id; an investigation run is keyed by its thread."""
    return ctx.thread_id or ctx.run_id


class BudgetTracker:
    def __init__(
        self,
        limits: BudgetLimits | None = None,
        store: UsageStore | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_runs: int = 5000,
    ) -> None:
        self.limits = limits or BudgetLimits()
        self.store: UsageStore = store or MemoryUsageStore()
        self._clock = clock
        self._runs: OrderedDict[str, Usage] = OrderedDict()
        self._classifier: dict[str, int] = {}
        self._max_runs = max_runs

    def day(self) -> date:
        return self._clock().date()

    def run_usage(self, ctx: GuardContext) -> Usage:
        key = run_key(ctx)
        return self._runs.get(key, Usage()) if key else Usage()

    def _run_limits(self, ctx: GuardContext) -> RunLimits:
        return (
            self.limits.chat_turn if ctx.purpose.startswith("chat") else self.limits.run
        )

    async def check(
        self, ctx: GuardContext, purpose: str, estimated_tokens: int
    ) -> list[Violation]:
        lim = self.limits
        found: list[Violation] = []
        if estimated_tokens > lim.max_input_tokens:
            found.append(
                Violation(
                    rule="call_too_large",
                    message="This request is larger than a single model call may be.",
                    hard=True,
                )
            )
        used, cap = self.run_usage(ctx), self._run_limits(ctx)
        for rule, now, limit in (
            ("run_calls", used.calls, cap.calls),
            ("run_tokens", used.tokens, cap.tokens),
            ("run_cost", used.cost_usd, cap.cost_usd),
        ):
            if now >= limit:
                found.append(
                    Violation(
                        rule=rule, message="This run used up its AI budget.", hard=True
                    )
                )
            elif now >= limit * SOFT_FRACTION:
                found.append(
                    Violation(
                        rule=rule,
                        message="This run is close to its AI budget.",
                        hard=False,
                    )
                )
        if purpose == "classifier":
            key = run_key(ctx) or ""
            if self._classifier.get(key, 0) >= lim.max_classifier_calls_per_run:
                found.append(
                    Violation(
                        rule="classifier_calls",
                        message="Screening budget used.",
                        hard=False,
                    )
                )
        totals = await self.store.totals(self.day(), ctx.ip, ctx.actor, ctx.demo)
        day_rules = (
            ("global_day_cost", totals["global"].cost_usd, lim.global_day_cost_usd),
            (
                "demo_day_cost",
                totals["demo"].cost_usd if "demo" in totals else 0.0,
                lim.demo_day_cost_usd,
            ),
            (
                "ip_day_cost",
                totals["ip"].cost_usd if "ip" in totals else 0.0,
                lim.ip_day_cost_usd,
            ),
            (
                "ip_day_tokens",
                float(totals["ip"].tokens) if "ip" in totals else 0.0,
                float(lim.ip_day_tokens),
            ),
            (
                "actor_day_cost",
                totals["actor"].cost_usd if "actor" in totals else 0.0,
                lim.actor_day_cost_usd,
            ),
        )
        for rule, now_f, limit_f in day_rules:
            if now_f >= limit_f:
                found.append(
                    Violation(
                        rule=rule,
                        message="The daily AI allowance has been used. Try again tomorrow.",
                        hard=True,
                    )
                )
        return found

    async def record(
        self, ctx: GuardContext, purpose: str, tokens: int, cost_usd: float
    ) -> None:
        key = run_key(ctx)
        if key:
            self._runs[key] = self._runs.get(key, Usage()).plus(tokens, cost_usd)
            self._runs.move_to_end(key)
            while len(self._runs) > self._max_runs:
                self._runs.popitem(last=False)
            if purpose == "classifier":
                self._classifier[key] = self._classifier.get(key, 0) + 1
                if len(self._classifier) > self._max_runs:
                    self._classifier.pop(next(iter(self._classifier)))
        await self.store.add(
            self.day(), ctx.ip, ctx.actor, Usage().plus(tokens, cost_usd), ctx.demo
        )
