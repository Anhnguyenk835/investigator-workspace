"""Each subgraph on its own: retrieval (tool loop), analysis, validation, response."""

from __future__ import annotations

from datetime import date
from typing import Any

from investigator.agents.investigation.env import NodeEnv, as_model
from investigator.agents.investigation.schemas import (
    BlockersDraft,
    CaseContext,
    ClaimSide,
    CommitmentDraft,
    CommitmentsDraft,
    Conflict,
    CrossCheckDraft,
    DraftPlan,
    Finding,
    TimelineDraft,
    TimelineEventDraft,
)
from investigator.agents.investigation.subgraphs.analysis import (
    AnalysisState,
    build_analysis_subgraph,
    commitment_status,
)
from investigator.agents.investigation.subgraphs.response import (
    ResponseState,
    build_response_subgraph,
    date_keys,
    grounding_violations,
    tone_violations,
)
from investigator.agents.investigation.subgraphs.retrieval import (
    RetrievalState,
    build_retrieval_subgraph,
)
from investigator.agents.investigation.subgraphs.validation import (
    ValidationState,
    build_validation_subgraph,
)
from investigator.connectors import SourceCoverage
from investigator.tools import HarnessLimits, ToolHarness
from tests.fakes import (
    FakeConnector,
    ScriptedLlm,
    access,
    rec,
    result,
    text_turn,
    tool_turn,
)
from tests.scenario import NOW


def env_for(
    llm: ScriptedLlm, *conns: FakeConnector, limits: HarnessLimits | None = None
) -> NodeEnv:
    return NodeEnv(
        llm=llm,  # type: ignore[arg-type]
        harness=ToolHarness({c.name: c for c in conns}, limits or HarnessLimits()),
        agent_route="fast",
        default_access=None,
        now=lambda: NOW,
    )


# ---- retrieval: seed search + the reusable tool loop ----------------------------


async def retrieve(
    env: NodeEnv, *sources: str, queries: list[str] | None = None
) -> RetrievalState:
    sub = build_retrieval_subgraph(env)
    out = await sub.ainvoke(
        RetrievalState(
            question="why?", queries=queries or ["why"], context=CaseContext()
        ),
        config={"configurable": {"access": access(*sources)}, "recursion_limit": 60},
    )
    return as_model(out, RetrievalState)


async def test_every_plan_query_runs_on_every_readable_source() -> None:
    email, chat = FakeConnector("email"), FakeConnector("chat")
    llm = ScriptedLlm([text_turn("nothing more")])
    out = await retrieve(env_for(llm, email, chat), "email", "chat", queries=["a", "b"])
    assert [q.text for q in email.queries] == ["a", "b"] and [
        q.text for q in chat.queries
    ] == ["a", "b"]
    assert out.search_notes == "nothing more"


async def test_no_readable_source_means_no_model_call() -> None:
    llm = ScriptedLlm()
    out = await retrieve(env_for(llm, FakeConnector("email")))  # nothing permitted
    assert llm.tool_calls_seen == [] and out.evidence == []
    assert {(c.source, c.status) for c in out.coverage} == {
        ("email", "permission_denied")
    }


async def test_model_follows_a_thread_through_the_harness() -> None:
    first = rec("e1", thread_id="t1")
    email = FakeConnector(
        search=lambda q: result("email", "searched", [first]),
        threads={"t1": [first, rec("e2", thread_id="t1")]},
    )
    llm = ScriptedLlm(
        [tool_turn(("get_thread", {"thread_id": "t1"})), text_turn("followed t1")]
    )
    out = await retrieve(env_for(llm, email), "email")
    assert {e.id for e in out.evidence} == {"e1", "e2"}
    # The search, the whole thread read by rule, then the model's own request (a cache hit).
    assert [e.tool for e in out.tool_events] == [
        "search_records",
        "get_thread",
        "get_thread",
    ]
    assert out.tool_events[-1].status == "cached"
    assert [m.role for m in llm.tool_calls_seen[1][0]][-2:] == [
        "assistant",
        "tool",
    ]  # every call answered


async def test_model_cannot_pivot_to_an_unseen_id() -> None:
    email = FakeConnector(search=lambda q: result("email", "searched", [rec("e1")]))
    llm = ScriptedLlm(
        [tool_turn(("get_record", {"record_id": "secret-9"})), text_turn("done")]
    )
    out = await retrieve(env_for(llm, email), "email")
    assert email.fetched == [] and any(
        e.status == "unknown_id" for e in out.tool_events
    )


