"""Notion, read-only. The token sees only the pages the user shared with the app at
consent, and Notion's search endpoint matches page and database titles, not body
text. Both limits are stated in the coverage detail instead of implied away."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from investigator.connectors.base import EvidenceRecord, SearchQuery, SearchResult
from investigator.connectors.support import (
    PAGE_SIZE,
    LiveConnector,
    SourceHttpError,
    done,
    in_bounds,
    record,
    window_bounds,
)
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext

NAME = "notion"
API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
UUID = re.compile(
    r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
)
TITLES_ONLY = "Notion search matches page titles only, not text inside pages."
SHARED_ONLY = "Only pages shared with this connection are visible."
MAX_BLOCK_PAGES = 3
MAX_CHILD_FETCHES = 15


def rich(parts: list[dict[str, Any]] | None) -> str:
    return "".join(p.get("plain_text", "") for p in parts or [])


def page_title(obj: dict[str, Any]) -> str:
    if obj.get("object") == "database":
        return rich(obj.get("title")) or "(untitled database)"
    for prop in (obj.get("properties") or {}).values():
        if prop.get("type") == "title":
            return rich(prop.get("title")) or "(untitled)"
    return "(untitled)"


def block_text(block: dict[str, Any]) -> str:
    kind = block.get("type", "")
    body = block.get(kind) or {}
    text = rich(body.get("rich_text"))
    if kind == "to_do":
        return f"[{'x' if body.get('checked') else ' '}] {text}"
    if kind in {"bulleted_list_item", "numbered_list_item"}:
        return f"- {text}"
    if kind.startswith("heading_"):
        return f"\n{text}"
    if kind == "child_page":
        return f"(sub-page: {body.get('title', '')})"
    return text


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def object_record(
    obj: dict[str, Any], body: str = "", author: str | None = None
) -> EvidenceRecord:
    when = parse_time(obj.get("last_edited_time"))
    title = page_title(obj)
    text = title + (
        f"\n\n{body}" if body else "\n\n[Title only. Read the page for its content.]"
    )
    return record(
        id=f"{NAME}:{obj['id']}",
        source=NAME,
        title=title,
        author=author,
        occurred_at=when,
        timestamp_precision="exact" if when else "unknown",
        excerpt=text,
        url=obj.get("url"),
        thread_id=f"{NAME}:{obj['id']}",
    )


class NotionConnector(LiveConnector):
    name = NAME
    provider = "notion"
    label = "Notion"

    def __init__(self, tokens: TokenProvider, http: httpx.AsyncClient) -> None:
        super().__init__(tokens, http)

    async def _call(
        self,
        method: str,
        path: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        return await self._request(
            method,
            f"{API}{path}",
            token,
            params=params,
            json=json,
            headers={"Notion-Version": VERSION},
        )

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        body: dict[str, Any] = {
            "query": query.text,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
            "page_size": PAGE_SIZE,
        }
        if query.cursor:
            body["start_cursor"] = query.cursor
        data = await self._call("POST", "/search", token, json=body)
        bounds = window_bounds(query)
        start = bounds[0]
        results = data.get("results", [])
        records = [
            object_record(o)
            for o in results
            if in_bounds(parse_time(o.get("last_edited_time")), bounds)
        ]
        # Newest first: once a page is older than the window, nothing after it can match.
        past_window = bool(
            start
            and results
            and (parse_time(results[-1].get("last_edited_time")) or start) < start
        )
        more = (
            None if past_window or not data.get("has_more") else data.get("next_cursor")
        )
        note = f"{TITLES_ONLY} {SHARED_ONLY}"
        if not records and not more:
            # Zero title matches does not mean the text is not in a page.
            return done(NAME, [], detail=note, partial=True)
        return done(NAME, records, more, detail=note)

    async def _blocks(self, token: str, block_id: str) -> tuple[list[str], bool]:
        lines: list[str] = []
        fetches = 0
        capped = False

        async def walk(parent: str, depth: int) -> None:
            nonlocal fetches, capped
            params: dict[str, Any] = {"page_size": 100}
            for _ in range(MAX_BLOCK_PAGES):
                data = await self._call(
                    "GET", f"/blocks/{parent}/children", token, params=params
                )
                for block in data.get("results", []):
                    text = block_text(block)
                    if text.strip():
                        lines.append("  " * depth + text)
                    if block.get("has_children") and block.get("type") != "child_page":
                        if depth >= 1 or fetches >= MAX_CHILD_FETCHES:
                            capped = (
                                capped or depth >= 1 or fetches >= MAX_CHILD_FETCHES
                            )
                            continue
                        fetches += 1
                        await walk(block["id"], depth + 1)
                if not data.get("has_more"):
                    return
                params["start_cursor"] = data["next_cursor"]
            capped = True

        await walk(block_id, 0)
        return lines, capped

    async def _author(self, token: str, user_id: str | None) -> str | None:
        if not user_id:
            return None
        try:
            user = await self._call("GET", f"/users/{user_id}", token)
        except SourceHttpError:
            return None  # the app may lack user-read capability
        name = user.get("name")
        return str(name) if name else None

    async def _page(self, token: str, native: str) -> tuple[EvidenceRecord, bool]:
        obj = await self._call("GET", f"/pages/{native}", token)
        lines, capped = await self._blocks(token, native)
        author = await self._author(token, (obj.get("created_by") or {}).get("id"))
        return object_record(obj, "\n".join(lines), author), capped

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        native = record_id.removeprefix(f"{NAME}:").split(":")[0]
        if not UUID.match(native):
            return done(NAME, [], detail=f"{record_id} is not a Notion page id.")
        rec, capped = await self._page(token, native)
        return done(
            NAME,
            [rec],
            partial=capped,
            detail="The page is larger or more deeply nested than was read."
            if capped
            else None,
        )

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        native = thread_id.removeprefix(f"{NAME}:")
        if not UUID.match(native):
            return done(NAME, [], detail=f"{thread_id} is not a Notion page id.")
        rec, capped = await self._page(token, native)
        records = [rec]
        note = (
            "The page is larger or more deeply nested than was read."
            if capped
            else None
        )
        try:
            data = await self._call(
                "GET", "/comments", token, params={"block_id": native, "page_size": 100}
            )
        except SourceHttpError as exc:
            if exc.status not in (400, 403):
                raise
            return done(
                NAME,
                records,
                partial=True,
                detail="Comments are not available to this connection.",
            )
        for c in data.get("results", []):
            when = parse_time(c.get("created_time"))
            records.append(
                record(
                    id=f"{NAME}:{native}:comment:{c['id']}",
                    source=NAME,
                    title=f"Comment on {rec.title}",
                    occurred_at=when,
                    timestamp_precision="exact" if when else "unknown",
                    excerpt=rich(c.get("rich_text")),
                    url=rec.url,
                    thread_id=f"{NAME}:{native}",
                )
            )
        records.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        if data.get("has_more"):
            note = (note + " " if note else "") + "More comments exist than were read."
        return done(
            NAME, records, partial=bool(capped or data.get("has_more")), detail=note
        )
