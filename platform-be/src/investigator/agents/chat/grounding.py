"""Checks an answer against the evidence it cites. Pure code, no model."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field

from investigator.guardrails.output.patterns import BLAME

CITE = re.compile(r"\[E:([^\]\s,]+)\]")
# A model often lists several ids in one bracket: [E:a, E:b].
CITE_LIST = re.compile(r"\[(E:[^\]]+)\]")
NEGATION = re.compile(
    r"\b(cannot|can't|can not|not|no|never|neither|nor|without|unable|nothing|none|"
    r"doesn't|does not|isn't|is not|don't|do not)\b",
    re.IGNORECASE,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class Grounded:
    text: str
    citations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _split_lists(text: str) -> str:
    """`[E:a, E:b]` becomes `[E:a][E:b]`, so every id is checked on its own."""

    def one(m: re.Match[str]) -> str:
        parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
        if len(parts) < 2 or not all(p.startswith("E:") for p in parts):
            return m.group(0)
        return "".join(f"[{p}]" for p in parts)

    return CITE_LIST.sub(one, text)


def _blames(text: str) -> bool:
    """A sentence that assigns fault. Saying fault cannot be assigned does not count."""
    return any(
        BLAME.search(sentence) and not NEGATION.search(sentence)
        for sentence in SENTENCE.split(text)
    )


def _is_brief_non_answer(text: str) -> bool:
    """A refusal or "unknown" needs no citation; a claim, figures or length do."""
    return (
        len(text) < 240
        and not re.search(r"\d", text)
        and bool(
            NEGATION.search(text) or re.search(r"\bunknown\b", text, re.IGNORECASE)
        )
    )


def ground(answer: str, known: Collection[str]) -> Grounded:
    """Keep citations that name a real record, drop the rest, and say what is weak.

    A marker the model invented must not reach a reader looking like evidence, so it is
    removed from the text rather than left in with a warning beside it.
    """
    known_ids = set(known)
    cited: list[str] = []
    removed = 0

    def keep(match: re.Match[str]) -> str:
        nonlocal removed
        ident = match.group(1)
        if ident in known_ids:
            if ident not in cited:
                cited.append(ident)
            return match.group(0)
        removed += 1
        return ""

    text = re.sub(r" {2,}", " ", CITE.sub(keep, _split_lists(answer))).strip()
    warnings: list[str] = []
    if removed:
        warnings.append(
            f"{removed} citation{'s' if removed != 1 else ''} named a record that does "
            "not exist and was removed."
        )
    if not cited and not _is_brief_non_answer(text):
        warnings.append("This answer cites no evidence. Treat it as unverified.")
    if _blames(text):
        warnings.append(
            "This answer attributes fault. Evidence of events is not evidence of blame; "
            "check the records yourself."
        )
    return Grounded(text=text, citations=cited, warnings=warnings)


BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


def segments(text: str) -> list[str]:
    """The text cut into sentences and lines; joining them gives the text back."""
    parts: list[str] = []
    last = 0
    for m in BOUNDARY.finditer(text):
        parts.append(text[last : m.end()])
        last = m.end()
    if last < len(text):
        parts.append(text[last:])
    return parts


def markers_in(segment: str) -> list[str]:
    return list(dict.fromkeys(CITE.findall(segment)))


def strip_markers(segment: str, ids: Collection[str]) -> str:
    """Remove the citation markers naming `ids` from one sentence."""
    drop = set(ids)
    out = CITE.sub(lambda m: "" if m.group(1) in drop else m.group(0), segment)
    out = re.sub(r" {2,}", " ", out)
    return re.sub(r"\s+([.,;:!?])", r"\1", out)
