"""People's names can't be found by shape, so they are looked up.

The names come from where the system already knows them: the sender and recipient names the
connectors read, the people in the directory. A name that appears only in running text, and
is nowhere in that metadata, is not found. That limit is real and the evaluation measures it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from investigator.guardrails.pii.detect import PERSON, Span, fold

# Words that are names of groups or tools, or ordinary words, more than people.
NOT_A_PERSON = frozenset(
    [
        "support",
        "team",
        "admin",
        "administrator",
        "client",
        "customer",
        "system",
        "bot",
        "jira",
        "slack",
        "notion",
        "confluence",
        "gmail",
        "noreply",
        "no-reply",
        "service",
        "ops",
        "billing",
        "sales",
        "finance",
        "hr",
        "it",
        "helpdesk",
        "unknown",
        "anonymous",
        "everyone",
        "all",
        "staff",
        "user",
        "users",
        "owner",
        "manager",
        "reviewer",
        "assistant",
    ]
)
# First names that are also everyday words: never matched on their own.
COMMON_WORDS = frozenset(
    [
        "will",
        "mark",
        "grace",
        "may",
        "rob",
        "bill",
        "rose",
        "hope",
        "art",
        "pat",
        "sue",
        "ray",
        "jack",
        "bob",
        "jean",
        "guy",
        "dean",
        "case",
        "page",
        "long",
        "young",
        "king",
        "bell",
        "price",
        "smith",
    ]
)
_AUTHOR = re.compile(r'\bauthor="([^"\n]{2,80})"')
_HEADER = re.compile(r'(?m)^(?:From|To|Cc|Bcc):\s*"?([^<\n",@]{2,60}?)"?\s*<[^>\n]+>')
_SIGNOFF = re.compile(
    r"(?im)^(?:best regards|kind regards|regards|best|thanks|thank you|cheers|sincerely|"
    r"trân trọng|thân ái|cảm ơn)[,.!]?\s*\n\s*([A-ZÀ-Ỹ][\w'’.-]+(?: [A-ZÀ-Ỹ][\w'’.-]+){0,3})\s*$"
)


def plausible(name: str) -> bool:
    name = " ".join(name.split())
    if len(name) < 3 or "@" in name or sum(c.isdigit() for c in name) > 0:
        return False
    parts = name.split()
    if any(fold(p) in NOT_A_PERSON for p in parts):
        return False
    return not (
        len(parts) == 1 and (fold(parts[0]) in COMMON_WORDS or not name[0].isupper())
    )


def names_in(text: str) -> set[str]:
    """Names the text itself tells us: the author of a record, the display name in a
    From/To line, the name under a sign-off."""
    found = {m.group(1).strip() for m in _AUTHOR.finditer(text)}
    found |= {m.group(1).strip() for m in _HEADER.finditer(text)}
    found |= {m.group(1).strip() for m in _SIGNOFF.finditer(text)}
    return {n for n in found if plausible(n)}


def directory_names(directory: object | None) -> set[str]:
    """Names (and aliases) of the people the directory lists."""
    out: set[str] = set()
    for person in getattr(directory, "people", None) or []:
        for n in [person.name, *person.aliases]:
            if plausible(n):
                out.add(" ".join(n.split()))
    return out


def fold_with_map(text: str) -> tuple[str, list[int]]:
    """`fold(text)` and, for each folded character, where it came from in `text`."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        piece = fold(ch)
        out.append(piece)
        index.extend([i] * len(piece))
    return "".join(out), index


@dataclass(frozen=True)
class _Entry:
    canonical: str  # folded full name: the placeholder key
    alias: bool


class NameMatcher:
    """Finds the registered people in text. Full names match any case and ignore accents;
    a first or last name on its own matches only when it is unambiguous among the people
    registered, is capitalised in the text, and is not an everyday word."""

    def __init__(self, names: set[str]) -> None:
        self._entries: dict[str, _Entry] = {}
        owners: dict[str, set[str]] = {}
        for raw in sorted(names):
            full = " ".join(raw.split())
            canon = fold(full)
            if len(canon) < 3:
                continue
            self._entries[canon] = _Entry(canon, False)
            parts = [p for p in full.split() if len(p) >= 3]
            if len(parts) > 1:
                for p in parts:
                    if fold(p) not in COMMON_WORDS and fold(p) not in NOT_A_PERSON:
                        owners.setdefault(fold(p), set()).add(canon)
        for token, who in owners.items():
            if len(who) == 1 and token not in self._entries:
                self._entries[token] = _Entry(next(iter(who)), True)
        keys = sorted(self._entries, key=len, reverse=True)
        self._pattern = (
            re.compile(
                r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keys) + r")(?!\w)"
            )
            if keys
            else None
        )

    def find(self, text: str) -> list[Span]:
        if self._pattern is None:
            return []
        folded, index = fold_with_map(text)
        spans: list[Span] = []
        for m in self._pattern.finditer(folded):
            entry = self._entries[m.group()]
            start, end = index[m.start()], index[m.end() - 1] + 1
            if entry.alias and not text[start].isupper():
                continue
            spans.append(Span(PERSON, start, end, text[start:end]))
        return spans

    def canonical(self, surface: str) -> str:
        entry = self._entries.get(fold(" ".join(surface.split())))
        return entry.canonical if entry else fold(surface)
