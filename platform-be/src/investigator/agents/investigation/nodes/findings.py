"""Main graph, steps 7-14: analyse (subgraph), synthesize, validate (subgraph), repair, recommend."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from investigator.agents.investigation.env import (
    EVIDENCE_RULES,
    UNTRUSTED,
    NodeEnv,
    as_model,
    ask,
    fail,
)
from investigator.agents.investigation.schemas import (
    ActionsDraft,
    Finding,
    RecommendedAction,
    SynthesisDraft,
    ValidationReport,
    stable_id,
)
from investigator.agents.investigation.state import InvestigationState
from investigator.agents.investigation.subgraphs.analysis import AnalysisState
from investigator.agents.investigation.subgraphs.validation import (
    TAINT_NOTE,
    ValidationState,
)
from investigator.agents.support import Claim, check_claims, status_of
from investigator.guardrails.injection.spotlight import derived_block, user_block


async def analyze_evidence(state: InvestigationState, *, sub: Any) -> dict[str, Any]:
    out = as_model(
        await sub.ainvoke(
            AnalysisState(
                question=state.question,
                evidence=state.evidence,
                duplicate_of=state.duplicate_of,
                coverage=state.coverage,
                reviewer_notes=state.reviewer_notes,
            )
        ),
        AnalysisState,
    )
    # Keep the coverage/quality gaps from assessment; the analysis contributes its own.
    kept = [g for g in state.gaps if g.origin != "analysis"]
    update = {
        "timeline": out.timeline,
        "commitments": out.commitments,
        "blockers": out.blockers,
        "conflicts": out.conflicts,
        "gaps": [*kept, *out.gaps],
    }
    return {**update, **fail(out.error)} if out.error else update


def _analysis_digest(s: InvestigationState) -> str:
    def ids(xs: list[str]) -> str:
        return f"[{', '.join(xs)}]"

    parts = [
        "Timeline:\n"
        + (
            "\n".join(
                f"- {e.occurred_at.date() if e.occurred_at else 'undated'} {e.title}: {e.summary} {ids(e.evidence_ids)}"
                for e in s.timeline
            )
            or "(none)"
        ),
        "Commitments:\n"
        + (
            "\n".join(
                f"- {c.description} | {c.basis} | due {c.due_date} | {c.status} {ids(c.evidence_ids)}"
                for c in s.commitments
            )
            or "(none)"
        ),
        "Blockers:\n"
        + (
            "\n".join(
                f"- {b.description} ({b.kind}, {b.basis}) {ids(b.evidence_ids)}"
                for b in s.blockers
            )
            or "(none)"
        ),
        "Conflicts (unresolved):\n"
        + (
            "\n".join(
                f"- A: {c.claim_a.text} {ids(c.claim_a.evidence_ids)} vs B: {c.claim_b.text} {ids(c.claim_b.evidence_ids)}"
                for c in s.conflicts
            )
            or "(none)"
        ),
        "Gaps:\n" + ("\n".join(f"- {g.what_missing}" for g in s.gaps) or "(none)"),
        "Source coverage:\n"
        + ("\n".join(f"- {c.source}: {c.status}" for c in s.coverage) or "(none)"),
    ]
    return "\n\n".join(parts)


async def synthesize_findings(
    state: InvestigationState, *, env: NodeEnv
) -> dict[str, Any]:
    notes = (
        "\n\nReviewer notes:\n" + user_block("- " + "\n- ".join(state.reviewer_notes))
        if state.reviewer_notes
        else ""
    )
    draft, err = await ask(
        env,
        "Write the findings of an investigation as a short summary plus findings. Each "
        "finding: a claim, its supporting_evidence_ids (and contradicting ones), and "
        "reasoning_type `direct` (the evidence says it) or `inference` (you conclude it). "
        "Status: `verified` only if direct and uncontradicted; `conflicting` if evidence "
        "disagrees (show both, never pick one); `needs_verification` for inferences or thin "
        "support; `unknown` for something that cannot be established from the evidence. "
        "Never assign blame without direct evidence. Cite evidence ids exactly as given. "
        f"{UNTRUSTED} {EVIDENCE_RULES}",
        f"Question: {user_block(state.question)}{notes}\n\n"
        f"{derived_block(_analysis_digest(state))}",
        SynthesisDraft,
    )
    if draft is None:
        return fail(err or "synthesis failed")
    previous = {f.id: f for f in state.findings}
    out: dict[str, Finding] = {}
    for d in draft.findings:
        # Only duplicate ids are mapped; unknown ids are left for validation to catch.
        sup = [state.duplicate_of.get(i, i) for i in d.supporting_evidence_ids]
        con = [state.duplicate_of.get(i, i) for i in d.contradicting_evidence_ids]
        fid = stable_id("fd", d.claim)
        out[fid] = Finding(
            **{
                **d.model_dump(),
                "supporting_evidence_ids": sup,
                "contradicting_evidence_ids": con,
            },
            id=fid,
            reviewer_note=previous[fid].reviewer_note if fid in previous else None,
        )
    return {
        "summary": draft.summary,
        "findings": list(out.values()),
        "validation": ValidationReport(),
        "validation_rounds": 0,
    }


async def verify_claims(state: InvestigationState, *, env: NodeEnv) -> dict[str, Any]:
    """Judge every claim against the passages it cites. A claim whose record does not
    say it is flagged here; validation then drops or downgrades it."""
    claims = [
        *(
            Claim(f"f:{f.id}", f.claim, f.supporting_evidence_ids)
            for f in state.findings
        ),
        *(Claim(f"c:{c.id}", c.description, c.evidence_ids) for c in state.commitments),
        *(
            Claim(f"t:{t.id}", f"{t.title}: {t.summary}", t.evidence_ids)
            for t in state.timeline
        ),
    ]
    results = await check_claims(env.llm, claims, state.evidence)

    def apply[T: BaseModel](prefix: str, items: list[T], key: str = "id") -> list[T]:
        out: list[T] = []
        for item in items:
            got = results.get(f"{prefix}:{getattr(item, key)}")
            out.append(
                item
                if got is None
                else item.model_copy(
                    update={"support": got.checks, "support_status": got.status}
                )
            )
        return out

    return {
        "findings": apply("f", state.findings),
        "commitments": apply("c", state.commitments),
        "timeline": apply("t", state.timeline),
    }


def validate_claims(state: InvestigationState, *, sub: Any) -> dict[str, Any]:
    out = as_model(
        sub.invoke(
            ValidationState(
                evidence=state.evidence,
                findings=state.findings,
                commitments=state.commitments,
                timeline=state.timeline,
                conflicts=state.conflicts,
                coverage=state.coverage,
            )
        ),
        ValidationState,
    )
    return {"validation": out.report}


def repair_findings(state: InvestigationState) -> dict[str, Any]:
    """Apply the fixes validation asked for. Claims without real support leave the
    findings and are kept for the reviewer; nothing is invented to fill the gap."""
    by_finding: dict[str, list[Any]] = {}
    for issue in state.validation.issues:
        if issue.severity == "error" and issue.finding_id:
            by_finding.setdefault(issue.finding_id, []).append(issue)

    kept: list[Finding] = []
    rejected = list(state.rejected_findings)
    repaired = dropped = 0
    for f in state.findings:
        issues = by_finding.get(f.id, [])
        if not issues:
            kept.append(f)
            continue
        if any(i.fix == "drop_finding" for i in issues):
            why = next(i.code for i in issues if i.fix == "drop_finding")
            rejected.append(
                f.model_copy(
                    update={"explanation": f"[rejected: {why}] {f.explanation}".strip()}
                )
            )
            dropped += 1
            continue
        update: dict[str, Any] = {}
        for i in issues:
            if i.fix == "drop_ids":
                remaining = [c for c in f.support if c.evidence_id not in i.ids]
                update["support"] = remaining
                if remaining:
                    update["support_status"] = status_of(remaining)
                update["supporting_evidence_ids"] = [
                    x
                    for x in update.get(
                        "supporting_evidence_ids", f.supporting_evidence_ids
                    )
                    if x not in i.ids
                ]
                update["contradicting_evidence_ids"] = [
                    x
                    for x in update.get(
                        "contradicting_evidence_ids", f.contradicting_evidence_ids
                    )
                    if x not in i.ids
                ]
            elif i.fix == "force_conflicting":
                update["status"] = "conflicting"
            elif i.fix == "downgrade":
                update["status"] = "needs_verification"
            elif i.fix == "flag_tainted":
                update["review_flag"] = TAINT_NOTE
                if f.status == "verified":
                    update["status"] = "needs_verification"
                if set(f.supporting_evidence_ids) <= set(i.ids):
                    update["reasoning_type"] = "inference"
        kept.append(f.model_copy(update=update))
        repaired += 1
    return {
        "findings": kept,
        "rejected_findings": rejected,
        "validation_rounds": state.validation_rounds + 1,
        "validation": state.validation.model_copy(
            update={
                "repaired": state.validation.repaired + repaired,
                "dropped": state.validation.dropped + dropped,
            }
        ),
    }


async def recommend_actions(
    state: InvestigationState, *, env: NodeEnv
) -> dict[str, Any]:
    finding_ids = {f.id for f in state.findings}
    listing = (
        "\n".join(f"- {f.id} [{f.status}] {f.claim}" for f in state.findings)
        or "(none)"
    )
    gaps = (
        "\n".join(f"- {g.what_missing} → {g.follow_up}" for g in state.gaps) or "(none)"
    )
    draft, err = await ask(
        env,
        "Recommend concrete next steps for the Customer Success team, each with a rationale "
        "and the finding ids it relates to. Name an owner only if the evidence names one. "
        "Steps are internal suggestions; do not propose sending anything to the customer. "
        f"{UNTRUSTED} {EVIDENCE_RULES}",
        f"Question: {user_block(state.question)}\n\n"
        f"Findings:\n{derived_block(listing)}\n\nGaps:\n{derived_block(gaps)}",
        ActionsDraft,
    )
    if draft is None:
        return fail(err or "actions failed")
    kept_ids = {e.id for e in state.evidence}
    text_by_id = {e.id: f"{e.author or ''} {e.excerpt}".lower() for e in state.evidence}
    actions: dict[str, RecommendedAction] = {}
    for d in draft.actions:
        related = [i for i in d.related_finding_ids if i in finding_ids]
        evid = [state.duplicate_of.get(i, i) for i in d.evidence_ids]
        evid = [i for i in evid if i in kept_ids]
        if not related and not evid:
            continue  # a recommendation must point at something
        owner = d.owner
        if owner and not any(owner.lower() in text_by_id[i] for i in evid):
            owner = None  # an owner the cited evidence never mentions is a guess
        a = RecommendedAction(
            **{
                **d.model_dump(),
                "related_finding_ids": related,
                "evidence_ids": evid,
                "owner": owner,
            },
            id=stable_id("ac", d.title, *sorted(related)),
        )
        actions[a.id] = a
    return {"actions": list(actions.values())}
