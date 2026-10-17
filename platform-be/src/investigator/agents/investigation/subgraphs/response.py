"""Response subgraph: a customer update grounded in verified findings only.

    response_generator ─► tone_risk_checker ─► grounding_with_evidence ─┬─ clean / retried ─► editable_draft ─► END
              ▲                                                         └─ violations, attempts left ─┐
              └─────────────────────────────────────────────────────────────────────────────────────────┘

The model writes; code checks. Nothing here sends anything. The result is an
editable draft plus any warnings still standing, for a person to approve.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from investigator.agents.investigation.env import (
    UNTRUSTED,
    NodeEnv,
    ask,
    fail,
    render_evidence,
)
from investigator.agents.investigation.schemas import DraftPlan, Finding
from investigator.connectors import EvidenceRecord
from investigator.guardrails.injection.spotlight import derived_block, user_block
from investigator.guardrails.output.patterns import (
    BLAME,
    INTERNAL,
    PLACEHOLDER,
    PROMISE,
)
from investigator.guardrails.output.sanitize import TRAILING, URL_IN_TEXT

MAX_ATTEMPTS = 2

MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        1,
    )
}
_MON = "(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
DATE_ISO = re.compile(r"\b\d{4}-(\d{2})-(\d{2})\b")
DATE_MD = re.compile(rf"\b({_MON})\.? (\d{{1,2}})\b", re.IGNORECASE)
DATE_DM = re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)? ({_MON})\b", re.IGNORECASE)


def date_keys(text: str) -> set[tuple[int, int]]:
    """(month, day) of every date written in `text`. Year is ignored on purpose:
    a draft restating "Oct 12" is grounded by a record dated 2026-10-12."""
    keys = {(int(m), int(d)) for m, d in DATE_ISO.findall(text)}
    keys |= {(MONTHS[m[:3].lower()], int(d)) for m, d in DATE_MD.findall(text)}
    keys |= {(MONTHS[m[:3].lower()], int(d)) for d, m in DATE_DM.findall(text)}
    return keys


class ResponseState(BaseModel):
    question: str = ""
    findings: list[Finding] = Field(default_factory=list)  # verified only
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)
    feedback: str = ""
    today: date | None = None
    draft: str = ""
    violations: list[str] = Field(default_factory=list)
    attempts: int = 0
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


def _cited(s: ResponseState) -> list[EvidenceRecord]:
    ids = {i for f in s.findings for i in f.supporting_evidence_ids}
    return [e for e in s.evidence if e.id in ids]


def tone_violations(draft: str, evidence_ids: list[str]) -> list[str]:
    out: list[str] = []
    if BLAME.search(draft):
        out.append("assigns blame")
    if PROMISE.search(draft):
        out.append("makes a promise or guarantee")
    if INTERNAL.search(draft):
        out.append("contains internal-only wording")
    if any(i in draft for i in evidence_ids):
        out.append("exposes internal record ids")
    if PLACEHOLDER.search(draft):
        out.append("contains an unresolved placeholder")
    return out


def grounding_violations(
    draft: str, findings: list[Finding], cited: list[EvidenceRecord]
) -> list[str]:
    corpus = " ".join(f"{f.claim} {f.explanation}" for f in findings)
    corpus += " ".join(e.model_excerpt or e.excerpt for e in cited)
    corpus += " ".join(e.occurred_at.date().isoformat() for e in cited if e.occurred_at)
    known = date_keys(corpus)
    out = [
        f"mentions a date ({m}/{d}) not found in the verified findings or their evidence"
        for m, d in sorted(date_keys(draft) - known)
    ]
    # A customer update may repeat an address the evidence gives, never introduce one.
    seen = {u.rstrip(TRAILING) for u in URL_IN_TEXT.findall(corpus)}
    out += [
        "contains a link or image address that no verified evidence gives"
        for url in sorted(
            {u.rstrip(TRAILING) for u in URL_IN_TEXT.findall(draft)} - seen
        )
    ][:1]
    if "![" in draft:
        out.append("contains an image")
    return out


def build_response_subgraph(env: NodeEnv) -> Any:
    async def response_generator(s: ResponseState) -> dict[str, Any]:
        facts = "\n".join(
            f"- {f.title}: {f.claim} {f.explanation}".strip() for f in s.findings
        )
        redo = (
            f"\n\nYour previous draft had problems; fix them: {'; '.join(s.violations)}."
            if s.violations
            else ""
        )
        notes = (
            "\n\nReviewer notes:\n" + user_block("- " + "\n- ".join(s.reviewer_notes))
            if s.reviewer_notes
            else ""
        )
        ask_more = (
            f"\n\nChanges requested: {user_block(s.feedback)}" if s.feedback else ""
        )
        plan, err = await ask(
            env,
            "Write a short, calm, accurate update for the customer: greeting, acknowledgement, "
            "confirmed current status, what is known, next steps. Use ONLY the verified facts "
            "given. Do not promise dates, assign blame, mention internal notes or record ids, "
            "or state anything not listed. If something is unknown, say it is still being "
            f"confirmed. {UNTRUSTED}",
            f"Customer issue: {user_block(s.question)}\n\n"
            f"Verified facts:\n{derived_block(facts)}{notes}{ask_more}{redo}"
            f"\n\nEvidence for reference:\n{render_evidence(_cited(s), 600)}",
            DraftPlan,
        )
        if plan is None:
            return fail(err or "draft failed")
        return {"draft": plan.text.strip(), "attempts": s.attempts + 1}

    def tone_risk_checker(s: ResponseState) -> dict[str, Any]:
        return {"violations": tone_violations(s.draft, [e.id for e in s.evidence])}

    def grounding_with_evidence(s: ResponseState) -> dict[str, Any]:
        return {
            "violations": [
                *s.violations,
                *grounding_violations(s.draft, s.findings, _cited(s)),
            ]
        }

    def editable_draft(s: ResponseState) -> dict[str, Any]:
        # Anything still wrong is shown to the person approving, not hidden.
        return {"warnings": list(s.violations)}

    def after_grounding(s: ResponseState) -> str:
        return (
            "response_generator"
            if s.violations and s.attempts < MAX_ATTEMPTS
            else "editable_draft"
        )

    b: StateGraph[ResponseState, Any, ResponseState, ResponseState] = StateGraph(
        ResponseState
    )
    b.add_node("response_generator", response_generator)
    b.add_node("tone_risk_checker", tone_risk_checker)
    b.add_node("grounding_with_evidence", grounding_with_evidence)
    b.add_node("editable_draft", editable_draft)
    b.add_edge(START, "response_generator")
    b.add_conditional_edges(
        "response_generator",
        lambda s: END if s.error else "tone_risk_checker",
        {"tone_risk_checker": "tone_risk_checker", END: END},
    )
    b.add_edge("tone_risk_checker", "grounding_with_evidence")
    b.add_conditional_edges(
        "grounding_with_evidence",
        after_grounding,
        {
            "response_generator": "response_generator",
            "editable_draft": "editable_draft",
        },
    )
    b.add_edge("editable_draft", END)
    return b.compile()
