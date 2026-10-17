"""Validation subgraph: check findings, change nothing.

    citation_validator ─► confidence_assessor ─► fact_vs_inference_check ─► missing_information_check ─► END

All four are deterministic code. Each appends `ValidationIssue`s; none edits a
finding. The main graph's `repair_findings` applies the fixes and validation runs
again, so what is checked and what is changed stay separate and testable.
Errors block; warnings inform the reviewer.
"""

from __future__ import annotations

import itertools
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from investigator.agents.investigation.schemas import (
    Commitment,
    Conflict,
    Finding,
    TimelineEvent,
    ValidationIssue,
    ValidationReport,
)
from investigator.connectors import EvidenceRecord, SourceCoverage
from investigator.guardrails.output.patterns import BLAME

NOT_FULLY_SEARCHED = {"failed", "partial", "permission_denied", "not_connected"}


class ValidationState(BaseModel):
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    commitments: list[Commitment] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    coverage: list[SourceCoverage] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    report: ValidationReport = Field(default_factory=ValidationReport)


def _kept(s: ValidationState) -> set[str]:
    return {e.id for e in s.evidence}


def citation_validator(s: ValidationState) -> dict[str, Any]:
    """Every cited id must be a real record; a claim needs support unless it says "unknown"."""
    kept, issues = _kept(s), []
    for f in s.findings:
        cited = [*f.supporting_evidence_ids, *f.contradicting_evidence_ids]
        unknown = [i for i in cited if i not in kept]
        support = [i for i in f.supporting_evidence_ids if i in kept]
        if f.status != "unknown" and not support:
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="citation_missing",
                    severity="error",
                    fix="drop_finding",
                    detail="The claim cites no real evidence record.",
                )
            )
        elif unknown:
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="citation_unknown_id",
                    severity="error",
                    fix="drop_ids",
                    ids=unknown,
                    detail=f"Cited ids do not exist: {', '.join(unknown)}.",
                )
            )
    return {"issues": [*s.issues, *issues]}


def support_check(s: ValidationState) -> dict[str, Any]:
    """A record that exists must also say what the claim says (judged earlier by
    `verify_claims`; here the verdicts become issues)."""
    issues: list[ValidationIssue] = []
    for f in s.findings:
        if f.support_status == "unchecked":
            continue
        cited = set(f.supporting_evidence_ids)
        weak = [
            c.evidence_id
            for c in f.support
            if c.verdict == "unsupported" and c.evidence_id in cited
        ]
        if f.support_status == "unsupported" and f.status != "unknown":
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="claim_not_supported",
                    severity="error",
                    fix="drop_finding",
                    detail="None of the cited records says this.",
                )
            )
        elif weak:
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="citation_not_supporting",
                    severity="error",
                    fix="drop_ids",
                    ids=weak,
                    detail=f"Cited but does not support the claim: {', '.join(weak)}.",
                )
            )
        if f.support_status == "partial" and f.status == "verified":
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="support_partial",
                    severity="error",
                    fix="downgrade",
                    detail="The cited records support only part of this claim.",
                )
            )
    for c in s.commitments:
        if c.support_status in ("unsupported", "partial"):
            issues.append(
                ValidationIssue(
                    code="commitment_weak_support",
                    severity="warning",
                    detail=f"Commitment not fully supported by its evidence: {c.description[:80]}",
                )
            )
    for t in s.timeline:
        if t.support_status in ("unsupported", "partial"):
            issues.append(
                ValidationIssue(
                    code="timeline_weak_support",
                    severity="warning",
                    detail=f"Timeline event not fully supported by its evidence: {t.title[:80]}",
                )
            )
    return {"issues": [*s.issues, *issues]}


TAINT_NOTE = (
    "Rests on a record that contained instructions aimed at an AI. Those parts were withheld "
    "from the analysis; read the original record before relying on this."
)