async def test_rounds_are_bounded_and_wrap_up_has_no_tools() -> None:
    email = FakeConnector(search=lambda q: result("email", "searched", [rec("e1")]))
    loop = [
        tool_turn(("search_records", {"source": "email", "query": f"q{i}"}))
        for i in range(10)
    ]
    llm = ScriptedLlm([*loop[:2], text_turn("final notes")])
    env = env_for(llm, email, limits=HarnessLimits(max_rounds=2, max_stale_rounds=9))
    out = await retrieve(env, "email")
    assert out.tool_rounds == 2 and out.search_notes == "final notes"
    messages, tools = llm.tool_calls_seen[-1]
    assert tools == [] and all(m.role != "tool" and not m.tool_calls for m in messages)


async def test_stale_rounds_stop_the_loop() -> None:
    email = FakeConnector(search=lambda q: result("email", "no_matches"))
    turns = [
        tool_turn(("search_records", {"source": "email", "query": f"q{i}"}))
        for i in range(5)
    ]
    out = await retrieve(
        env_for(
            ScriptedLlm([*turns[:2], text_turn("nothing")]),
            email,
            limits=HarnessLimits(max_stale_rounds=2),
        ),
        "email",
    )
    assert out.tool_rounds == 2


async def test_model_failure_is_reported_not_raised() -> None:
    out = await retrieve(
        env_for(ScriptedLlm(fail_tools=True), FakeConnector("email")), "email"
    )
    assert out.error


async def test_the_first_search_follows_a_few_pages_and_a_later_pass_finishes_the_rest() -> (
    None
):
    chain = ["p2", "p3", "p4"]  # more pages than one seed pass will read

    def page(q: Any) -> Any:
        cursor = q.cursor
        n = 0 if cursor is None else chain.index(cursor) + 1
        nxt = chain[n] if n < len(chain) else None
        return result("email", "searched", [rec(f"r{n}")], cursor=nxt)

    email = FakeConnector(search=page)
    sub = build_retrieval_subgraph(
        env_for(ScriptedLlm([text_turn("n"), text_turn("n")]), email)
    )
    cfg = {"configurable": {"access": access("email")}, "recursion_limit": 60}
    first = as_model(
        await sub.ainvoke(RetrievalState(queries=["x"]), cfg), RetrievalState
    )
    assert {e.id for e in first.evidence} == {
        "r0",
        "r1",
        "r2",
    }  # first page plus two more
    assert first.pending_cursors  # a page is still outstanding
    second = as_model(
        await sub.ainvoke(
            first.model_copy(update={"messages": [], "tool_rounds": 0}), cfg
        ),
        RetrievalState,
    )
    assert {e.id for e in second.evidence} == {"r0", "r1", "r2", "r3"}
    assert not second.pending_cursors


async def test_whole_threads_are_read_by_rule_once_and_lone_slack_messages_are_skipped() -> (
    None
):
    multi = rec("m1", "chat", thread_id="chat:t1", meta={"thread": "multi"})
    lone = rec("m2", "chat", thread_id="chat:t2", meta={"thread": "single"})
    seen: list[str] = []

    class Chat(FakeConnector):
        async def get_thread(self, thread_id: str, ctx: Any) -> Any:
            seen.append(thread_id)
            return result(
                "chat", "searched", [multi, rec("m3", "chat", thread_id=thread_id)]
            )

    chat = Chat("chat", search=lambda q: result("chat", "searched", [multi, lone]))
    sub = build_retrieval_subgraph(env_for(ScriptedLlm([text_turn("n")]), chat))
    cfg = {"configurable": {"access": access("chat")}, "recursion_limit": 60}
    out = as_model(
        await sub.ainvoke(RetrievalState(queries=["x"]), cfg), RetrievalState
    )
    assert seen == ["chat:t1"] and out.expanded_threads == ["chat:t1"]
    await sub.ainvoke(out.model_copy(update={"messages": [], "tool_rounds": 0}), cfg)
    assert seen == ["chat:t1"]  # already read: not read again on the next pass


def test_the_busiest_threads_are_read_first_within_a_budget() -> None:
    from investigator.agents.investigation.subgraphs.retrieval import (
        EXPAND_PER_SOURCE,
        pick_threads,
    )

    many = [
        rec(f"r{i}", "email", thread_id=f"t{i}", occurred_at=NOW.replace(minute=i))
        for i in range(20)
    ]
    busy = [rec(f"b{i}", "email", thread_id="busy") for i in range(3)]
    picked = pick_threads([*many, *busy], set())
    assert picked[0] == ("email", "busy")  # three results fall in it
    assert len(picked) == EXPAND_PER_SOURCE
    assert pick_threads(busy, {"busy"}) == []


