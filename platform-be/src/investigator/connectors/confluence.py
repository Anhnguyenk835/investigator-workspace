"""Confluence Cloud (REST v1 through the Atlassian gateway), read-only.

Search returns one record per page with Confluence's excerpt. `get_record` reads the
whole page; `get_thread` adds its comments."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from investigator.connectors.atlassian import cloud_site
from investigator.connectors.base import EvidenceRecord, SearchQuery, SearchResult
from investigator.connectors.support import (
    PAGE_SIZE,
    LiveConnector,
    done,
    html_to_text,
    narrowed,
    padded,
    record,
    scoped,
    search_terms,
)
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext

NAME = "confluence"
CONTENT_ID = re.compile(r"^\d{1,20}$")
HIGHLIGHT = re.compile(r"@@@(?:end)?hl@@@")
EXPAND = "body.storage,version,history,space"
MAX_COMMENT_PAGES = 5


def cql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _link(base: str, links: dict[str, Any]) -> str | None:
    web = links.get("webui")
    return f"{base}/wiki{web}" if base and web else None


def search_record(item: dict[str, Any], site: str) -> EvidenceRecord | None:
    content = item.get("content") or {}
    cid = content.get("id")
    if not cid:
        return None  # spaces, users and attachments are not documents
    when = parse_time(item.get("lastModified"))
    excerpt = HIGHLIGHT.sub("", item.get("excerpt") or "").strip()
    expandable = (content.get("_expandable") or {}).get("space") or ""
    space = expandable.rsplit("/", 1)[-1]
    return record(
        id=f"{NAME}:{cid}",
        source=NAME,
        title=item.get("title") or content.get("title") or "(untitled)",
        meta={"space": space} if space else {},
        occurred_at=when,
        timestamp_precision="exact" if when else "unknown",
        excerpt=(excerpt or "(no excerpt)")
        + "\n\n[Excerpt only. Read the page for its full text.]",
        url=f"{site}/wiki{item['url']}" if site and item.get("url") else None,
        thread_id=f"{NAME}:{cid}",
    )


def page_record(page: dict[str, Any], site: str) -> EvidenceRecord:
    version = page.get("version") or {}
    when = parse_time(version.get("when"))
    author = (version.get("by") or {}).get("displayName")
    body = html_to_text(
        ((page.get("body") or {}).get("storage") or {}).get("value", "")
    )
    space = (page.get("space") or {}).get("name")
    lines = [f"{page.get('title', '')} (version {version.get('number', '?')})"]
    if space:
        lines.append(f"Space: {space}")
    lines += ["", body]
    return record(
        id=f"{NAME}:{page['id']}",
        source=NAME,
        title=page.get("title") or "(untitled)",
        author=author,
        meta={"space": (page.get("space") or {}).get("key", "")}
        if (page.get("space") or {}).get("key")
        else {},
        occurred_at=when,
        timestamp_precision="exact" if when else "unknown",
        excerpt="\n".join(lines),
        url=_link(site, page.get("_links") or {}),
        thread_id=f"{NAME}:{page['id']}",
    )


def comment_record(page_id: str, comment: dict[str, Any], site: str) -> EvidenceRecord:
    version = comment.get("version") or {}
    when = parse_time(version.get("when"))
    return record(
        id=f"{NAME}:{page_id}:comment:{comment['id']}",
        source=NAME,
        title=f"Comment on {page_id}",
        author=(version.get("by") or {}).get("displayName"),
        occurred_at=when,
        timestamp_precision="exact" if when else "unknown",
        excerpt=html_to_text(
            ((comment.get("body") or {}).get("storage") or {}).get("value", "")
        ),
        url=_link(site, comment.get("_links") or {}),
        thread_id=f"{NAME}:{page_id}",
    )


class ConfluenceConnector(LiveConnector):
    name = NAME
    provider = "atlassian"
    label = "Confluence"

    def __init__(
        self,
        tokens: TokenProvider,
        http: httpx.AsyncClient,
        *,
        space_keys: str = "",
        site_url: str = "",
    ) -> None:
        super().__init__(tokens, http)
        self._spaces = scoped(space_keys)
        self._wanted_site = site_url
        for key in self._spaces:
            if not re.fullmatch(r"[~A-Za-z0-9_-]+", key):
                raise ValueError(f"{key!r} is not a Confluence space key")

    def _spaces_for(self, ctx: AccessContext) -> frozenset[str]:
        f = self.case_filter(ctx)
        return narrowed(self._spaces, f.confluence_spaces if f else [])

    async def _base(self, ctx: AccessContext) -> tuple[str, str]:
        cloud_id, url = await cloud_site(
            self._tokens, ctx, self._wanted_site, "Confluence"
        )
        return f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api", url

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        api, site = await self._base(ctx)
        spaces = self._spaces_for(ctx)
        clauses = ["type in (page, blogpost)"]
        if spaces:
            clauses.append(
                "space in (" + ", ".join(cql_quote(s) for s in sorted(spaces)) + ")"
            )
        clauses += [f"text ~ {cql_quote(t)}" for t in search_terms(query.text)]
        if query.date_from:
            clauses.append(f'lastmodified >= "{query.date_from:%Y-%m-%d}"')
        if query.date_to:
            clauses.append(f'lastmodified < "{padded(query.date_to, 1):%Y-%m-%d}"')
        start = int(query.cursor) if query.cursor else 0
        data = await self._get(
            f"{api}/search",
            token,
            {
                "cql": " AND ".join(clauses) + " ORDER BY lastmodified DESC",
                "limit": PAGE_SIZE,
                "start": start,
                "excerpt": "highlight",
            },
        )
        results = data.get("results", [])
        records = [r for r in (search_record(i, site) for i in results) if r]
        more = (
            str(start + len(results))
            if (data.get("_links") or {}).get("next")
            else None
        )
        return done(NAME, records, more)

    async def _suggest(self, token: str, ctx: AccessContext) -> list[dict[str, str]]:
        api, _ = await self._base(ctx)
        data = await self._get(f"{api}/space", token, {"limit": 100})
        return [
            {"id": x["key"], "label": f"{x['key']} · {x.get('name', '')}".strip(" ·")}
            for x in data.get("results", [])
            if x.get("key")
        ]

    async def _page(self, token: str, api: str, page_id: str) -> dict[str, Any]:
        data: dict[str, Any] = await self._get(
            f"{api}/content/{page_id}", token, {"expand": EXPAND}
        )
        return data

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        page_id = record_id.removeprefix(f"{NAME}:").split(":")[0]
        if not CONTENT_ID.match(page_id):
            return done(NAME, [], detail=f"{record_id} is not a Confluence page id.")
        api, site = await self._base(ctx)
        page = await self._page(token, api, page_id)
        spaces = self._spaces_for(ctx)
        if spaces and (page.get("space") or {}).get("key") not in spaces:
            return done(
                NAME,
                [],
                detail="That page is outside the configured Confluence spaces.",
            )
        return done(NAME, [page_record(page, site)])

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        page_id = thread_id.removeprefix(f"{NAME}:")
        if not CONTENT_ID.match(page_id):
            return done(NAME, [], detail=f"{thread_id} is not a Confluence page id.")
        api, site = await self._base(ctx)
        page = await self._page(token, api, page_id)
        spaces = self._spaces_for(ctx)
        if spaces and (page.get("space") or {}).get("key") not in spaces:
            return done(
                NAME,
                [],
                detail="That page is outside the configured Confluence spaces.",
            )
        comments: list[dict[str, Any]] = []
        start, more = 0, True
        for _ in range(MAX_COMMENT_PAGES):
            batch = await self._get(
                f"{api}/content/{page_id}/child/comment",
                token,
                {"expand": "body.storage,version", "limit": 100, "start": start},
            )
            items = batch.get("results", [])
            comments += items
            start += len(items)
            more = bool((batch.get("_links") or {}).get("next"))
            if not more or not items:
                break
        records = [
            page_record(page, site),
            *(comment_record(page_id, c, site) for c in comments),
        ]
        records.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        return done(
            NAME,
            records,
            partial=more,
            detail="The page has more comments than were read." if more else None,
        )
