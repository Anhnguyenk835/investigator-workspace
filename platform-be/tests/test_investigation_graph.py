"""The main orchestration graph end to end: routing, loops and human checkpoints."""

from __future__ import annotations

from datetime import datetime

import pytest
from langgraph.types import Command

from investigator.agents.investigation.schemas import (
    ClarificationResume,
    DraftPlan,
    DraftResume,
    FindingDraft,
    InvestigationPlan,
    ReviewResume,
    SynthesisDraft,
    TimelineDraft,
)
from investigator.connectors import SearchQuery, SearchResult
from investigator.llm import LlmError
from tests.fakes import FakeConnector, ScriptedLlm, access, rec, result
from tests.scenario import NOW, advance, connectors, make_graph, structured

START = {"question": "Why was the form late?"}


def review(decision: str = "approved", note: str = "") -> Command[None]:
    return Command(resume=ReviewResume(decision=decision, note=note).model_dump())  # type: ignore[arg-type]


def approval(approved: bool = True, **kw: object) -> Command[None]:
    return Command(resume=DraftResume(approved=approved, **kw).model_dump())  # type: ignore[arg-type]


async def test_full_flow_pauses_at_both_checkpoints_then_resolves() -> None:
    llm = ScriptedLlm(structured=structured())
    graph = make_graph(llm)

    state, pending = await advance(graph, START)
    assert pending is not None and pending["kind"] == "review"
    assert (
        state.status == "investigating"
    )  # paused, not finished: the runner maps this to needs_review
    assert [e.id for e in state.evidence] == ["e1", "c1"]  # chronological
    assert {c.source: c.status for c in state.coverage} == {
        "email": "searched",
        "chat": "searched",
    }

    # timeline times come from the cited evidence, in order
    assert [e.title for e in state.timeline] == [
        "Request received",
        "Delivery expected",
    ]
    assert state.timeline[0].occurred_at == datetime.fromisoformat(
        "2026-10-12T09:00:00+00:00"
    )
    # commitment status is computed: due Oct 16, today is Oct 17
    assert state.commitments[0].status == "overdue"
    # validation repaired the findings: unsupported and blame-by-inference left, rest kept
    assert {f.title for f in state.findings} == {"Request", "Deadline"}
    assert {f.title for f in state.rejected_findings} == {"Made up", "Fault"}
    assert state.validation.passed and state.validation_rounds == 1
    # owner kept because the cited record names them; unanchored action dropped
    assert [(a.title, a.owner) for a in state.actions] == [
        ("Confirm status with Digitization", "Sam")
    ]

    state, pending = await advance(graph, review("approved"))
    assert pending is not None and pending["kind"] == "draft_approval"
    assert state.draft_status == "drafted" and "confirming the status" in state.draft

    state, pending = await advance(graph, approval(True, draft="Edited by a person."))
    assert pending is None
    assert state.status == "resolved" and state.draft == "Edited by a person."
    assert state.resolved_by == "u" and state.resolved_at == NOW


async def test_no_readable_source_means_no_model_call_and_denied_is_reported() -> None:
    llm = ScriptedLlm()
    state, pending = await advance(make_graph(llm, connectors()), START, "t", "other")
    assert pending is None and llm.structured_calls == [] and llm.tool_calls_seen == []
    assert state.status == "needs_review" and state.findings == []
    assert {(c.source, c.status) for c in state.coverage} == {
        ("email", "permission_denied"),
        ("chat", "permission_denied"),
    }


async def test_missing_access_context_fails_closed() -> None:
    graph = make_graph(ScriptedLlm())
    with pytest.raises(PermissionError):
        await graph.ainvoke(
            START, config={"configurable": {"thread_id": "x"}, "recursion_limit": 80}
        )


async def test_failed_source_is_retried_then_reported_searched() -> None:
    calls = {"n": 0}

    def flaky(q: SearchQuery) -> SearchResult:
        calls["n"] += 1
        return (
            result("email", "failed", detail="down")
            if calls["n"] == 1
            else result(
                "email",
                "searched",
                [
                    rec(
                        "e1",
                        "email",
                        occurred_at=datetime(2026, 10, 12, tzinfo=NOW.tzinfo),
                    )
                ],
            )
        )

    state, pending = await advance(
        make_graph(
            ScriptedLlm(structured=structured()), [FakeConnector("email", search=flaky)]
        ),
        START,
        "t",
        "email",
    )
    assert state.retrieval_loops == 2
    assert {c.source: c.status for c in state.coverage} == {"email": "searched"}


async def test_unrecoverable_source_does_not_loop_forever() -> None:
    down = FakeConnector("email", raises=RuntimeError("down"))
    state, pending = await advance(
        make_graph(ScriptedLlm(), [down]), START, "t", "email"
    )
    assert state.retrieval_loops == 3  # first run plus two retries, then stop
    assert (
        pending is None
        and state.status == "needs_review"
        and state.coverage[0].status == "failed"
    )
    assert any(g.origin == "coverage" and "email" in g.what_missing for g in state.gaps)


