"""Marking what is data and what is instruction, in text sent to a model.

Anything a third party wrote goes inside a tag the prompt says is data. The tag names are
fixed, so a record that contains one of them would be able to close its own wrapper: every
lookalike inside content is therefore defused, not just the closing tag. A nonce would add
nothing on top of that — content that cannot contain the delimiter cannot forge it.
"""

from __future__ import annotations

import re

from investigator.guardrails.injection.scan import HIDDEN

TAGS = "record|options|untrusted[\\w-]*|user-input|derived-notes|system|assistant|developer"
_LOOKALIKE = re.compile(rf"<(?=\s*/?\s*(?:{TAGS})\b)", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ATTR_MAX = 160


def neutralize(text: str) -> str:
    """Invisible characters out, and any tag that imitates one of ours defused (`</record`
    becomes `<\\/record`)."""
    text = HIDDEN.sub("", text)
    text = _CONTROL.sub("", text)
    return _LOOKALIKE.sub("<\\\\", text)


def attr(value: str, limit: int = ATTR_MAX) -> str:
    """A value safe inside `name="..."`: no quotes, angle brackets, newlines or control characters."""
    value = HIDDEN.sub("", value)
    value = _CONTROL.sub("", value)
    value = value.replace('"', "'").replace("\n", " ").replace("\r", " ")
    value = value.replace("<", "‹").replace(">", "›")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def user_block(text: str) -> str:
    """What a person typed: it says what they want, and cannot change the rules."""
    return f"<user-input>\n{neutralize(text)}\n</user-input>"


def derived_block(text: str) -> str:
    """Notes the system itself wrote from records: only as trustworthy as those records."""
    return f"<derived-notes>\n{neutralize(text)}\n</derived-notes>"
