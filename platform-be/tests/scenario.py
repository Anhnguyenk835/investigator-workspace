"""A small coherent case used across graph tests. Test data only; never in product code."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any, cast

from langgraph.checkpoint.memory import MemorySaver

from investigator.agents.investigation import Deps, InvestigationState, build_graph
from investigator.agents.investigation.schemas import (
    ActionDraft,
    ActionsDraft,
    BlockersDraft,
    CommitmentDraft,
    CommitmentsDraft,
    CrossCheckDraft,
    DraftPlan,
    FindingDraft,
    GapDraft,
    SupportDraft,
    SupportItemDraft,
    SynthesisDraft,
    TimelineDraft,
    TimelineEventDraft,
    stable_id,
)
from tests.fakes import FakeConnector, ScriptedLlm, access, rec, result

NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
CLAIM_REQUEST = "Client asked for the form update"
CLAIM_DEADLINE = "Team expected delivery on Friday Oct 16"
FID_REQUEST = stable_id("fd", CLAIM_REQUEST)

E1 = dict(
    occurred_at=datetime(2026, 10, 12, 9, tzinfo=UTC),
    timestamp_precision="exact",
    author="Client",
    excerpt="Please update the form before Oct 20.",
    thread_id="t1",
    project_id="p1",
)
C1 = dict(
    occurred_at=datetime(2026, 10, 13, 15, tzinfo=UTC),
    timestamp_precision="exact",
    author="Sam",
    excerpt="We expect it ready by Friday Oct 16.",
    project_id="p1",
)


def connectors() -> list[FakeConnector]:
    e1, c1 = rec("e1", "email", **E1), rec("c1", "chat", **C1)
    return [
        FakeConnector("email", search=lambda q: result("email", "searched", [e1])),
        FakeConnector("chat", search=lambda q: result("chat", "searched", [c1])),
    ]


def supports_everything(messages: Any) -> SupportDraft:
    """A model that finds every cited record to support its claim, quoting its first words."""
    text = str(messages[-1].content)
    checks = []
    for rid, body in re.findall(
        r'<record id="([^"]+)"[^>]*>\n(.*?)\n</record>', text, flags=re.DOTALL
    ):
        quote = body.strip().splitlines()[0][:40] if body.strip() else ""
        checks.append(
            SupportItemDraft(evidence_id=rid, verdict="supported", quote=quote)
        )
    return SupportDraft(checks=checks)


def structured(overrides: dict[type, Any] | None = None) -> dict[type, Any]:
    base: dict[type, Any] = {
        TimelineDraft: TimelineDraft(
            events=[
                TimelineEventDraft(
                    title="Request received",
                    event_type="customer_request",
                    actor="Client",
                    summary="Client asks for the update.",
                    evidence_ids=["e1"],
                ),
                TimelineEventDraft(
                    title="Delivery expected",
                    event_type="commitment",
                    actor="Sam",
                    summary="Team expects Friday.",
                    evidence_ids=["c1"],
                ),
            ]
        ),
        CommitmentsDraft: CommitmentsDraft(
            commitments=[
                CommitmentDraft(
                    description="Form ready by Friday",
                    committed_by="Sam",
                    owner="Sam",
                    due_date=date(2026, 10, 16),
                    basis="explicit",
                    evidence_ids=["c1"],
                )
            ]
        ),
        BlockersDraft: BlockersDraft(),
        CrossCheckDraft: CrossCheckDraft(
            gaps=[
                GapDraft(
                    what_missing="Who confirmed the final deadline",
                    why_it_matters="Decides what was promised",
                    resolving_evidence="The confirming email",
                    follow_up="Ask the owner",
                )
            ]
        ),
        SynthesisDraft: SynthesisDraft(
            summary="Request made; delivery expectation unconfirmed.",
            findings=[
                FindingDraft(
                    title="Request",
                    claim=CLAIM_REQUEST,
                    status="verified",
                    supporting_evidence_ids=["e1"],
                    reasoning_type="direct",
                ),
                FindingDraft(
                    title="Deadline",
                    claim=CLAIM_DEADLINE,
                    status="needs_verification",
                    supporting_evidence_ids=["c1"],
                    reasoning_type="direct",
                ),
                FindingDraft(
                    title="Made up",
                    claim="The ticket was closed",
                    status="verified",
                    supporting_evidence_ids=["zzz"],
                    reasoning_type="direct",
                ),
                FindingDraft(
                    title="Fault",
                    claim="Sam is at fault for the delay",
                    status="needs_verification",
                    supporting_evidence_ids=["c1"],
                    reasoning_type="inference",
                ),
            ],
        ),
        ActionsDraft: ActionsDraft(
            actions=[
                ActionDraft(
                    title="Confirm status with Digitization",
                    rationale="Deadline unconfirmed",
                    owner="Sam",
                    related_finding_ids=[FID_REQUEST],
                    evidence_ids=["c1"],
                ),
                ActionDraft(title="Unanchored idea", rationale="No support"),
            ]
        ),
        DraftPlan: DraftPlan(
            text="Hello, we received your request and are confirming the status."
        ),
        SupportDraft: supports_everything,
    }
    base.update(overrides or {})
    return base


def make_graph(
    llm: ScriptedLlm, conns: list[FakeConnector] | None = None, **deps: Any
) -> Any:
    # Fakes stand in for the real client and connectors; Deps is typed on the real ones.
    fakes: Any = Deps(
        llm=cast(Any, llm),
        connectors=cast(Any, conns if conns is not None else connectors()),
        now=lambda: NOW,
        **deps,
    )
    return build_graph(fakes, MemorySaver())


async def advance(
    graph: Any, payload: Any, thread: str = "t", *sources: str, **access_kw: Any
) -> tuple[InvestigationState, dict[str, Any] | None]:
    """Run or resume until the graph ends or pauses; return state and the pending question."""
    config = {
        "configurable": {
            "thread_id": thread,
            "access": access(*(sources or ("email", "chat")), **access_kw),
        },
        "recursion_limit": 80,
    }
    await graph.ainvoke(payload, config=config)
    snap = await graph.aget_state(config)
    pending = [i.value for t in snap.tasks for i in t.interrupts]
    return InvestigationState(**snap.values), (pending[0] if pending else None)
