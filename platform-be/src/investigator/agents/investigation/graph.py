"""The Investigator: main orchestration graph with four subgraphs.

    intake → resolve_context → plan_investigation → retrieve_evidence ◄─────────────┐
                                    ▲                    [Retrieval subgraph]       │
                                    │                         ▼                      │
                                    │                 normalize_dedupe               │
                                    │                         ▼                      │
                                    │                  assess_evidence ── unsearched sources ─┘
                                    │                    │      └─ no evidence ─► finalize
                                    │         critical unknown
                                    │                    ▼
                                    └──────── request_clarification (human input)
                                                         │ enough evidence
                                                         ▼
                    analyze_evidence  [Analysis subgraph]
                                                         ▼
                    synthesize_findings ◄──────────── revise ────────────────┐
                                                         ▼                    │
                    validate_claims [Validation subgraph] ─ failed ─► repair_findings ─┐
                                    ▲                                                   │
                                    └───────────────────────────────────────────────────┘
                                                         │ passed
                                                         ▼
                    recommend_actions → human_review (Checkpoint A)
                         approved │            │ needs more evidence → reset → plan_investigation
                                  ▼
                    draft_response [Response subgraph] → human_approval (Checkpoint B)
                                  ▲   changes requested ───────┘        │ approved
                                                                        ▼
                                                            complete_investigation → END

Every other path ends at `finalize` (status `needs_review`, or `failed`). The
subgraphs are compiled separately and called from thin node wrappers; the main
state is the shared investigation record. Human checkpoints use `interrupt`, so a
checkpointer is required to run past them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from investigator.agents.investigation import routing
from investigator.agents.investigation.env import NodeEnv
from investigator.agents.investigation.nodes import evidence, findings, review, setup
from investigator.agents.investigation.state import InvestigationState
from investigator.agents.investigation.subgraphs.analysis import build_analysis_subgraph
from investigator.agents.investigation.subgraphs.response import build_response_subgraph
from investigator.agents.investigation.subgraphs.retrieval import (
    build_retrieval_subgraph,
)
from investigator.agents.investigation.subgraphs.validation import (
    build_validation_subgraph,
)
from investigator.connectors import SourceConnector
from investigator.guardrails import GuardRuntime
from investigator.llm import Llm, Route
from investigator.tools import AccessContext, HarnessLimits, ToolHarness


def recursion_limit(limits: HarnessLimits) -> int:
    """Generous for the main graph's loops; subgraphs count their own steps."""
    return 80


@dataclass
class Deps:
    llm: Llm
    # Empty until real connectors exist; coverage then reports nothing searched.
    connectors: list[SourceConnector] = field(default_factory=list)
    limits: HarnessLimits = field(default_factory=HarnessLimits)
    agent_route: Route = "fast"
    # None runs without guardrails (tests that do not exercise them).
    guard: GuardRuntime | None = None
    # Used only when a run supplies no AccessContext (e.g. LangGraph Studio).
    default_access: AccessContext | None = None
    now: Callable[[], datetime] = lambda: datetime.now(UTC)