# ---- analysis ----------------------------------------------------------------


def test_commitment_status_is_computed_from_dates_and_fulfilment() -> None:
    today = date(2026, 10, 17)
    assert commitment_status("explicit", date(2026, 10, 16), False, today) == "overdue"
    assert commitment_status("explicit", date(2026, 10, 18), False, today) == "at_risk"
    assert commitment_status("explicit", date(2026, 11, 1), False, today) == "confirmed"
    assert commitment_status("explicit", date(2026, 10, 1), True, today) == "fulfilled"
    assert (
        commitment_status("inferred", date(2026, 10, 1), False, today) == "unverified"
    )  # a date alone is not a promise
    assert commitment_status("explicit", None, False, today) == "confirmed"


async def analyze(llm: ScriptedLlm, *evidence: Any) -> AnalysisState:
    sub = build_analysis_subgraph(env_for(llm))
    return as_model(
        await sub.ainvoke(AnalysisState(question="q", evidence=list(evidence))),
        AnalysisState,
    )


async def test_analysis_takes_times_from_evidence_and_drops_uncited_items() -> None:
    from datetime import UTC, datetime

    e1 = rec(
        "e1",
        occurred_at=datetime(2026, 10, 12, 9, tzinfo=UTC),
        timestamp_precision="date_only",
    )
    llm = ScriptedLlm(
        structured={
            TimelineDraft: TimelineDraft(
                events=[
                    TimelineEventDraft(title="Real", summary="s", evidence_ids=["e1"]),
                    TimelineEventDraft(
                        title="Invented", summary="s", evidence_ids=["nope"]
                    ),
                ]
            ),
            CommitmentsDraft: CommitmentsDraft(
                commitments=[
                    CommitmentDraft(
                        description="ok", basis="explicit", evidence_ids=["e1"]
                    ),
                    CommitmentDraft(
                        description="ghost", basis="explicit", evidence_ids=["nope"]
                    ),
                ]
            ),
        }
    )
    out = await analyze(llm, e1)
    assert [(e.title, e.timestamp_precision) for e in out.timeline] == [
        ("Real", "date_only")
    ]
    assert out.timeline[0].occurred_at == e1.occurred_at
    assert [c.description for c in out.commitments] == ["ok"]


async def test_conflicts_need_real_evidence_on_both_sides_and_stay_unresolved() -> None:
    ok = CrossCheckDraft.model_validate(
        {
            "conflicts": [
                {
                    "claim_a": {"text": "ready", "evidence_ids": ["e1"]},
                    "claim_b": {"text": "blocked", "evidence_ids": ["e2"]},
                    "why": "differ",
                },
                {
                    "claim_a": {"text": "x", "evidence_ids": ["e1"]},
                    "claim_b": {"text": "y", "evidence_ids": ["ghost"]},
                    "why": "w",
                },
            ]
        }
    )
    out = await analyze(
        ScriptedLlm(structured={CrossCheckDraft: ok, BlockersDraft: BlockersDraft()}),
        rec("e1"),
        rec("e2"),
    )
    assert len(out.conflicts) == 1 and out.conflicts[0].resolution == "unresolved"


async def test_analysis_stops_on_model_failure() -> None:
    from investigator.llm import LlmError

    out = await analyze(
        ScriptedLlm(structured={TimelineDraft: LlmError("boom")}), rec("e1")
    )
    assert out.error and out.commitments == []


# ---- validation --------------------------------------------------------------


def finding(id: str, **kw: Any) -> Finding:
    base: dict[str, Any] = {
        "id": id,
        "title": id,
        "claim": f"claim {id}",
        "status": "verified",
        "supporting_evidence_ids": ["e1"],
        "reasoning_type": "direct",
    }
    return Finding(**{**base, **kw})


def validate(
    findings: list[Finding],
    conflicts: list[Conflict] | None = None,
    coverage: list[SourceCoverage] | None = None,
) -> dict[str, list[str]]:
    out = as_model(
        build_validation_subgraph().invoke(
            ValidationState(
                evidence=[rec("e1", occurred_at=NOW)],
                findings=findings,
                conflicts=conflicts or [],
                coverage=coverage or [],
            )
        ),
        ValidationState,
    )
    by: dict[str, list[str]] = {}
    for i in out.report.issues:
        by.setdefault(i.finding_id or "-", []).append(f"{i.code}:{i.severity}")
    by["passed"] = [str(out.report.passed)]
    return by


