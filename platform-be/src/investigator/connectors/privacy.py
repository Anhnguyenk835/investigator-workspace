"""Safety net applied to every record at the connector boundary, before anything is
stored or shown to a model. Regexes catch common shapes of credentials and card or
government numbers; they are not a guarantee. Contact details are kept: who wrote to
whom is evidence."""

from __future__ import annotations

import re

_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)
_TOKEN = re.compile(
    r"""(?x)
    \bxox[abprs]-[A-Za-z0-9-]{10,}
    | \bsk-[A-Za-z0-9_-]{20,}
    | \bAKIA[0-9A-Z]{16}\b
    | \bgh[pousr]_[A-Za-z0-9]{30,}
    | \bya29\.[\w-]{20,}
    | \bATATT[\w=-]{20,}
    | \bntn_[A-Za-z0-9]{20,}
    | \bsecret_[A-Za-z0-9]{30,}
    | \beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}
    | \bBearer\s+[\w.~+/-]{16,}=*
    """
)
_ASSIGNED = re.compile(
    r"(?i)\b(password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|token)\b"
    r"(\s*[:=]\s*)(?!\[REDACTED)\S+"
)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        total += n * 2 - 9 if i % 2 and n * 2 > 9 else n * 2 if i % 2 else n
    return total % 10 == 0


def _card(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group())
    return (
        "[REDACTED:card]"
        if 13 <= len(digits) <= 19 and _luhn(digits)
        else match.group()
    )


def redact_secrets(text: str) -> str:
    text = _PRIVATE_KEY.sub("[REDACTED:private-key]", text)
    text = _TOKEN.sub("[REDACTED:token]", text)
    text = _ASSIGNED.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
    text = _SSN.sub("[REDACTED:id]", text)
    return _CARD.sub(_card, text)
