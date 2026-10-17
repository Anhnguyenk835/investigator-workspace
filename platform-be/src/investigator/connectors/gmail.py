"""Gmail (REST API), read-only. Searches the signed-in user's own mailbox with
Gmail's own query syntax, so the server does the matching and `threadId` groups
conversations. Sent time is Gmail's `internalDate` (when it was received)."""

from __future__ import annotations

import base64
import re
from datetime import UTC, datetime
from email.utils import getaddresses, parseaddr
from typing import Any

import httpx

from investigator.connectors.base import EvidenceRecord, SearchQuery, SearchResult
from investigator.connectors.documents import extract_text, supported
from investigator.connectors.support import (
    PAGE_SIZE,
    LiveConnector,
    done,
    gather_limited,
    html_to_text,
    in_bounds,
    padded,
    record,
    search_terms,
    window_bounds,
)
from investigator.directory import SourceFilter
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext

NAME = "gmail"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
PART = re.compile(r"^[0-9][0-9.]{0,20}$")
MAX_ATTACHMENTS_PER_THREAD = 3


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
        "utf-8", "replace"
    )


def _parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out = [payload]
    for child in payload.get("parts", []) or []:
        out += _parts(child)
    return out


def body_text(payload: dict[str, Any]) -> str:
    """Plain text part if there is one, else the HTML part flattened."""
    parts = _parts(payload)
    for wanted in ("text/plain", "text/html"):
        texts = [
            _decode(p["body"]["data"])
            for p in parts
            if p.get("mimeType") == wanted
            and p.get("body", {}).get("data")
            and not p.get("filename")
        ]
        if texts:
            joined = "\n".join(texts)
            return html_to_text(joined) if wanted == "text/html" else joined.strip()
    return ""


def readable_attachments(msg: dict[str, Any]) -> list[dict[str, Any]]:
    """Attached files of a kind this product can read as text."""
    return [
        p
        for p in _parts(msg.get("payload", {}))
        if p.get("filename")
        and p.get("partId")
        and p.get("body", {}).get("attachmentId")
        and supported(p.get("mimeType", ""), p["filename"])
    ]


def attachment_record(
    msg: dict[str, Any], part: dict[str, Any], text: str
) -> EvidenceRecord:
    """A document attached to a message, as a record of its own that cites the same thread."""
    mail = message_record(msg)
    return record(
        id=f"{mail.id}:att:{part['partId']}",
        source=NAME,
        title=part["filename"],
        author=mail.author,
        author_id=mail.author_id,
        participants=mail.participants,
        occurred_at=mail.occurred_at,
        timestamp_precision=mail.timestamp_precision,
        excerpt=f'Attachment "{part["filename"]}" of the email "{mail.title}"\n\n{text}',
        url=mail.url,
        thread_id=mail.thread_id,
        meta={"kind": "attachment", "thread": "multi"},
    )


def message_record(msg: dict[str, Any]) -> EvidenceRecord:
    payload = msg.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    name, addr = parseaddr(headers.get("from", ""))
    author = name or addr or None
    recipients = [
        a for _, a in getaddresses([headers.get("to", ""), headers.get("cc", "")]) if a
    ]
    attachments = [p["filename"] for p in _parts(payload) if p.get("filename")]
    when = (
        datetime.fromtimestamp(int(msg["internalDate"]) / 1000, UTC)
        if msg.get("internalDate")
        else None
    )
    subject = headers.get("subject", "(no subject)")
    lines = [
        f"From: {name} <{addr}>" if name else f"From: {addr}",
        f"Subject: {subject}",
    ]
    if recipients:
        lines.append("To/Cc: " + ", ".join(recipients))
    if attachments:
        lines.append("Attachments: " + ", ".join(attachments))
    text = body_text(payload) or msg.get("snippet", "")
    lines += ["", text]
    return record(
        id=f"{NAME}:{msg['id']}",
        source=NAME,
        title=subject,
        author=author,
        author_id=addr or None,
        participants=recipients,
        occurred_at=when,
        timestamp_precision="exact" if when else "unknown",
        excerpt="\n".join(lines),
        url=f"https://mail.google.com/mail/u/0/#all/{msg['id']}",
        thread_id=f"{NAME}:{msg['threadId']}" if msg.get("threadId") else None,
    )


