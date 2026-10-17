"""The guard runtime: policy plus the sinks and counters, shared by every `GuardedLlm`
in a process."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from investigator.guardrails.audit import AuditSink, LlmCall, MemoryAuditSink
from investigator.guardrails.breaker import (
    Breakers,
    CircuitBreaker,
    FlagStore,
    KillSwitch,
    MemoryFlagStore,
)
from investigator.guardrails.budget import BudgetTracker, UsageStore
from investigator.guardrails.context import current
from investigator.guardrails.events import GuardEvent
from investigator.guardrails.injection.quarantine import SUSPECT_AFTER, Decisions
from investigator.guardrails.pii.aliases import AliasBook, MemoryAliasBook
from investigator.guardrails.policy import GuardPolicy, Mode

log = logging.getLogger(__name__)

# Decides a passage the rules are unsure about: True aimed at an AI, False not, None unknown.
Classifier = Callable[[str], Awaitable[bool | None]]


class GuardRuntime:
    def __init__(
        self,
        policy: GuardPolicy | None = None,
        sink: AuditSink | None = None,
        usage: UsageStore | None = None,
        flags: FlagStore | None = None,
        aliases: AliasBook | None = None,
    ) -> None:
        self.policy = policy or GuardPolicy()
        self.aliases: AliasBook = aliases or MemoryAliasBook()
        self.sink: AuditSink = sink or MemoryAuditSink()
        self.budget = BudgetTracker(self.policy.limits, usage)
        threshold = self.policy.breaker_threshold
        self.breakers = Breakers(lambda: CircuitBreaker(threshold=threshold))
        self.flags: FlagStore = flags or MemoryFlagStore()
        self.kill = KillSwitch(self.flags, forced=self.policy.kill_switch)
        self.decisions = Decisions()
        self.classifier: Classifier | None = None
        self._suspect: dict[str, int] = {}

    @classmethod
    def for_tests(
        cls,
        policy: GuardPolicy | None = None,
        sink: AuditSink | None = None,
        usage: UsageStore | None = None,
        flags: FlagStore | None = None,
    ) -> GuardRuntime:
        return cls(policy or GuardPolicy(), sink or MemoryAuditSink(), usage, flags)

    async def note_suspect(self, record_id: str, high_count: int) -> None:
        """Several records in one run carried instructions: say so once, loudly."""
        ctx = current()
        key = ctx.thread_id or ctx.run_id
        if not key or not high_count:
            return
        self._suspect[key] = self._suspect.get(key, 0) + 1
        if self._suspect[key] == SUSPECT_AFTER:
            await self.emit(
                "injection",
                "run_suspect",
                enforced=False,
                action="allow",
                severity="high",
                record_id=record_id,
                detail=f"{SUSPECT_AFTER} records in this run carried instructions",
            )
        if len(self._suspect) > 5000:
            self._suspect.pop(next(iter(self._suspect)))

    def mode(self, guard: str) -> Mode:
        return self.policy.mode(guard)

    async def record_call(self, call: LlmCall) -> None:
        """Audit a call. A failing store never fails the call unless the policy says so."""
        if not self.policy.enabled:
            return
        call.policy_version = self.policy.fingerprint
        try:
            await self.sink.call(call)
        except Exception:
            if self.policy.audit_fail_closed:
                raise
            log.exception("could not audit an LLM call")

    async def emit(
        self,
        guard: str,
        rule: str,
        *,
        enforced: bool,
        action: str = "allow",
        severity: str = "info",
        route: str | None = None,
        record_id: str | None = None,
        detail: str | None = None,
    ) -> GuardEvent:
        ctx = current()
        event = GuardEvent(
            guard=guard,
            rule=rule,
            action=action,  # type: ignore[arg-type]
            enforced=enforced,
            severity=severity,  # type: ignore[arg-type]
            run_id=ctx.run_id,
            actor=ctx.actor,
            ip=ctx.ip,
            route=route,
            record_id=record_id,
            detail=detail[:160] if detail else None,
            policy_version=self.policy.fingerprint,
        )
        try:
            await self.sink.event(event)
        except Exception:
            if self.policy.audit_fail_closed:
                raise
            log.exception("could not audit a guard event")
        return event
