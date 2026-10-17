"""Checks a search the model asks for before it reaches a connector.

Connectors quote what they are given, so this is not what stops a query from injecting
syntax. It stops a model that has been talked into it, or has wandered, from using the
search box to look something up that has nothing to do with this case (another person's
email address, a pasted record) or to carry data out in the query string. It is code, not
a model, and it fails closed.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from investigator.connectors.privacy import redact_secrets
from investigator.guardrails.context import GuardContext
from investigator.guardrails.output.patterns import PLACEHOLDER
from investigator.guardrails.pii.detect import find, fold

_URL = re.compile(r"(?i)\b(?:https?|ftp|file|data|javascript):|www\.\S+\.\S+")
_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{40,}|\b[0-9a-fA-F]{32,}\b")
_OPERATOR = re.compile(
    r"(?ix)\b(?:in|from|to|cc|bcc|label|deliveredto|rfc822msgid|older_than|newer_than)\s*:"
    r"|\bor\s+1\s*=\s*1\b|--|;\s*(?:drop|delete|update)\b|\bunion\s+select\b|\border\s+by\b"
)
SHINGLE = 8  # words copied in a row from a record: pasting, not searching


@dataclass(frozen=True)
class Refusal:
    rule: str
    message: str


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", fold(text))


def pasted_from(query: str, corpus: Iterable[str]) -> bool:
    """True when the query repeats a run of `SHINGLE` words from one of the records."""
    words = _words(query)
    if len(words) < SHINGLE:
        return False
    grams = {" ".join(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}
    for text in corpus:
        flat = " ".join(_words(text))
        if any(g in flat for g in grams):
            return True
    return False


def screen_search(
    query: str,
    cursor: str | None,
    ctx: GuardContext,
    *,
    corpus: Iterable[str],
    pending_cursors: Collection[str],
) -> Refusal | None:
    """The first reason this search must not run, or None."""
    if PLACEHOLDER.search(query):
        return Refusal(
            "placeholder",
            "QUERY_REJECTED: it contains a placeholder such as <PERSON_1>. Search for the "
            "plain words instead.",
        )
    if redact_secrets(query) != query:
        return Refusal(
            "secret",
            "QUERY_REJECTED: it appears to contain a credential. Search for topics, not secrets.",
        )
    if _URL.search(query) or _BLOB.search(query):
        return Refusal(
            "url_or_blob",
            "QUERY_REJECTED: it contains a web address or an encoded string. Use plain keywords.",
        )
    if _OPERATOR.search(query):
        return Refusal(
            "operator",
            "QUERY_REJECTED: search operators are not allowed. Use plain keywords; the source "
            "is already limited to this case.",
        )
    bound = ctx.run_id is not None or ctx.thread_id is not None
    foreign = (
        [s.value for s in find(query) if f"{s.kind}:{s.norm}" not in ctx.shown]
        if bound
        else []
    )
    if foreign:
        return Refusal(
            "foreign_identifier",
            "QUERY_REJECTED: it names an email address, number or account that this "
            "investigation has not shown you. Search only for what the case mentions.",
        )
    if pasted_from(query, corpus):
        return Refusal(
            "pasted_record",
            "QUERY_REJECTED: it repeats long text from a record. Use a few distinctive keywords.",
        )
    if cursor is not None and cursor not in pending_cursors:
        return Refusal(
            "unknown_cursor",
            "QUERY_REJECTED: that page cursor was not given by an earlier result.",
        )
    return None
