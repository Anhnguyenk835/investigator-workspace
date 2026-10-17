"""Routing between main-graph nodes. Decisions use state, never a model's opinion."""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from investigator.agents.investigation.env import NodeEnv, effective_access
from investigator.agents.investigation.state import InvestigationState


def failed_or(nxt: str):  # type: ignore[no-untyped-def]
    """Route to `finalize` if the run has failed, else to `nxt`."""

    def route(state: InvestigationState) -> str:
        return "finalize" if state.status == "failed" else nxt

    return route


def route_after_intake(
    state: InvestigationState, config: RunnableConfig, env: NodeEnv
) -> str:
    """With no source this user can read there is nothing to search, so no model is called."""
    if state.status == "failed":
        return "finalize"
    ctx = effective_access(state.context, config, env)
    return "resolve_context" if env.harness.readable_sources(ctx) else "finalize"


def route_after_resolve(state: InvestigationState) -> str:
    """A question that names several customers or projects is put to the person first."""
    if state.clarification_needed and not state.clarification_asked:
        return "request_clarification"
    return "plan_investigation"


def route_after_assess(state: InvestigationState, env: NodeEnv) -> str:
    """Key routing logic: unsearched sources → retrieve more; critical unknown →
    ask the user; no evidence → stop; otherwise analyse."""
    if state.status == "failed":
        return "finalize"
    if state.retryable_sources and state.retrieval_loops <= env.max_retrieval_loops:
        return "retrieve_evidence"
    if state.clarification_needed:
        return "request_clarification"
    if not state.evidence:
        return "finalize"
    return "analyze_evidence"


def route_after_validation(state: InvestigationState, env: NodeEnv) -> str:
    if state.validation.passed:
        return "recommend_actions"
    # Bounded: after the last repair the reviewer sees what is still flagged.
    if state.validation_rounds < env.max_validation_rounds:
        return "repair_findings"
    return "recommend_actions"


def route_after_review(state: InvestigationState) -> str:
    return {
        "approved": "draft_response",
        "needs_more_evidence": "reset_for_more_evidence",
        "revise": "synthesize_findings",
    }.get(state.review_decision, "finalize")


def route_after_draft(state: InvestigationState) -> str:
    if state.status == "failed" or state.draft_status == "not_possible":
        return "finalize"
    return "human_approval"


def route_after_approval(state: InvestigationState, env: NodeEnv) -> str:
    if state.draft_status == "approved":
        return "complete_investigation"
    if state.draft_rounds < env.max_draft_rounds:
        return "draft_response"
    return "finalize"