def test_clean_findings_pass() -> None:
    assert validate([finding("a")]) == {"passed": ["True"]}


def test_citation_rules() -> None:
    by = validate(
        [
            finding("nosupport", supporting_evidence_ids=[]),
            finding("unknown_only", supporting_evidence_ids=["ghost"]),
            finding("mixed", supporting_evidence_ids=["e1", "ghost"]),
            finding(
                "absence", status="unknown", supporting_evidence_ids=[]
            ),  # "we don't know" needs no evidence
        ]
    )
    assert by["nosupport"] == ["citation_missing:error"] and by["unknown_only"] == [
        "citation_missing:error"
    ]
    assert (
        by["mixed"] == ["citation_unknown_id:error"]
        and "absence" not in by
        and by["passed"] == ["False"]
    )


def test_verified_cannot_stand_against_contradiction_or_conflict() -> None:
    conflict = Conflict(
        id="c",
        claim_a=ClaimSide(text="a", evidence_ids=["e1"]),
        claim_b=ClaimSide(text="b", evidence_ids=["e9"]),
        why="w",
    )
    by = validate(
        [finding("contra", contradicting_evidence_ids=["e1"]), finding("inconflict")],
        [conflict],
    )
    assert by["contra"] == ["confidence_overstated:error"] and by["inconflict"] == [
        "confidence_overstated:error"
    ]


def test_inference_is_never_verified_and_never_assigns_blame() -> None:
    by = validate(
        [
            finding("inf", reasoning_type="inference"),
            finding(
                "blame",
                claim="The vendor is at fault",
                reasoning_type="inference",
                status="needs_verification",
            ),
            finding(
                "direct_blame", claim="Sam blamed the vendor in writing"
            ),  # direct evidence: allowed
        ]
    )
    assert by["inf"] == ["inference_marked_verified:error"]
    assert (
        by["blame"] == ["blame_without_direct_evidence:error"]
        and "direct_blame" not in by
    )


def test_unsearched_sources_warn_but_do_not_block() -> None:
    by = validate(
        [finding("a")], coverage=[SourceCoverage(source="jira", status="failed")]
    )
    assert by["-"] == ["coverage_limit:warning"] and by["passed"] == ["True"]


# ---- response ------------------------------------------------------------------


def test_tone_and_grounding_checks() -> None:
    assert tone_violations("The delay is Sam's fault.", []) == ["assigns blame"]
    assert "makes a promise or guarantee" in tone_violations("We guarantee it.", [])
    assert tone_violations("See record e1 for details", ["e1"]) == [
        "exposes internal record ids"
    ]
    assert date_keys("Oct 12, 13 October and 2026-10-14") == {
        (10, 12),
        (10, 13),
        (10, 14),
    }
    f = finding("a", claim="Request received on Oct 12")
    assert grounding_violations("We received it on October 12.", [f], []) == []
    assert grounding_violations("It will be ready on Oct 30.", [f], []) != []


async def draft(llm: ScriptedLlm) -> ResponseState:
    sub = build_response_subgraph(env_for(llm))
    return as_model(
        await sub.ainvoke(
            ResponseState(
                question="q",
                findings=[finding("a", claim="Request received on Oct 12")],
                evidence=[rec("e1", occurred_at=NOW)],
            )
        ),
        ResponseState,
    )


async def test_a_bad_draft_is_regenerated_once_then_passes() -> None:
    llm = ScriptedLlm(
        structured={
            DraftPlan: [
                DraftPlan(text="It is Sam's fault; ready Oct 30."),
                DraftPlan(text="We received your request on Oct 12."),
            ]
        }
    )
    out = await draft(llm)
    assert out.attempts == 2 and out.warnings == [] and "Oct 12" in out.draft


async def test_a_draft_that_stays_bad_keeps_its_warnings_for_the_approver() -> None:
    out = await draft(
        ScriptedLlm(
            structured={DraftPlan: DraftPlan(text="We guarantee it, by Oct 30.")}
        )
    )
    assert (
        out.attempts == 2
        and any("promise" in w for w in out.warnings)
        and any("Oct" in w or "date" in w for w in out.warnings)
    )
