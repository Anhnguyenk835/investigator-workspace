"""The tool harness: everything between the model's tool call and the connector.

The model proposes a call; the harness decides what actually runs. It
  - validates arguments and rejects ids the investigation has not seen,
  - clamps source, dates and case scope from the backend's AccessContext,
  - enforces a per-run call budget, per-call timeout and result caps,
  - answers repeated identical calls from cache without spending budget,
  - never raises into the model: every outcome becomes structured status plus
    a sentinel text that says what the status does and does not mean,
  - merges evidence and coverage into the ledger (state stays the source of
    truth, not the chat transcript),
  - records an audit event per call (no content, no credentials).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError

from investigator.connectors import (
    CoverageStatus,
    EvidenceRecord,
    SearchQuery,
    SearchResult,
    SourceConnector,
    SourceCoverage,
)
from investigator.guardrails import GuardRuntime, current
from investigator.guardrails.egress import Refusal, screen_search
from investigator.guardrails.injection.quarantine import protect
from investigator.guardrails.injection.spotlight import attr, neutralize
from investigator.llm import ToolCall
from investigator.tools.context import AccessContext
from investigator.tools.specs import (
    TOOL_ARGS,
    GetRecordArgs,
    GetThreadArgs,
    SearchRecordsArgs,
    openai_tools,
)


@dataclass(frozen=True)
class HarnessLimits:
    max_tool_calls: int = 100  # per run, seed searches and thread reads included
    max_rounds: int = 8  # model turns that call tools
    max_stale_rounds: int = 2  # consecutive rounds that add no new record
    max_records_per_call: int = 20
    excerpt_chars: int = 1500
    timeout_s: float = 20.0


class ToolEvent(BaseModel):
    """Audit trail of one call. Arguments are hashed; content is never stored."""

    tool: str
    args_hash: str
    source: str | None = None
    status: str
    records: int = 0
    new_records: int = 0
    duration_ms: int = 0
    note: str | None = None


class CallOutcome(BaseModel):
    """What one distinct call last returned. A retry overwrites it, so a source
    that failed once and then succeeded is reported by its latest attempt."""

    source: str
    status: CoverageStatus
    detail: str | None = None


@dataclass
class Ledger:
    """Mutable working copy of the harness-owned part of the run state."""

    evidence: dict[str, EvidenceRecord] = field(default_factory=dict)
    coverage: dict[str, SourceCoverage] = field(default_factory=dict)
    seen_calls: dict[str, str] = field(default_factory=dict)
    pending_cursors: dict[str, list[str]] = field(default_factory=dict)
    call_outcomes: dict[str, CallOutcome] = field(default_factory=dict)
    events: list[ToolEvent] = field(default_factory=list)
    calls_used: int = 0

    def known_thread_ids(self) -> dict[str, str]:
        return {e.thread_id: e.source for e in self.evidence.values() if e.thread_id}


_OK = {"searched", "no_matches"}


def merge_status(old: CoverageStatus, new: CoverageStatus) -> CoverageStatus:
    """Combine two calls' outcomes for one source without overstating coverage."""
    if old == new:
        return old
    if old in _OK and new in _OK:
        return "searched"
    if "partial" in (old, new):
        return "partial"
    if (old in _OK) != (new in _OK):  # one worked, the other did not
        return "partial"
    return new


def _fold_coverage(source: str, outcomes: dict[str, CallOutcome]) -> SourceCoverage:
    mine = [o for o in outcomes.values() if o.source == source]
    status = mine[0].status
    for o in mine[1:]:
        status = merge_status(status, o.status)
    detail = next((o.detail for o in reversed(mine) if o.detail), None)
    return SourceCoverage(source=source, status=status, detail=detail)