class GmailConnector(LiveConnector):
    name = NAME
    provider = "google"
    label = "Gmail"

    def __init__(
        self, tokens: TokenProvider, http: httpx.AsyncClient, *, label: str = ""
    ) -> None:
        super().__init__(tokens, http)
        if label and not re.fullmatch(r"[\w .@/-]+", label):
            raise ValueError("GMAIL_LABEL contains unsupported characters")
        self._label = label.strip()

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        terms = [f'"{t}"' for t in search_terms(query.text)]
        f = self.case_filter(ctx)
        scope = self._scope_clause(f)
        if scope:
            terms.append(scope)
        elif self._label:
            terms.append(f'label:"{self._label}"')
        # Gmail's after:/before: are whole days in the account's zone: pad, then filter exactly.
        if query.date_from:
            terms.append(f"after:{padded(query.date_from, -1):%Y/%m/%d}")
        if query.date_to:
            terms.append(f"before:{padded(query.date_to, 2):%Y/%m/%d}")
        params: dict[str, Any] = {"q": " ".join(terms), "maxResults": PAGE_SIZE}
        if query.cursor:
            params["pageToken"] = query.cursor
        listing = await self._get(f"{API}/messages", token, params)
        ids = [m["id"] for m in listing.get("messages", [])]
        messages = await gather_limited(ids, lambda i: self._message(token, i))
        bounds = window_bounds(query)
        records = [
            r for r in map(message_record, messages) if in_bounds(r.occurred_at, bounds)
        ]
        records.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        note = (
            "No label or customer domain is mapped to this case, so the search was not narrowed."
            if f is not None and f.is_empty()
            else None
        )
        return done(NAME, records, listing.get("nextPageToken"), detail=note)

    @staticmethod
    def _scope_clause(f: SourceFilter | None) -> str:
        """Mail that carries one of the case's labels or involves one of its domains."""
        if f is None or f.is_empty():
            return ""
        parts = [f'label:"{x}"' for x in f.gmail_labels]
        for domain in f.gmail_domains:
            d = domain.lstrip("@")
            parts += [f"from:@{d}", f"to:@{d}", f"cc:@{d}"]
        return "(" + " OR ".join(parts) + ")"

    async def _suggest(self, token: str, ctx: AccessContext) -> list[dict[str, str]]:
        data = await self._get(f"{API}/labels", token)
        return [
            {"id": x["name"], "label": x["name"]}
            for x in data.get("labels", [])
            if x.get("type") == "user" and x.get("name")
        ]

    async def _message(self, token: str, message_id: str) -> dict[str, Any]:
        data: dict[str, Any] = await self._get(
            f"{API}/messages/{message_id}", token, {"format": "full"}
        )
        return data

    async def _attachment_text(
        self, token: str, msg: dict[str, Any], part: dict[str, Any]
    ) -> str | None:
        data = await self._get(
            f"{API}/messages/{msg['id']}/attachments/{part['body']['attachmentId']}",
            token,
        )
        raw = data.get("data")
        if not isinstance(raw, str):
            return None
        blob = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        return extract_text(part.get("mimeType", ""), part["filename"], blob)

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        native = record_id.removeprefix(f"{NAME}:")
        if ":att:" in native:
            message_id, _, part_id = native.partition(":att:")
            if not ID.match(message_id) or not PART.match(part_id):
                return done(
                    NAME, [], detail=f"{record_id} is not a Gmail attachment id."
                )
            msg = await self._message(token, message_id)
            part = next(
                (p for p in readable_attachments(msg) if p.get("partId") == part_id),
                None,
            )
            if part is None:
                return done(
                    NAME, [], detail="That attachment is not a readable document."
                )
            text = await self._attachment_text(token, msg, part)
            if text is None:
                return done(
                    NAME,
                    [],
                    partial=True,
                    detail="The attachment could not be read as text.",
                )
            return done(NAME, [attachment_record(msg, part, text)])
        if not ID.match(native):
            return done(NAME, [], detail=f"{record_id} is not a Gmail message id.")
        return done(NAME, [message_record(await self._message(token, native))])

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        native = thread_id.removeprefix(f"{NAME}:")
        if not ID.match(native):
            return done(NAME, [], detail=f"{thread_id} is not a Gmail thread id.")
        thread = await self._get(f"{API}/threads/{native}", token, {"format": "full"})
        messages = thread.get("messages", [])
        records = [message_record(m) for m in messages]
        # Documents attached to the thread are evidence too (a form, a contract draft).
        pending = [(m, p) for m in messages for p in readable_attachments(m)]
        skipped = 0
        for m, p in pending[:MAX_ATTACHMENTS_PER_THREAD]:
            text = await self._attachment_text(token, m, p)
            if text is None:
                skipped += 1
            else:
                records.append(attachment_record(m, p, text))
        extra = max(0, len(pending) - MAX_ATTACHMENTS_PER_THREAD) + skipped
        records.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        return done(
            NAME,
            records,
            partial=extra > 0,
            detail=f"{extra} attachment(s) were not read (too many, too large or not text)."
            if extra
            else None,
        )