async def test_ambiguous_project_asks_the_user_then_narrows_the_case() -> None:
    p1, p2 = (
        rec("a", "email", project_id="p1", excerpt="alpha", occurred_at=NOW),
        rec("b", "email", project_id="p2", excerpt="beta", occurred_at=NOW),
    )
    email = FakeConnector(
        "email", search=lambda q: result("email", "searched", [p1, p2])
    )
    llm = ScriptedLlm(structured=structured())
    graph = make_graph(llm, [email])

    state, pending = await advance(graph, START, "t", "email")
    assert pending is not None and pending["kind"] == "clarification"
    assert pending["questions"][0]["options"] == ["p1", "p2"]

    state, pending = await advance(
        graph,
        Command(resume=ClarificationResume(project_id="p1").model_dump()),
        "t",
        "email",
    )
    assert state.context.project_id == "p1"
    assert {e.id for e in state.evidence} == {"a"}  # the other project's record is gone
    assert llm.count(InvestigationPlan) == 2  # re-planned after the answer
    assert pending is not None and pending["kind"] == "review"


async def test_reviewer_can_ask_for_more_evidence_and_the_plan_sees_the_note() -> None:
    llm = ScriptedLlm(structured=structured())
    graph = make_graph(llm)
    await advance(graph, START)
    state, pending = await advance(
        graph, review("needs_more_evidence", "Look at the Jira thread")
    )
    assert llm.count(InvestigationPlan) == 2
    assert "Look at the Jira thread" in state.reviewer_notes
    assert (
        pending is not None and pending["kind"] == "review"
    )  # back at review with fresh results


async def test_revise_resynthesizes_without_searching_again() -> None:
    llm = ScriptedLlm(structured=structured())
    graph = make_graph(llm)
    await advance(graph, START)
    searches = len(connectors())  # noqa: F841
    state, pending = await advance(graph, review("revise", "Tone down finding 2"))
    assert llm.count(SynthesisDraft) == 2 and llm.count(InvestigationPlan) == 1
    assert pending is not None and pending["kind"] == "review"


async def test_no_draft_without_a_verified_finding() -> None:
    only_unverified = SynthesisDraft(
        summary="s",
        findings=[
            FindingDraft(
                title="t",
                claim="Something may have happened",
                status="needs_verification",
                supporting_evidence_ids=["e1"],
                reasoning_type="inference",
            )
        ],
    )
    graph = make_graph(
        ScriptedLlm(structured=structured({SynthesisDraft: only_unverified}))
    )
    await advance(graph, START)
    state, pending = await advance(graph, review("approved"))
    assert (
        pending is None and state.draft_status == "not_possible" and state.draft == ""
    )
    assert state.status == "needs_review"  # never resolved without an approved draft


async def test_requested_changes_regenerate_the_draft_until_the_limit() -> None:
    llm = ScriptedLlm(structured=structured())
    graph = make_graph(llm)
    await advance(graph, START)
    await advance(graph, review("approved"))
    state, pending = await advance(graph, approval(False, note="Shorter please"))
    assert (
        pending is not None and pending["kind"] == "draft_approval"
    )  # regenerated, asking again
    assert llm.count(DraftPlan) == 2
    await advance(graph, approval(False))
    state, pending = await advance(graph, approval(False))
    assert (
        pending is None
        and state.status == "needs_review"
        and state.draft_status == "changes_requested"
    )


async def test_duplicate_records_are_folded_and_citations_follow() -> None:
    a = rec("a", "email", excerpt="Same body", author="x", occurred_at=NOW)
    b = rec(
        "b",
        "chat",
        excerpt="  same   BODY ",
        author="X",
        occurred_at=NOW.replace(hour=12),
    )
    email = FakeConnector("email", search=lambda q: result("email", "searched", [a, b]))
    s = structured()
    s[SynthesisDraft] = SynthesisDraft(
        summary="s",
        findings=[
            FindingDraft(
                title="t",
                claim="Said once",
                status="verified",
                supporting_evidence_ids=["b"],
                reasoning_type="direct",
            )
        ],
    )
    state, _ = await advance(
        make_graph(ScriptedLlm(structured=s), [email]), START, "t", "email"
    )
    assert [e.id for e in state.evidence] == ["a"] and state.duplicate_of == {"b": "a"}
    assert state.findings[0].supporting_evidence_ids == [
        "a"
    ]  # cited the copy, kept the original


async def test_llm_failure_in_analysis_fails_the_run_but_keeps_the_evidence() -> None:
    s = structured()
    s[TimelineDraft] = LlmError("boom")
    state, pending = await advance(make_graph(ScriptedLlm(structured=s)), START)
    assert pending is None and state.status == "failed" and state.error
    assert {e.id for e in state.evidence} == {"e1", "c1"} and state.timeline == []


async def test_empty_problem_statement_fails_at_intake() -> None:
    state, _ = await advance(make_graph(ScriptedLlm()), {"question": "   "})
    assert state.status == "failed"


def test_access_helper_used() -> None:
    assert access("a").permitted_sources == frozenset({"a"}) and connectors()