def _hash(name: str, args: dict[str, Any]) -> str:
    raw = json.dumps({"n": name, "a": args}, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


DOCUMENT_CHARS = 4000  # an attached document gets more room than a message


def render_record(rec: EvidenceRecord, excerpt_chars: int) -> str:
    """One record as the model reads it, inside a tag the prompts call untrusted data.

    What the model reads is `model_excerpt` when the injection guard has set one, otherwise
    the original. Invisible characters are dropped, and anything that imitates one of our
    tags is defused, so a record cannot close its own wrapper or open a fake one.
    """
    if rec.meta.get("kind") == "attachment":
        excerpt_chars = max(excerpt_chars, DOCUMENT_CHARS)
    body = rec.model_excerpt if rec.model_excerpt is not None else rec.excerpt
    excerpt = body[:excerpt_chars]
    if len(body) > excerpt_chars:
        excerpt += " …[truncated]"
    excerpt = neutralize(excerpt)
    when = rec.occurred_at.isoformat() if rec.occurred_at else "undated"
    thread = f' thread="{attr(rec.thread_id)}"' if rec.thread_id else ""
    who = ""
    if rec.author_side:
        role = f" ({attr(rec.author_role)})" if rec.author_role else ""
        who = f' side="{rec.author_side}{role}"'
    title = rec.model_title if rec.model_title is not None else rec.title
    author = rec.model_author if rec.model_author is not None else rec.author
    flagged = ' flagged="instructions removed"' if rec.model_excerpt is not None else ""
    return (
        f'<record id="{attr(rec.id)}" source="{attr(rec.source)}"{thread} '
        f'title="{attr(title)}" author="{attr(author or "unknown")}"{who} '
        f'time="{when}" precision="{rec.timestamp_precision}"{flagged}>\n{excerpt}\n</record>'
    )


_SENTINEL = {
    "no_matches": (
        "NO_MATCHES: the search completed and found nothing. This is not proof that "
        "nothing exists elsewhere."
    ),
    "not_connected": "SOURCE_NOT_CONNECTED: this source is not connected. Do not retry.",
    "permission_denied": "PERMISSION_DENIED: access to this source is not allowed. Do not retry.",
    "failed": (
        "SOURCE_UNAVAILABLE: the source could not be searched. This says nothing about "
        "whether records exist; report it as not searched and do not estimate."
    ),
    "partial": "PARTIAL: results are incomplete.",
    "searched": "OK",
}


class ToolHarness:
    def __init__(
        self,
        connectors: dict[str, SourceConnector],
        limits: HarnessLimits | None = None,
        guard: GuardRuntime | None = None,
    ) -> None:
        self._connectors = connectors
        self.limits = limits or HarnessLimits()
        self._guard = guard

    # ---- what the model is offered -------------------------------------------------

    async def suggestions(
        self, source: str, ctx: AccessContext
    ) -> tuple[str, list[dict[str, str]]]:
        """What a person could choose to search in a source: its channels, projects, labels
        or spaces. ("not_connected", []) when the source cannot list them."""
        found = getattr(self._connectors.get(source), "suggestions", None)
        if found is None:
            return "not_connected", []
        return await found(ctx)  # type: ignore[no-any-return]

    def readable_sources(self, ctx: AccessContext) -> list[str]:
        names = [n for n in self._connectors if n in ctx.permitted_sources]
        if ctx.source_scope is not None:
            names = [n for n in names if n in ctx.source_scope]
        return sorted(names)

    def tool_schemas(self, ctx: AccessContext) -> list[dict[str, Any]]:
        sources = self.readable_sources(ctx)
        return openai_tools(sources) if sources else []

    def record_denied_sources(self, ledger: Ledger, ctx: AccessContext) -> None:
        """Connected but not permitted: coverage says so instead of staying silent."""
        for name in self._connectors:
            if name not in ctx.permitted_sources:
                ledger.coverage[name] = SourceCoverage(
                    source=name,
                    status="permission_denied",
                    detail="Access not permitted.",
                )

    # ---- execution -----------------------------------------------------------------

    async def run_calls(
        self, calls: list[ToolCall], ledger: Ledger, ctx: AccessContext
    ) -> list[tuple[ToolCall, str]]:
        """Run one model turn's calls. Sequential so budget and cache stay exact;
        every call id gets an answer, as the provider API requires."""
        out: list[tuple[ToolCall, str]] = []
        for c in calls:
            refusal = await self._screen(c, ledger)
            out.append(
                (
                    c,
                    refusal
                    if refusal is not None
                    else await self.execute(c, ledger, ctx),
                )
            )
        return out

    async def _screen(self, call: ToolCall, ledger: Ledger) -> str | None:
        """The guardrail's say on a search the model asked for. Calls the backend makes itself
        (the first searches, reading threads) are not screened: they are not the model's."""
        guard = self._guard
        if guard is None or call.name != "search_records":
            return None
        mode = guard.mode("egress")
        if mode == "off":
            return None
        try:
            args = SearchRecordsArgs.model_validate_json(call.arguments)
        except ValidationError:
            return None  # `execute` reports invalid arguments
        pending = {
            p.split("\x1f", 1)[1]
            for ps in ledger.pending_cursors.values()
            for p in ps
            if "\x1f" in p
        }
        try:
            refusal = screen_search(
                args.query,
                args.cursor,
                current(),
                corpus=[e.excerpt for e in ledger.evidence.values()],
                pending_cursors=pending,
            )
        except Exception:  # noqa: BLE001  fail closed
            refusal = Refusal("guard_error", "QUERY_REJECTED: it could not be checked.")
        if refusal is None:
            return None
        await guard.emit(
            "egress",
            refusal.rule,
            enforced=mode == "enforce",
            action="block",
            severity="medium",
            detail=f"{call.name} on {args.source}",
        )
        if mode != "enforce":
            return None
        ledger.calls_used += 1
        ledger.events.append(
            ToolEvent(
                tool=call.name,
                args_hash=_hash(call.name, {"raw": call.arguments}),
                source=args.source,
                status="egress_blocked",
                note=refusal.rule,
            )
        )
        return refusal.message

    async def execute(self, call: ToolCall, ledger: Ledger, ctx: AccessContext) -> str:
        started = time.monotonic()
        model = TOOL_ARGS.get(call.name)
        if model is None:
            return self._reject(
                ledger,
                call,
                "unknown_tool",
                f"UNKNOWN_TOOL: no tool named '{call.name}'.",
            )
        try:
            args = model.model_validate_json(call.arguments)
        except ValidationError as exc:
            msg = "; ".join(
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()
            )
            return self._reject(
                ledger, call, "invalid_arguments", f"INVALID_ARGUMENTS: {msg}"
            )

        try:
            source, prepared, clamp_note = self._prepare(args, ledger, ctx)
        except _Rejected as rej:
            return self._reject(ledger, call, rej.code, rej.text)

        key = _hash(call.name, {"source": source, **prepared})
        if key in ledger.seen_calls:
            ledger.events.append(
                ToolEvent(tool=call.name, args_hash=key, source=source, status="cached")
            )
            return "ALREADY_CALLED: an identical request was made earlier; its results are above."
        if ledger.calls_used >= self.limits.max_tool_calls:
            return self._reject(
                ledger,
                call,
                "budget_exhausted",
                "BUDGET_EXHAUSTED: no tool calls remain. Write your notes from what you have.",
            )
        ledger.calls_used += 1

        result = await self._invoke(call.name, source, prepared, ctx)
        text = await self._absorb(
            call, key, source, prepared, result, ledger, ctx, started, clamp_note
        )
        # A failed call may succeed on retry, so it is not served from cache.
        if result.coverage.status != "failed":
            ledger.seen_calls[key] = "done"
        return text

    # ---- internals -----------------------------------------------------------------

    def _prepare(
        self, args: BaseModel, ledger: Ledger, ctx: AccessContext
    ) -> tuple[str, dict[str, Any], str | None]:
        """Turn validated model arguments into a call the backend is willing to make."""
        readable = self.readable_sources(ctx)
        if isinstance(args, SearchRecordsArgs):
            if args.source not in readable:
                raise _Rejected(
                    "source_not_allowed",
                    f"SOURCE_NOT_AVAILABLE: '{args.source}' is not a source you can search. "
                    f"Available: {', '.join(readable) or 'none'}.",
                )
            lo, hi, note = _clamp_dates(args.date_from, args.date_to, ctx)
            return (
                args.source,
                {
                    "text": args.query.strip(),
                    "date_from": lo,
                    "date_to": hi,
                    "cursor": args.cursor,
                },
                note,
            )
        if isinstance(args, GetRecordArgs):
            rec = ledger.evidence.get(args.record_id)
            if rec is None or rec.source not in readable:
                raise _Rejected(
                    "unknown_id",
                    f"UNKNOWN_ID: '{args.record_id}' was not seen in this investigation. "
                    "Only ids from earlier results can be fetched.",
                )
            return rec.source, {"record_id": args.record_id}, None
        if isinstance(args, GetThreadArgs):
            source = ledger.known_thread_ids().get(args.thread_id)
            if source is None or source not in readable:
                raise _Rejected(
                    "unknown_id",
                    f"UNKNOWN_ID: thread '{args.thread_id}' was not seen in this investigation. "
                    "Only thread ids shown on earlier records can be fetched.",
                )
            return source, {"thread_id": args.thread_id}, None
        raise _Rejected("unknown_tool", "UNKNOWN_TOOL")

    async def _invoke(
        self, tool: str, source: str, prepared: dict[str, Any], ctx: AccessContext
    ) -> SearchResult:
        connector = self._connectors[source]
        try:
            async with asyncio.timeout(self.limits.timeout_s):
                if tool == "search_records":
                    return await connector.search(SearchQuery(**prepared), ctx)
                if tool == "get_record":
                    return await connector.get_record(prepared["record_id"], ctx)
                return await connector.get_thread(prepared["thread_id"], ctx)
        except TimeoutError:
            detail = f"Timed out after {self.limits.timeout_s:g}s."
        except Exception as exc:  # noqa: BLE001  a connector must never end the run
            detail = f"{type(exc).__name__}: {exc}"
        return SearchResult(
            coverage=SourceCoverage(source=source, status="failed", detail=detail)
        )

    async def _absorb(
        self,
        call: ToolCall,
        key: str,
        source: str,
        prepared: dict[str, Any],
        result: SearchResult,
        ledger: Ledger,
        ctx: AccessContext,
        started: float,
        clamp_note: str | None,
    ) -> str:
        notes: list[str] = [clamp_note] if clamp_note else []
        records = result.records
        # Defence in depth: connectors scope by case, the harness re-checks.
        scoped = [r for r in records if _in_scope(r, ctx)]
        if len(scoped) < len(records):
            notes.append(
                f"{len(records) - len(scoped)} record(s) outside the case scope were dropped."
            )
        if len(scoped) > self.limits.max_records_per_call:
            notes.append(
                f"Showing {self.limits.max_records_per_call} of {len(scoped)}; use a narrower query."
            )
            scoped = scoped[: self.limits.max_records_per_call]

        if self._guard is not None:
            guard = self._guard
            scoped = [await protect(r, guard) for r in scoped]
        status = result.coverage.status
        new = 0
        for rec in scoped:
            if rec.id not in ledger.evidence:
                new += 1
            ledger.evidence[rec.id] = rec

        # Coverage per source: fold the latest outcome of each distinct call.
        ledger.call_outcomes[key] = CallOutcome(
            source=source, status=status, detail=result.coverage.detail
        )
        ledger.coverage[source] = _fold_coverage(source, ledger.call_outcomes)
        self._track_cursor(
            ledger,
            source,
            prepared.get("text", ""),
            prepared.get("cursor"),
            result.next_cursor,
        )

        ledger.events.append(
            ToolEvent(
                tool=call.name,
                args_hash=key,
                source=source,
                status=status,
                records=len(scoped),
                new_records=new,
                duration_ms=int((time.monotonic() - started) * 1000),
                note=" ".join(notes) or None,
            )
        )

        lines = [
            _SENTINEL[status] if status not in ("searched",) or not scoped else "OK"
        ]
        if result.coverage.detail and status in (
            "failed",
            "partial",
            "permission_denied",
        ):
            lines.append(f"Detail: {result.coverage.detail}")
        if result.next_cursor:
            lines.append(f"More results available. Next cursor: {result.next_cursor}")
        lines += notes
        lines += [render_record(r, self.limits.excerpt_chars) for r in scoped]
        return "\n".join(lines)

    @staticmethod
    def _track_cursor(
        ledger: Ledger, source: str, query: str, used: str | None, nxt: str | None
    ) -> None:
        """Unfetched pages are kept as "query<US>cursor": a cursor only means
        something together with the query that produced it."""
        pending = ledger.pending_cursors.setdefault(source, [])
        if used and f"{query}\x1f{used}" in pending:
            pending.remove(f"{query}\x1f{used}")
        if nxt and f"{query}\x1f{nxt}" not in pending:
            pending.append(f"{query}\x1f{nxt}")
        if not pending:
            ledger.pending_cursors.pop(source, None)

    def _reject(self, ledger: Ledger, call: ToolCall, code: str, text: str) -> str:
        ledger.calls_used += 1 if code in ("invalid_arguments", "unknown_tool") else 0
        ledger.events.append(
            ToolEvent(
                tool=call.name,
                args_hash=_hash(call.name, {"raw": call.arguments}),
                status=code,
            )
        )
        return text

    def finalize_coverage(self, ledger: Ledger) -> list[SourceCoverage]:
        """Sources with unretrieved pages are `partial`, never `searched`."""
        out: list[SourceCoverage] = []
        for name, cov in sorted(ledger.coverage.items()):
            if ledger.pending_cursors.get(name) and cov.status in (
                "searched",
                "no_matches",
            ):
                cov = SourceCoverage(
                    source=name,
                    status="partial",
                    detail="More results exist that were not retrieved.",
                )
            out.append(cov)
        return out


class _Rejected(Exception):
    def __init__(self, code: str, text: str) -> None:
        super().__init__(text)
        self.code = code
        self.text = text


def _clamp_dates(
    lo: date | None, hi: date | None, ctx: AccessContext
) -> tuple[date | None, date | None, str | None]:
    """Keep model-requested dates inside the case window."""
    new_lo, new_hi = lo, hi
    if ctx.window_from and (lo is None or lo < ctx.window_from):
        new_lo = ctx.window_from
    if ctx.window_to and (hi is None or hi > ctx.window_to):
        new_hi = ctx.window_to
    note = None
    if (new_lo, new_hi) != (lo, hi) and (lo or hi):
        note = f"Date range was limited to the case window ({new_lo or '…'} to {new_hi or '…'})."
    return new_lo, new_hi, note


def _in_scope(rec: EvidenceRecord, ctx: AccessContext) -> bool:
    s = ctx.scope
    if s.customer_id and rec.customer_id and rec.customer_id != s.customer_id:
        return False
    return not (s.project_id and rec.project_id and rec.project_id != s.project_id)
