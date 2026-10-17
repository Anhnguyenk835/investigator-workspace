"""Main graph, steps 15-19: human review, response (subgraph), approval, completion."""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from investigator.agents.investigation.env import (
    NodeEnv,
    as_model,
    effective_access,
    fail,
    ledger_of,
)
from investigator.agents.investigation.schemas import DraftResume, ReviewResume
from investigator.agents.investigation.state import InvestigationState
from investigator.agents.investigation.subgraphs.response import ResponseState


def human_review(state: InvestigationState) -> dict[str, Any]:
    """Checkpoint A. The graph stops here until a person decides."""
    decision = ReviewResume.model_validate(
        interrupt(
            {
                "kind": "review",
                "findings": len(state.findings),
                "conflicts": len(state.conflicts),
                "gaps": len(state.gaps),
                "actions": len(state.actions),
                "validation_passed": state.validation.passed,
            }
        )
    )
    notes = (
        [*state.reviewer_notes, decision.note]
        if decision.note
        else state.reviewer_notes
    )
    return {"review_decision": decision.decision, "reviewer_notes": notes}


def reset_for_more_evidence(state: InvestigationState) -> dict[str, Any]:
    """The reviewer asked for more evidence: a fresh search budget, same cache."""
    return {
        "calls_used": 0,
        "retrieval_loops": 0,
        "review_decision": "pending",
        "clarification_asked": False,
    }


async def draft_response(state: InvestigationState, *, sub: Any) -> dict[str, Any]:
    verified = [f for f in state.findings if f.status == "verified"]
    if not verified:
        # Never write to the customer from claims nobody has verified.
        return {"draft_status": "not_possible", "draft": "", "draft_warnings": []}
    feedback = (
        state.reviewer_notes[-1]
        if state.draft_status == "changes_requested" and state.reviewer_notes
        else ""
    )
    out = as_model(
        await sub.ainvoke(
            ResponseState(
                question=state.question,
                findings=verified,
                evidence=state.evidence,
                reviewer_notes=state.reviewer_notes,
                feedback=feedback,
            )
        ),
        ResponseState,
    )
    if out.error:
        return fail(out.error)
    return {
        "draft": out.draft,
        "draft_warnings": out.warnings,
        "draft_status": "drafted",
    }


def human_approval(state: InvestigationState) -> dict[str, Any]:
    """Checkpoint B. Nothing leaves the system; a person approves or asks for changes."""
    answer = DraftResume.model_validate(
        interrupt(
            {
                "kind": "draft_approval",
                "draft": state.draft,
                "warnings": state.draft_warnings,
            }
        )
    )
    update: dict[str, Any] = {
        "draft": answer.draft if answer.draft is not None else state.draft,
        "draft_rounds": state.draft_rounds + 1,
        "draft_status": "approved" if answer.approved else "changes_requested",
    }
    if answer.note:
        update["reviewer_notes"] = [*state.reviewer_notes, answer.note]
    return update


def complete_investigation(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv
) -> dict[str, Any]:
    """Reached only after a person approved the draft; records who and when."""
    conf = config.get("configurable") or {}
    access = conf.get("access") or env.default_access
    return {
        "status": "resolved",
        # The name the person gave (not a login), else the account the run used.
        "resolved_by": conf.get("actor") or getattr(access, "user_id", None),
        "resolved_at": env.now(),
        "coverage": env.harness.finalize_coverage(ledger_of(state)),
    }


def finalize(
    state: InvestigationState, config: RunnableConfig, *, env: NodeEnv
) -> dict[str, Any]:
    """Any other end: hand the case to a person, with coverage stated honestly,
    including connected sources this user was not allowed to read."""
    ledger = ledger_of(state)
    env.harness.record_denied_sources(
        ledger, effective_access(state.context, config, env)
    )
    update: dict[str, Any] = {"coverage": env.harness.finalize_coverage(ledger)}
    if state.status != "failed":
        update["status"] = "needs_review"
    return update
