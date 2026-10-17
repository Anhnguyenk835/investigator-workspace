"""Main graph, steps 4-6: retrieve (subgraph), normalize, decide if evidence is enough."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from investigator.agents.investigation.env import (
    NodeEnv,
    as_model,
    directory_of,
    effective_access,
    fail,
    ledger_of,
    ledger_update,
)
from investigator.agents.investigation.schemas import (
    ClarificationQuestion,
    ClarificationResume,
    Gap,
    stable_id,
)
from investigator.agents.investigation.state import InvestigationState
from investigator.agents.investigation.subgraphs.retrieval import RetrievalState
from investigator.connectors import EvidenceRecord
from investigator.directory import SourceFilter

NOT_FULLY_SEARCHED = {"failed", "partial", "permission_denied", "not_connected"}
RETRYABLE = {"failed", "partial"}  # denied and not-connected will not change on retry


async def retrieve_evidence(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv, sub: Any
) -> dict[str, Any]:
    out = as_model(
        await sub.ainvoke(
            RetrievalState(
                question=state.question,
                queries=state.plan.queries,
                context=state.context,
                evidence=state.evidence,
                coverage=state.coverage,
                seen_calls=state.seen_calls,
                pending_cursors=state.pending_cursors,
                call_outcomes=state.call_outcomes,
                tool_events=state.tool_events,
                calls_used=state.calls_used,
                expanded_threads=state.expanded_threads,
            ),
            config,
        ),
        RetrievalState,
    )
    if out.error:
        return {**ledger_update(ledger_of(out)), **fail(out.error)}
    notes = "\n".join(n for n in [state.search_notes, out.search_notes] if n) or None
    return {
        **ledger_update(ledger_of(out)),
        "expanded_threads": out.expanded_threads,
        "search_notes": notes,
        "retrieval_loops": state.retrieval_loops + 1,
    }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def content_hash(rec: EvidenceRecord) -> str:
    return hashlib.sha1(
        f"{_norm(rec.excerpt)}|{_norm(rec.author or '')}".encode()
    ).hexdigest()[:16]


def _naive(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.max
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def normalize_dedupe(state: InvestigationState) -> dict[str, Any]:
    """Same content from two ids (a forward, a cross-post) is one record; the earliest is kept
    and later citations of the other id are mapped onto it."""
    kept: dict[str, EvidenceRecord] = {}
    duplicate_of = dict(state.duplicate_of)
    for rec in sorted(state.evidence, key=lambda r: (_naive(r.occurred_at), r.id)):
        h = content_hash(rec)
        rec = rec.model_copy(update={"content_hash": h})
        if h in kept:
            duplicate_of[rec.id] = kept[h].id
        else:
            kept[h] = rec
    return {"evidence": list(kept.values()), "duplicate_of": duplicate_of}


def assess_evidence(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv
) -> dict[str, Any]:
    """Coverage, quality, ambiguity. Facts about the retrieval; no model involved."""
    ctx = effective_access(state.context, config, env)
    ledger = ledger_of(state)
    coverage = env.harness.finalize_coverage(ledger)
    by_source = {c.source: c for c in coverage}
    retryable = [
        s
        for s in env.harness.readable_sources(ctx)
        if s not in by_source or by_source[s].status in RETRYABLE
    ]

    gaps = [g for g in state.gaps if g.origin == "analysis"]
    for c in coverage:
        if c.status in NOT_FULLY_SEARCHED:
            gaps.append(
                Gap(
                    id=stable_id("gap", "coverage", c.source, c.status),
                    what_missing=f"{c.source} was not fully searched ({c.status}).",
                    why_it_matters="Records there could change the conclusion.",
                    resolving_evidence=f"Records from {c.source}.",
                    follow_up="Retry the search, fix the connection or permission, or ask the owner.",
                    origin="coverage",
                )
            )
    undated = sum(1 for e in state.evidence if e.occurred_at is None)
    if undated:
        gaps.append(
            Gap(
                id=stable_id("gap", "quality", "undated"),
                what_missing=f"{undated} record(s) have no timestamp.",
                why_it_matters="Their place in the sequence cannot be established.",
                resolving_evidence="The original records with dates.",
                follow_up="Open the source records and confirm when they were sent.",
                origin="quality",
            )
        )

    questions: list[ClarificationQuestion] = []
    if not state.clarification_asked:
        for key, label in (("project_id", "project"), ("customer_id", "customer")):
            if getattr(state.context, key) is None:
                options = sorted({v for e in state.evidence if (v := getattr(e, key))})
                if len(options) > 1:
                    directory = directory_of(config)
                    lookup = (
                        (
                            directory.project
                            if key == "project_id"
                            else directory.customer
                        )
                        if directory
                        else None
                    )
                    names = {
                        o: found.name
                        for o in options
                        if lookup and (found := lookup(o))
                    }
                    questions.append(
                        ClarificationQuestion(
                            key=key,  # type: ignore[arg-type]
                            question=f"Records mention several {label}s. Which one is this about?",
                            options=options,
                            labels=names,
                        )
                    )
    return {
        "coverage": coverage,
        "gaps": gaps,
        "retryable_sources": retryable,
        "clarification_needed": questions,
    }


# Which SourceFilter list holds what a person picks in each source.
SCOPE_FIELD = {
    "slack": "channels",
    "jira": "jira_projects",
    "gmail": "gmail_labels",
    "confluence": "confluence_spaces",
}


def _clean_ids(ids: list[str]) -> list[str]:
    return sorted({i.strip() for i in ids if i.strip()})


def request_clarification(state: InvestigationState) -> dict[str, Any]:
    """Pause for a person. On resume the answer narrows the case and the search restarts."""
    answer = ClarificationResume.model_validate(
        interrupt(
            {
                "kind": "clarification",
                "questions": [q.model_dump() for q in state.clarification_needed],
            }
        )
    )
    chosen = dict(state.context.source_filters)
    for source, ids in answer.scope.items():
        field = SCOPE_FIELD.get(source)
        if field is not None:
            chosen[source] = SourceFilter(**{field: _clean_ids(ids)})
    ctx = state.context.model_copy(
        update={
            "project_id": answer.project_id or state.context.project_id,
            "customer_id": answer.customer_id or state.context.customer_id,
            "source_filters": chosen,
        }
    )

    def in_scope(e: EvidenceRecord) -> bool:
        return (not ctx.project_id or e.project_id in (None, ctx.project_id)) and (
            not ctx.customer_id or e.customer_id in (None, ctx.customer_id)
        )

    notes = (
        [*state.reviewer_notes, answer.note] if answer.note else state.reviewer_notes
    )
    return {
        "context": ctx,
        "evidence": [e for e in state.evidence if in_scope(e)],
        "clarification_needed": [],
        "clarification_asked": True,
        "reviewer_notes": notes,
        # The scope changed, so earlier results and budget no longer apply.
        "seen_calls": {},
        "call_outcomes": {},
        "pending_cursors": {},
        "calls_used": 0,
        "retrieval_loops": 0,
    }
