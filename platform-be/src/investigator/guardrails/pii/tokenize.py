"""Swap personal identifiers for placeholders on the way to a model, and back on the way out.

`<PERSON_1>` names the same person for the whole of one call (and, with a shared alias book,
the whole investigation). The text a person reads is always the restored one: nothing in
state, in a checkpoint or on screen ever holds a placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from investigator.guardrails.pii.aliases import AliasBook
from investigator.guardrails.pii.detect import (
    ACCT,
    EMAIL,
    IBAN,
    PERSON,
    PHONE,
    TAXID,
    Span,
    find,
    normalize,
)
from investigator.guardrails.pii.names import NameMatcher

TAGS = {
    EMAIL: "EMAIL",
    PHONE: "PHONE",
    IBAN: "IBAN",
    ACCT: "ACCT",
    TAXID: "TAXID",
    PERSON: "PERSON",
}
KINDS = tuple(TAGS.values())

# Structure the model must get back unchanged: citations, record attributes, web addresses.
_PROTECTED = re.compile(
    r"""\[E:[^\]\s]+\]
      | \b(?:id|thread|source|time|precision|side)="[^"\n]*"
      | https?://[^\s<>"')\]]+
    """,
    re.VERBOSE,
)
_HOLD = 24  # longest a possible placeholder is held back while streaming
# `<PERSON_3>`, and `<PERSON_3b>` for a second way the same person was written (a first name
# on its own, another spelling), so that restoring gives back exactly what was there.
_BRACKETED = re.compile(
    r"<\s*(" + "|".join(KINDS) + r")[\s_-]*(\d+)([a-z]?)\s*>", re.IGNORECASE
)
_BARE = re.compile(r"(?<![\w<])(" + "|".join(KINDS) + r")_(\d+)([a-z]?)(?![\w])")
FORMS = "abcdefghijklmnopqrstuvwxyz"


@dataclass
class ReverseMap:
    """What each placeholder stood for in one call."""

    values: dict[tuple[str, int, str], str] = field(default_factory=dict)
    unknown: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    _forms: dict[tuple[str, int], list[str]] = field(default_factory=dict)

    def form(self, kind: str, n: int, surface: str) -> str:
        """The suffix for this way of writing the value: empty for the first seen."""
        key = surface.lower() if kind == "EMAIL" else surface
        forms = self._forms.setdefault((kind, n), [])
        if key not in forms:
            forms.append(key)
            suffix = "" if len(forms) == 1 else FORMS[min(len(forms) - 1, 25)]
            self.values[(kind, n, suffix)] = surface
        idx = forms.index(key)
        return "" if idx == 0 else FORMS[min(idx, 25)]

    def restore(self, text: str) -> str:
        if not self.values and "<" not in text:
            return text

        def lookup(m: re.Match[str]) -> str | None:
            return self.values.get(
                (m.group(1).upper(), int(m.group(2)), m.group(3).lower())
            )

        def known(m: re.Match[str]) -> str:
            got = lookup(m)
            return got if got is not None else m.group()

        def unknown(m: re.Match[str]) -> str:
            if lookup(m) is None:
                self.unknown += 1
            return known(m)

        text = _BRACKETED.sub(unknown, text)
        return _BARE.sub(known, text)

    def restore_json(self, obj: object) -> object:
        if isinstance(obj, str):
            return self.restore(obj)
        if isinstance(obj, list):
            return [self.restore_json(x) for x in obj]
        if isinstance(obj, dict):
            return {k: self.restore_json(v) for k, v in obj.items()}
        return obj


async def tokenize_text(
    text: str,
    scope: str,
    book: AliasBook,
    reverse: ReverseMap,
    matcher: NameMatcher | None,
) -> str:
    protected = [(m.start(), m.end()) for m in _PROTECTED.finditer(text)]

    def clear(s: Span) -> bool:
        return not any(s.start < e and s.end > b for b, e in protected)

    spans = [s for s in find(text) if clear(s)]
    if matcher is not None:
        spans += [s for s in matcher.find(text) if clear(s)]
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    kept: list[Span] = []
    for s in spans:  # no overlaps: the longest span starting first wins
        if kept and s.start < kept[-1].end:
            continue
        kept.append(s)
    out: list[str] = []
    at = 0
    for s in kept:
        norm = (
            matcher.canonical(s.value)
            if s.kind == PERSON and matcher
            else normalize(s.kind, s.value)
        )
        n = await book.ordinal(scope, s.kind, norm)
        tag = TAGS[s.kind]
        suffix = reverse.form(tag, n, s.value)
        reverse.counts[tag] = reverse.counts.get(tag, 0) + 1
        out.append(text[at : s.start])
        out.append(f"<{tag}_{n}{suffix}>")
        at = s.end
    out.append(text[at:])
    return "".join(out)


class StreamRestorer:
    """`ReverseMap.restore` for text that arrives in pieces: a placeholder cut in two is
    held back until it is whole, so it never appears half-restored."""

    def __init__(self, reverse: ReverseMap) -> None:
        self._rev = reverse
        self._buf = ""

    def feed(self, piece: str) -> str:
        self._buf += piece
        cut = self._hold_from(self._buf)
        ready, self._buf = self._buf[:cut], self._buf[cut:]
        return self._rev.restore(ready)

    def flush(self) -> str:
        ready, self._buf = self._buf, ""
        return self._rev.restore(ready)

    @staticmethod
    def _hold_from(buf: str) -> int:
        for i in range(max(0, len(buf) - _HOLD), len(buf)):
            if _could_become_placeholder(buf[i:]):
                return i
        return len(buf)


def _could_become_placeholder(tail: str) -> bool:
    """True when `tail` is the beginning of `<KIND_n>` or `KIND_n` and not yet complete."""
    s = tail.lstrip("<").lstrip() if tail.startswith("<") else tail
    if not s:
        return tail.startswith("<")
    letters = re.match(r"[A-Za-z]*", s)
    word = letters.group() if letters else ""
    rest = s[len(word) :]
    if not word:
        return False
    upper = word.upper()
    if rest == "":
        return any(k.startswith(upper) for k in KINDS)
    if upper not in KINDS:
        return False
    return bool(re.fullmatch(r"[\s_-]*\d*[A-Za-z]?\s*", rest)) and not (
        tail.startswith("<") and rest.rstrip().endswith(">")
    )


# Added to prompts: the model must hand placeholders back exactly as it was given them.
PLACEHOLDER_RULE = (
    "Placeholders written like <PERSON_N>, <EMAIL_N> or <PHONE_N> (N is a number) stand for "
    "real values that are withheld from you. Copy them exactly when you need to refer to that "
    "person or detail; never guess, invent or change one."
)