def build_graph(deps: Deps, checkpointer: Any | None = None) -> Any:
    env = NodeEnv(
        llm=deps.llm,
        harness=ToolHarness(
            {c.name: c for c in deps.connectors}, deps.limits, deps.guard
        ),
        agent_route=deps.agent_route,
        default_access=deps.default_access,
        now=deps.now,
    )
    retrieval = build_retrieval_subgraph(env)
    analysis = build_analysis_subgraph(env)
    validation = build_validation_subgraph()
    response = build_response_subgraph(env)

    b = StateGraph(InvestigationState)
    # 1-3  setup
    b.add_node("intake", setup.intake)
    b.add_node("resolve_context", partial(setup.resolve_context, env=env))
    b.add_node("plan_investigation", partial(setup.plan_investigation, env=env))
    # 4-6  retrieve, normalize, assess
    b.add_node(
        "retrieve_evidence", partial(evidence.retrieve_evidence, env=env, sub=retrieval)
    )
    b.add_node("normalize_dedupe", evidence.normalize_dedupe)
    b.add_node("assess_evidence", partial(evidence.assess_evidence, env=env))
    b.add_node("request_clarification", evidence.request_clarification)
    # 7-10 analysis
    b.add_node("analyze_evidence", partial(findings.analyze_evidence, sub=analysis))
    # 11-13 synthesize, validate, repair
    b.add_node("synthesize_findings", partial(findings.synthesize_findings, env=env))
    b.add_node("verify_claims", partial(findings.verify_claims, env=env))
    b.add_node("validate_claims", partial(findings.validate_claims, sub=validation))
    b.add_node("repair_findings", findings.repair_findings)
    # 14-19 actions, review, response, approval, completion
    b.add_node("recommend_actions", partial(findings.recommend_actions, env=env))
    b.add_node("human_review", review.human_review)
    b.add_node("reset_for_more_evidence", review.reset_for_more_evidence)
    b.add_node("draft_response", partial(review.draft_response, sub=response))
    b.add_node("human_approval", review.human_approval)
    b.add_node(
        "complete_investigation", partial(review.complete_investigation, env=env)
    )
    b.add_node("finalize", partial(review.finalize, env=env))

    b.add_edge(START, "intake")
    b.add_conditional_edges(
        "intake",
        partial(routing.route_after_intake, env=env),
        {"resolve_context": "resolve_context", "finalize": "finalize"},
    )
    b.add_conditional_edges(
        "resolve_context",
        routing.route_after_resolve,
        {
            "plan_investigation": "plan_investigation",
            "request_clarification": "request_clarification",
        },
    )
    b.add_edge("plan_investigation", "retrieve_evidence")
    b.add_conditional_edges(
        "retrieve_evidence",
        routing.failed_or("normalize_dedupe"),
        {"normalize_dedupe": "normalize_dedupe", "finalize": "finalize"},
    )
    b.add_edge("normalize_dedupe", "assess_evidence")
    b.add_conditional_edges(
        "assess_evidence",
        partial(routing.route_after_assess, env=env),
        {
            "retrieve_evidence": "retrieve_evidence",
            "request_clarification": "request_clarification",
            "analyze_evidence": "analyze_evidence",
            "finalize": "finalize",
        },
    )
    b.add_edge("request_clarification", "plan_investigation")
    b.add_conditional_edges(
        "analyze_evidence",
        routing.failed_or("synthesize_findings"),
        {"synthesize_findings": "synthesize_findings", "finalize": "finalize"},
    )
    b.add_conditional_edges(
        "synthesize_findings",
        routing.failed_or("verify_claims"),
        {"verify_claims": "verify_claims", "finalize": "finalize"},
    )
    b.add_edge("verify_claims", "validate_claims")
    b.add_conditional_edges(
        "validate_claims",
        partial(routing.route_after_validation, env=env),
        {
            "repair_findings": "repair_findings",
            "recommend_actions": "recommend_actions",
        },
    )
    b.add_edge("repair_findings", "validate_claims")
    b.add_conditional_edges(
        "recommend_actions",
        routing.failed_or("human_review"),
        {"human_review": "human_review", "finalize": "finalize"},
    )
    b.add_conditional_edges(
        "human_review",
        routing.route_after_review,
        {
            "draft_response": "draft_response",
            "reset_for_more_evidence": "reset_for_more_evidence",
            "synthesize_findings": "synthesize_findings",
            "finalize": "finalize",
        },
    )
    b.add_edge("reset_for_more_evidence", "plan_investigation")
    b.add_conditional_edges(
        "draft_response",
        routing.route_after_draft,
        {"human_approval": "human_approval", "finalize": "finalize"},
    )
    b.add_conditional_edges(
        "human_approval",
        partial(routing.route_after_approval, env=env),
        {
            "complete_investigation": "complete_investigation",
            "draft_response": "draft_response",
            "finalize": "finalize",
        },
    )
    b.add_edge("complete_investigation", END)
    b.add_edge("finalize", END)
    return b.compile(checkpointer=checkpointer)
