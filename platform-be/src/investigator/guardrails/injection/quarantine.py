"""Takes instruction-like passages out of what the model reads, and keeps the original
for people.

The record's `excerpt` is never changed: a reviewer must be able to see exactly what was
written, including the part that was withheld, with a warning beside it. What changes is the
copy the model is given (`model_excerpt`) and how far the record is trusted (`trust`).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from investigator.connectors.base import EvidenceRecord, QuarantinedSpan
from investigator.guardrails.injection.scan import Hit, scan, strip_hidden, verdict

if TYPE_CHECKING:
    from investigator.guardrails.runtime import GuardRuntime

REMOVED = "[removed: possible instruction aimed at an AI]"
WITHHELD = "[content withheld: most of this record is instructions aimed at an AI]"
WITHHELD_FRACTION = 0.5
SUSPECT_AFTER = 3  # records in one run that carried instructions


class Decisions:
    """Remembers what was decided for a record's exact content (it is read many times)."""

    def __init__(self, size: int = 4000) -> None:
        self._d: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
        self._size = size

    def get(self, key: tuple[str, int]) -> dict[str, Any] | None:
        got = self._d.get(key)
        if got is not None:
            self._d.move_to_end(key)
        return got

    def put(self, key: tuple[str, int], value: dict[str, Any]) -> None:
        self._d[key] = value
        while len(self._d) > self._size:
            self._d.popitem(last=False)


def _cut(text: str, spans: list[Hit]) -> str:
    out: list[str] = []
    at = 0
    for h in sorted(spans, key=lambda h: h.start):
        out.append(text[at : h.start])
        out.append(REMOVED)
        at = h.end
    out.append(text[at:])
    return "".join(out)


async def protect(rec: EvidenceRecord, guard: GuardRuntime) -> EvidenceRecord:
    mode = guard.mode("injection")
    if mode == "off":
        return rec
    enforce = mode == "enforce"
    key = (rec.id, hash((rec.excerpt, rec.title, rec.author, mode)))
    cached = guard.decisions.get(key)
    if cached is not None:
        return rec.model_copy(update=cached) if cached else rec

    clean, index = strip_hidden(rec.excerpt)
    high, band = verdict(scan(clean))
    unresolved = 0
    for hit in band:
        snippet = clean[hit.start : hit.end]
        decided = await guard.classifier(snippet) if guard.classifier else None
        if decided is True:
            high.append(Hit(hit.start, hit.end, hit.rule + "+model", 1.0))
        elif decided is None:
            unresolved += 1
    title_hit = bool(verdict(scan(strip_hidden(rec.title)[0], expand=False))[0])
    author_hit = bool(
        rec.author and verdict(scan(strip_hidden(rec.author)[0], expand=False))[0]
    )

    if not (high or unresolved or title_hit or author_hit):
        guard.decisions.put(key, {})
        return rec

    for hit in high:
        await guard.emit(
            "injection",
            hit.rule,
            enforced=enforce,
            action="quarantine",
            severity="high",
            record_id=rec.id,
            detail=clean[hit.start : hit.end][:80].replace("\n", " "),
        )
    for _ in range(unresolved):
        await guard.emit(
            "injection",
            "uncertain",
            enforced=enforce,
            action="downgrade",
            severity="medium",
            record_id=rec.id,
        )
    for field, hit_ in (("title", title_hit), ("author", author_hit)):
        if hit_:
            await guard.emit(
                "injection",
                f"{field}_instruction",
                enforced=enforce,
                action="quarantine",
                severity="high",
                record_id=rec.id,
            )

    spans = [
        QuarantinedSpan(
            start=index[h.start], end=index[min(h.end, len(index)) - 1] + 1, rule=h.rule
        )
        for h in sorted(high, key=lambda h: h.start)
        if index
    ]
    # Text the rules were sure about is removed (enforce) and lowers trust. Text they were
    # unsure about, and nobody could settle, is only marked for the reviewer: an uncertain
    # match is not evidence of an attack.
    removed = bool(high or title_hit or author_hit)
    update: dict[str, Any] = {
        "quarantine": spans,
        "trust": "tainted" if enforce and removed else "flagged",
    }
    if enforce:
        flagged_chars = sum(h.end - h.start for h in high)
        if clean and flagged_chars > WITHHELD_FRACTION * len(clean):
            update["model_excerpt"] = WITHHELD
        elif high:
            update["model_excerpt"] = _cut(clean, high)
        if title_hit:
            update["model_title"] = REMOVED
        if author_hit:
            update["model_author"] = "[name removed]"
    guard.decisions.put(key, update)
    await guard.note_suspect(rec.id, high_count=len(high) + title_hit + author_hit)
    return rec.model_copy(update=update)
