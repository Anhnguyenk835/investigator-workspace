"""The stored investigation, written out as the model's grounding."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from investigator.connectors import EvidenceRecord
from investigator.investigations.models import Investigation
from investigator.tools import render_record

MAX_RECORDS = 60
EXCERPT_CHARS = 350


def _ids(inv: Investigation) -> list[str]:
    """Records the investigation's own conclusions rest on, in the order they appear."""
    ordered: list[str] = []

    def add(ids: Iterable[str]) -> None:
        for i in ids:
            if i not in ordered:
                ordered.append(i)

    for f in inv.findings:
        add(f.supporting_evidence_ids)
        add(f.contradicting_evidence_ids)
    for c in inv.commitments:
        add(c.evidence_ids)
    for t in inv.timeline:
        add(t.evidence_ids)
    for b in inv.blockers:
        add(b.evidence_ids)
    for x in inv.conflicts:
        add(x.claim_a.evidence_ids)
        add(x.claim_b.evidence_ids)
    return ordered


def pick_records(inv: Investigation) -> tuple[list[EvidenceRecord], int]:
    """Cited records first, then the rest by time, up to the budget."""
    by_id = {e.id: e for e in inv.evidence}
    first = [by_id[i] for i in _ids(inv) if i in by_id]
    rest = [e for e in inv.evidence if e.id not in {r.id for r in first}]
    chosen = (first + rest)[:MAX_RECORDS]
    return chosen, len(inv.evidence) - len(chosen)


def _when(value: datetime | None) -> str:
    return value.isoformat() if value else "undated"


def render_context(inv: Investigation) -> str:
    out: list[str] = [
        f"Question: {inv.question}",
        f"Run status: {inv.status}"
        + (f" (waiting for: {inv.awaiting})" if inv.awaiting else ""),
    ]
    if inv.error:
        out.append(f"The run failed: {inv.error}")
    out.append("\nSource coverage:")
    out += [
        f"- {c.source}: {c.status}" + (f" ({c.detail})" if c.detail else "")
        for c in inv.coverage
    ] or ["- (no source has been searched)"]
    if inv.summary:
        out += ["\nSummary (AI-generated, not reviewed):", inv.summary]

    out.append("\nFindings (status; basis; evidence):")
    out += [
        f"- [{f.status}; {f.reasoning_type}] {f.claim} | supports: "
        f"{', '.join(f.supporting_evidence_ids) or 'none'}"
        + (
            f" | contradicts: {', '.join(f.contradicting_evidence_ids)}"
            if f.contradicting_evidence_ids
            else ""
        )
        for f in inv.findings
    ] or ["- (none)"]

    out.append("\nTimeline:")
    out += [
        f"- {_when(t.occurred_at)} [{t.timestamp_precision}] {t.title}: {t.summary} "
        f"({', '.join(t.evidence_ids)})"
        for t in inv.timeline
    ] or ["- (none)"]

    out.append("\nCommitments (status is computed from dates):")
    out += [
        f"- [{c.status}] {c.description} | by {c.committed_by or 'unknown'}, owner "
        f"{c.owner or 'not confirmed'}, due {c.due_date or 'not stated'} "
        f"({', '.join(c.evidence_ids)})"
        for c in inv.commitments
    ] or ["- (none)"]

    out.append("\nBlockers:")
    out += [
        f"- [{b.kind}; {b.basis}] {b.description} ({', '.join(b.evidence_ids)})"
        for b in inv.blockers
    ] or ["- (none)"]

    out.append("\nContradictions (unresolved; a person decides):")
    out += [
        f"- A: {c.claim_a.text} ({', '.join(c.claim_a.evidence_ids)}) vs "
        f"B: {c.claim_b.text} ({', '.join(c.claim_b.evidence_ids)}). {c.why}"
        for c in inv.conflicts
    ] or ["- (none)"]

    out.append("\nGaps:")
    out += [f"- {g.what_missing} (matters: {g.why_it_matters})" for g in inv.gaps] or [
        "- (none)"
    ]

    out.append("\nSuggested actions:")
    out += [f"- {a.title}: {a.rationale}" for a in inv.actions] or ["- (none)"]

    if inv.draft_status != "none":
        out.append(f"\nCustomer draft status: {inv.draft_status}")

    records, omitted = pick_records(inv)
    out.append(f"\nEvidence records ({len(inv.evidence)} total; excerpts shortened):")
    out.append(
        "\n\n".join(render_record(r, EXCERPT_CHARS) for r in records) or "(no evidence)"
    )
    if omitted:
        out.append(
            f"\n({omitted} more records exist. Use get_record or search_records to read them.)"
        )
    return "\n".join(out)
