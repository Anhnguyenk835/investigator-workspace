"""Find personal and account identifiers in text. Pure code, no model.

Contact details and account numbers are found by shape (and checked, where the shape has a
check digit); people's names are not: a name is only found by looking it up (see names.py).
Dates, amounts, company names, ticket keys and URLs are not identifiers here: the model needs
them to reason, and they are not what these checks are for.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

EMAIL, PHONE, IBAN, ACCT, TAXID, PERSON = (
    "EMAIL",
    "PHONE",
    "IBAN",
    "ACCT",
    "TAXID",
    "PERSON",
)
KINDS = (EMAIL, PHONE, IBAN, ACCT, TAXID, PERSON)


@dataclass(frozen=True)
class Span:
    kind: str
    start: int
    end: int
    value: str

    @property
    def norm(self) -> str:
        return normalize(self.kind, self.value)


_EMAIL = re.compile(
    r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_PHONE = re.compile(
    r"""(?x)
    (?<![\w.])(?:
        \+\d{1,3}[\s.-]?(?:\(\d{1,4}\)[\s.-]?)?\d[\d\s.-]{5,14}\d      # international
      | \(\d{2,4}\)[\s.-]?\d{3,4}[\s.-]?\d{3,4}                        # (415) 555-0100
      | \d{2,4}[\s.-]\d{3,4}[\s.-]\d{3,4}(?:[\s.-]\d{2,4})?            # 415-555-0100
      | 0\d{9,10}                                                      # local, leading 0
    )(?![\w])
    """
)
_DATE = re.compile(r"^\d{4}[-./]\d{1,2}[-./]\d{1,2}$|^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}$")
_KEYED = re.compile(
    r"""(?ix)
    (?P<key>account\s*(?:no\.?|number|num\.?|\#)?|acct\.?|a/c|tax\s*id|tin|ein|vat\s*(?:no\.?|number)?|
       mst|mã\s*số\s*thuế|stk|số\s*tài\s*khoản|số\s*tk)
    \s*[:#=]?\s*
    (?P<val>[A-Z0-9][A-Z0-9 -]{4,22}[A-Z0-9])
    """
)
_TAXKEYS = re.compile(r"(?i)tax|tin|ein|vat|mst|thuế")


def _iban_ok(s: str) -> bool:
    s = s.replace(" ", "")
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    digits = "".join(str(int(c, 36)) for c in moved)
    return int(digits) % 97 == 1


def _phone_ok(s: str) -> bool:
    digits = re.sub(r"\D", "", s)
    if not 8 <= len(digits) <= 15 or _DATE.match(s.strip()):
        return False
    # A Slack timestamp, an epoch, a Jira-style run of digits: not a number to call.
    return not re.fullmatch(r"\d{10}\.\d{3,6}", s.strip())


def fold(text: str) -> str:
    """Lower-case with diacritics removed, so `Nguyễn` and `nguyen` compare equal."""
    base = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in base if unicodedata.category(c) != "Mn").casefold()


def normalize(kind: str, value: str) -> str:
    if kind == EMAIL:
        return value.strip().lower()
    if kind == PHONE:
        digits = re.sub(r"\D", "", value)
        return digits[-9:] if len(digits) > 9 else digits
    if kind in (IBAN, ACCT, TAXID):
        return re.sub(r"[\s-]", "", value).upper()
    return re.sub(r"\s+", " ", fold(value)).strip()


def find(text: str) -> list[Span]:
    """Identifiers by shape, longest and most specific first, never overlapping."""
    found: list[Span] = []
    for m in _EMAIL.finditer(text):
        found.append(Span(EMAIL, m.start(), m.end(), m.group()))
    for m in _IBAN.finditer(text):
        if _iban_ok(m.group()):
            found.append(Span(IBAN, m.start(), m.end(), m.group()))
    for m in _KEYED.finditer(text):
        val = m.group("val")
        if sum(c.isdigit() for c in val) >= 5:
            kind = TAXID if _TAXKEYS.search(m.group("key")) else ACCT
            found.append(Span(kind, m.start("val"), m.end("val"), val))
    for m in _PHONE.finditer(text):
        if _phone_ok(m.group()):
            found.append(Span(PHONE, m.start(), m.end(), m.group()))
    found.sort(key=lambda s: (s.start, -(s.end - s.start)))
    out: list[Span] = []
    for s in found:
        if out and s.start < out[-1].end:
            continue
        out.append(s)
    return out


@lru_cache(maxsize=128)
def shown_in(text: str) -> frozenset[str]:
    """Normalised identifiers present in `text`, for 'was the model ever given this?'."""
    return frozenset(f"{s.kind}:{s.norm}" for s in find(text))
