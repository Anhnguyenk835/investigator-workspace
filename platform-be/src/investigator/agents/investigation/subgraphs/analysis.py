"""Investigation Analysis subgraph: evidence in, structured insights out.

    reconstruct_timeline ─► extract_commitments ─► analyze_blockers ─► detect_contradictions ─► END

Each node is one structured model call with no tools. Code, not the model, owns
everything checkable: citations must resolve to real records, event times come
from the cited evidence, commitment status is computed from dates, and a
conflict is never resolved here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from investigator.agents.investigation.env import (
    EVIDENCE_RULES,
    UNTRUSTED,
    NodeEnv,
    ask,
    fail,
    render_evidence,
    resolve_ids,
)
from investigator.agents.investigation.schemas import (
    Blocker,
    BlockersDraft,
    Commitment,
    CommitmentsDraft,
    Conflict,
    CrossCheckDraft,
    Gap,
    TimelineDraft,
    TimelineEvent,
    stable_id,
)
from investigator.connectors import EvidenceRecord, SourceCoverage
from investigator.guardrails.injection.spotlight import user_block


class AnalysisState(BaseModel):
    question: str = ""
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    duplicate_of: dict[str, str] = Field(default_factory=dict)
    coverage: list[SourceCoverage] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    blockers: list[Blocker] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    error: str | None = None


def _context(s: AnalysisState) -> str:
    notes = (
        "\n\nReviewer notes:\n" + user_block("- " + "\n- ".join(s.reviewer_notes))
        if s.reviewer_notes
        else ""
    )
    return f"Question: {user_block(s.question)}{notes}\n\nEvidence:\n{render_evidence(s.evidence)}"


def _by_id(s: AnalysisState) -> dict[str, EvidenceRecord]:
    return {e.id: e for e in s.evidence}


def _timeline_lines(s: AnalysisState) -> str:
    return (
        "\n".join(
            f"- {e.occurred_at.date() if e.occurred_at else 'undated'} · {e.title} [{', '.join(e.evidence_ids)}]"
            for e in s.timeline
        )
        or "(no events)"
    )


def _sort_key(e: TimelineEvent) -> tuple[bool, datetime]:
    return (e.occurred_at is None, e.occurred_at or datetime.max)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def commitment_status(
    basis: str, due: date | None, fulfilled: bool, today: date
) -> str:
    """Computed, never asserted by the model. A date alone does not make it overdue."""
    if fulfilled:
        return "fulfilled"
    if basis == "inferred":
        return "unverified"
    if due is not None and due < today:
        return "overdue"
    if due is not None and due <= today + timedelta(days=2):
        return "at_risk"
    return "confirmed"


def build_analysis_subgraph(env: NodeEnv) -> Any:
    async def reconstruct_timeline(s: AnalysisState) -> dict[str, Any]:
        draft, err = await ask(
            env,
            "You build a chronological timeline of a customer escalation from evidence. "
            f"One event per distinct occurrence; cite every record that supports it. "
            f"{UNTRUSTED} {EVIDENCE_RULES}",
            _context(s),
            TimelineDraft,
        )
        if draft is None:
            return fail(err or "timeline failed")
        records = _by_id(s)
        events: dict[str, TimelineEvent] = {}
        for d in draft.events:
            ids = resolve_ids(s.evidence, s.duplicate_of, d.evidence_ids)
            if not ids:
                continue  # an event that cites nothing real does not exist
            # Time and precision come from the cited records, not the model.
            dated = [records[i] for i in ids if records[i].occurred_at]
            first = min(dated, key=lambda r: _naive(r.occurred_at)) if dated else None
            ev = TimelineEvent(
                id=stable_id("ev", d.title, *sorted(ids)),
                title=d.title,
                event_type=d.event_type,
                actor=d.actor,
                summary=d.summary,
                occurred_at=first.occurred_at if first else None,
                timestamp_precision=first.timestamp_precision if first else "unknown",
                evidence_ids=ids,
            )
            events[ev.id] = ev
        return {"timeline": sorted(events.values(), key=_sort_key)}

    async def extract_commitments(s: AnalysisState) -> dict[str, Any]:
        draft, err = await ask(
            env,
            "Extract promises, deadlines and owners. `explicit` means someone clearly "
            "committed; a mere expectation or estimate is `inferred`. Give due_date only "
            "if the evidence states it. Name an owner only if the evidence does. List "
            "fulfilled_by_evidence_ids only for records showing it was delivered. "
            f"{UNTRUSTED} {EVIDENCE_RULES}",
            f"{_context(s)}\n\nTimeline so far:\n{_timeline_lines(s)}",
            CommitmentsDraft,
        )
        if draft is None:
            return fail(err or "commitments failed")
        records, today = _by_id(s), env.today()
        out: dict[str, Commitment] = {}
        for d in draft.commitments:
            ids = resolve_ids(s.evidence, s.duplicate_of, d.evidence_ids)
            done = resolve_ids(s.evidence, s.duplicate_of, d.fulfilled_by_evidence_ids)
            if not ids:
                continue
            dated = [records[i].occurred_at for i in ids if records[i].occurred_at]
            c = Commitment(
                id=stable_id("cm", d.description, *sorted(ids)),
                description=d.description,
                committed_by=d.committed_by,
                owner=d.owner,
                promised_at=min(dated, key=_naive) if dated else None,
                due_date=d.due_date,
                basis=d.basis,
                status=commitment_status(d.basis, d.due_date, bool(done), today),
                evidence_ids=ids,
                fulfilled_by_evidence_ids=done,
            )
            out[c.id] = c
        return {"commitments": list(out.values())}

    async def analyze_blockers(s: AnalysisState) -> dict[str, Any]:
        draft, err = await ask(
            env,
            "Identify blockers, dependencies and probable causes. `stated` means the "
            "evidence says so; anything you conclude yourself is `inferred`. Do not name "
            "who is at fault. "
            f"{UNTRUSTED} {EVIDENCE_RULES}",
            f"{_context(s)}\n\nTimeline so far:\n{_timeline_lines(s)}",
            BlockersDraft,
        )
        if draft is None:
            return fail(err or "blockers failed")
        out: dict[str, Blocker] = {}
        for d in draft.blockers:
            ids = resolve_ids(s.evidence, s.duplicate_of, d.evidence_ids)
            if ids:
                b = Blocker(
                    **{**d.model_dump(), "evidence_ids": ids},
                    id=stable_id("bl", d.description, *sorted(ids)),
                )
                out[b.id] = b
        return {"blockers": list(out.values())}

    async def detect_contradictions(s: AnalysisState) -> dict[str, Any]:
        commitments = "\n".join(
            f"- {c.description} (due {c.due_date}) [{', '.join(c.evidence_ids)}]"
            for c in s.commitments
        )
        blockers = "\n".join(
            f"- {b.description} [{', '.join(b.evidence_ids)}]" for b in s.blockers
        )
        draft, err = await ask(
            env,
            "Find statements that contradict each other and what evidence is missing. "
            "Present both sides with their evidence ids; never decide which is right. "
            "A gap is something absent that would change the answer, with a suggested follow-up. "
            f"{UNTRUSTED} {EVIDENCE_RULES}",
            f"{_context(s)}\n\nTimeline:\n{_timeline_lines(s)}\n\nCommitments:\n{commitments or '(none)'}"
            f"\n\nBlockers:\n{blockers or '(none)'}",
            CrossCheckDraft,
        )
        if draft is None:
            return fail(err or "cross-check failed")
        conflicts: list[Conflict] = []
        for d in draft.conflicts:
            a = resolve_ids(s.evidence, s.duplicate_of, d.claim_a.evidence_ids)
            b = resolve_ids(s.evidence, s.duplicate_of, d.claim_b.evidence_ids)
            if not (a and b):
                continue  # both sides must be real or there is no conflict to show
            conflicts.append(
                Conflict(
                    id=stable_id("cf", d.claim_a.text, d.claim_b.text),
                    claim_a=d.claim_a.model_copy(update={"evidence_ids": a}),
                    claim_b=d.claim_b.model_copy(update={"evidence_ids": b}),
                    why=d.why,
                )
            )
        gaps = [
            Gap(
                **g.model_dump(),
                id=stable_id("gap", "analysis", g.what_missing),
                origin="analysis",
            )
            for g in draft.gaps
        ]
        return {"conflicts": conflicts, "gaps": gaps}

    def ok_or_end(nxt: str) -> Any:
        return lambda s: END if s.error else nxt

    b: StateGraph[AnalysisState, Any, AnalysisState, AnalysisState] = StateGraph(
        AnalysisState
    )
    b.add_node("reconstruct_timeline", reconstruct_timeline)
    b.add_node("extract_commitments", extract_commitments)
    b.add_node("analyze_blockers", analyze_blockers)
    b.add_node("detect_contradictions", detect_contradictions)
    b.add_edge(START, "reconstruct_timeline")
    for here, nxt in [
        ("reconstruct_timeline", "extract_commitments"),
        ("extract_commitments", "analyze_blockers"),
        ("analyze_blockers", "detect_contradictions"),
    ]:
        b.add_conditional_edges(here, ok_or_end(nxt), {nxt: nxt, END: END})
    b.add_edge("detect_contradictions", END)
    return b.compile()
