"""Claims are judged against the passages they cite, and only confirmed passages count."""

from __future__ import annotations

import re
from typing import Any

from investigator.agents.investigation.schemas import (
    FindingDraft,
    SupportCheck,
    SupportDraft,
    SupportItemDraft,
    SupportVerdict,
    SynthesisDraft,
)
from investigator.agents.support import (
    Claim,
    check_claim,
    quote_in,
    status_of,
)
from investigator.llm import LlmError
from tests.fakes import ScriptedLlm, rec
from tests.scenario import advance, make_graph, structured

START = {"question": "Why was the form late?"}


def llm_with(draft: SupportDraft | Exception) -> Any:
    return ScriptedLlm(structured={SupportDraft: draft})


# ---- quotes ---------------------------------------------------------------------------


def test_a_quote_must_really_be_in_the_record_and_is_returned_as_written() -> None:
    record = rec("e1", excerpt="Please update the\nform before Oct 20.  Thanks.")
    assert (
        quote_in("update the form before oct 20", record)
        == "update the\nform before Oct 20"
    )
    assert quote_in("update the form after Oct 20", record) is None
    assert quote_in("   ", record) is None
    assert quote_in("x" * 400, rec("e2", excerpt="y")) is None


def test_status_of_a_set_of_checks() -> None:
    def c(v: SupportVerdict) -> SupportCheck:
        return SupportCheck(
            evidence_id="x", verdict=v, quote="q" if v != "unsupported" else None
        )

    assert status_of([c("unsupported"), c("supported")]) == "supported"
    assert status_of([c("unsupported"), c("partial")]) == "partial"
    assert status_of([c("unsupported")]) == "unsupported"
    assert status_of([]) == "unchecked"


# ---- one claim ------------------------------------------------------------------------


async def judge(draft: SupportDraft | Exception, ids: list[str] | None = None) -> Any:
    by_id = {
        "e1": rec("e1", excerpt="Please update the form before Oct 20."),
        "e2": rec("e2", excerpt="Lunch is at noon."),
    }
    return await check_claim(
        llm_with(draft),
        Claim("k", "Client asked for the form update", ids or ["e1", "e2"]),
        by_id,
    )


async def test_supported_needs_a_real_quote_and_unsupported_has_none() -> None:
    got = await judge(
        SupportDraft(
            checks=[
                SupportItemDraft(
                    evidence_id="e1", verdict="supported", quote="update the form"
                ),
                SupportItemDraft(evidence_id="e2", verdict="unsupported"),
            ]
        )
    )
    assert got.status == "supported"
    by = {c.evidence_id: c for c in got.checks}
    assert by["e1"].quote == "update the form" and by["e2"].verdict == "unsupported"


async def test_a_quote_that_is_not_in_the_record_voids_the_verdict() -> None:
    got = await judge(
        SupportDraft(
            checks=[
                SupportItemDraft(
                    evidence_id="e1",
                    verdict="supported",
                    quote="The client demanded a refund",
                ),
                SupportItemDraft(
                    evidence_id="e2", verdict="partial", quote="Lunch is at noon"
                ),
            ]
        )
    )
    by = {c.evidence_id: c for c in got.checks}
    assert (
        by["e1"].verdict == "unsupported" and by["e1"].quote is None
    )  # invented passage
    assert by["e2"].verdict == "partial"  # a real passage, though it is about lunch
    assert got.status == "partial"


async def test_a_record_the_model_skipped_is_not_support() -> None:
    got = await judge(
        SupportDraft(
            checks=[
                SupportItemDraft(
                    evidence_id="e1", verdict="supported", quote="update the form"
                )
            ]
        )
    )
    assert {c.evidence_id: c.verdict for c in got.checks} == {
        "e1": "supported",
        "e2": "unsupported",
    }