def taint_check(s: ValidationState) -> dict[str, Any]:
    """A claim that leans on a record carrying injected instructions is not `verified`, and
    one that rests only on such records is at most an inference. Deterministic: no model
    is asked whether it can be trusted."""
    by_id = {e.id: e for e in s.evidence}
    issues: list[ValidationIssue] = []
    for f in s.findings:
        if f.review_flag:  # already handled in an earlier round
            continue
        support = [by_id[i] for i in f.supporting_evidence_ids if i in by_id]
        bad = [e.id for e in support if e.trust == "tainted"]
        if not bad:
            continue
        issues.append(
            ValidationIssue(
                finding_id=f.id,
                code="support_tainted",
                severity="error",
                fix="flag_tainted",
                ids=bad,
                detail="; ".join(
                    [
                        "All the supporting records"
                        if len(bad) == len(support)
                        else "Some supporting records"
                    ]
                )
                + " carried instructions aimed at an AI.",
            )
        )
    return {"issues": [*s.issues, *issues]}


def confidence_assessor(s: ValidationState) -> dict[str, Any]:
    """`verified` must not hold against contradicting or conflicted evidence."""
    kept, issues = _kept(s), []
    sides = [
        set(c.claim_a.evidence_ids) | set(c.claim_b.evidence_ids)
        for c in s.conflicts
        if c.resolution == "unresolved"
    ]
    for f in s.findings:
        if f.status != "verified":
            continue
        contradicted = [i for i in f.contradicting_evidence_ids if i in kept]
        in_conflict = any(set(f.supporting_evidence_ids) & side for side in sides)
        if contradicted or in_conflict:
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="confidence_overstated",
                    severity="error",
                    fix="force_conflicting",
                    detail="Marked verified, but contradicting or conflicted evidence exists.",
                )
            )
    return {"issues": [*s.issues, *issues]}


def fact_vs_inference_check(s: ValidationState) -> dict[str, Any]:
    """An inference is never `verified`, and an inference never assigns blame."""
    issues = []
    for f in s.findings:
        blames = bool(BLAME.search(f"{f.title} {f.claim}"))
        if blames and f.reasoning_type == "inference":
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="blame_without_direct_evidence",
                    severity="error",
                    fix="drop_finding",
                    detail="Assigns fault by inference; blame needs direct evidence.",
                )
            )
        elif f.status == "verified" and f.reasoning_type == "inference":
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="inference_marked_verified",
                    severity="error",
                    fix="downgrade",
                    detail="An inference cannot be marked verified.",
                )
            )
    return {"issues": [*s.issues, *issues]}


def missing_information_check(s: ValidationState) -> dict[str, Any]:
    """Warnings only: say what the conclusions do not cover."""
    issues = []
    unsearched = [c for c in s.coverage if c.status in NOT_FULLY_SEARCHED]
    if unsearched:
        names = ", ".join(f"{c.source} ({c.status})" for c in unsearched)
        issues.append(
            ValidationIssue(
                code="coverage_limit",
                severity="warning",
                detail=f"Not fully searched: {names}. Conclusions cover only what was retrieved.",
            )
        )
    by_id = {e.id: e for e in s.evidence}
    for f in s.findings:
        support = [by_id[i] for i in f.supporting_evidence_ids if i in by_id]
        if (
            f.status == "verified"
            and support
            and all(e.occurred_at is None for e in support)
        ):
            issues.append(
                ValidationIssue(
                    finding_id=f.id,
                    code="undated_support",
                    severity="warning",
                    detail="Every supporting record is undated; check the sequence manually.",
                )
            )
    return {"issues": [*s.issues, *issues]}


def summarize(s: ValidationState) -> dict[str, Any]:
    return {
        "report": ValidationReport(
            passed=not any(i.severity == "error" for i in s.issues), issues=s.issues
        )
    }


def build_validation_subgraph() -> Any:
    b: StateGraph[ValidationState, Any, ValidationState, ValidationState] = StateGraph(
        ValidationState
    )
    chain = [
        ("citation_validator", citation_validator),
        ("support_check", support_check),
        ("taint_check", taint_check),
        ("confidence_assessor", confidence_assessor),
        ("fact_vs_inference_check", fact_vs_inference_check),
        ("missing_information_check", missing_information_check),
        ("report", summarize),
    ]
    for name, fn in chain:
        b.add_node(name, fn)
    b.add_edge(START, chain[0][0])
    for (here, _), (nxt, _) in itertools.pairwise(chain):
        b.add_edge(here, nxt)
    b.add_edge(chain[-1][0], END)
    return b.compile()