async def test_an_unavailable_model_leaves_the_claim_unchecked_and_no_citations_is_unsupported() -> (
    None
):
    assert await judge(LlmError("down")) is None
    none = await judge(SupportDraft(), ids=["missing"])
    assert none.status == "unsupported" and none.checks == []


# ---- in the graph ---------------------------------------------------------------------


def responder(verdicts: dict[str, SupportVerdict]) -> Any:
    """Per-record verdicts, quoting the first words of the record."""

    def respond(messages: Any) -> SupportDraft:
        text = str(messages[-1].content)
        checks = []
        for rid, body in re.findall(
            r'<record id="([^"]+)"[^>]*>\n(.*?)\n</record>', text, flags=re.DOTALL
        ):
            verdict: SupportVerdict = verdicts.get(rid, "supported")
            quote = (
                "" if verdict == "unsupported" else body.strip().splitlines()[0][:30]
            )
            checks.append(
                SupportItemDraft(evidence_id=rid, verdict=verdict, quote=quote)
            )
        return SupportDraft(checks=checks)

    return respond


def findings(*drafts: FindingDraft) -> dict[type, Any]:
    return {SynthesisDraft: SynthesisDraft(summary="s", findings=list(drafts))}


def finding(title: str, claim: str, ids: list[str]) -> FindingDraft:
    return FindingDraft(
        title=title,
        claim=claim,
        status="verified",
        supporting_evidence_ids=ids,
        reasoning_type="direct",
    )


async def test_a_claim_no_cited_record_says_leaves_the_findings() -> None:
    s = structured(
        findings(
            finding("Request", "Client asked", ["e1"]),
            finding("Deadline", "Delivery by Friday", ["c1"]),
        )
    )
    s[SupportDraft] = responder({"c1": "unsupported"})
    state, _ = await advance(make_graph(ScriptedLlm(structured=s)), START)
    assert [f.title for f in state.findings] == ["Request"]
    assert [f.title for f in state.rejected_findings] == ["Deadline"]
    assert "claim_not_supported" in state.rejected_findings[0].explanation
    kept = state.findings[0]
    assert kept.support_status == "supported" and kept.support[0].quote


async def test_support_for_only_part_of_a_claim_downgrades_verified() -> None:
    s = structured(findings(finding("Request", "Client asked", ["e1"])))
    s[SupportDraft] = responder({"e1": "partial"})
    state, _ = await advance(make_graph(ScriptedLlm(structured=s)), START)
    (f,) = state.findings
    assert f.status == "needs_verification" and f.support_status == "partial"


async def test_a_citation_that_does_not_support_is_dropped_the_rest_stay() -> None:
    s = structured(findings(finding("Request", "Client asked", ["e1", "c1"])))
    s[SupportDraft] = responder({"c1": "unsupported"})
    state, _ = await advance(make_graph(ScriptedLlm(structured=s)), START)
    (f,) = state.findings
    assert f.supporting_evidence_ids == ["e1"]
    assert state.validation.passed


async def test_commitments_and_timeline_are_flagged_not_silently_dropped() -> None:
    s = structured()
    s[SupportDraft] = responder({"c1": "unsupported"})
    state, _ = await advance(make_graph(ScriptedLlm(structured=s)), START)
    assert state.commitments[0].support_status == "unsupported"  # cited only c1
    assert any(t.support_status == "unsupported" for t in state.timeline)
    codes = {i.code for i in state.validation.issues}
    assert {"commitment_weak_support", "timeline_weak_support"} <= codes
    assert all(
        i.severity == "warning" for i in state.validation.issues if "weak" in i.code
    )


async def test_when_the_check_cannot_run_claims_are_kept_but_marked_unchecked() -> None:
    s = structured()
    s[SupportDraft] = LlmError("down")
    state, _ = await advance(make_graph(ScriptedLlm(structured=s)), START)
    assert {f.title for f in state.findings} == {"Request", "Deadline"}
    assert all(f.support_status == "unchecked" for f in state.findings)
