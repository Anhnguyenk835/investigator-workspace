"""Jira Cloud (REST v3 through the Atlassian gateway), read-only.

Search returns one record per issue. `get_thread(jira:KEY)` returns the issue's
timeline: creation, field changes that matter to a promise (status, assignee,
due date, priority, resolution) and every comment. Times come from Jira."""

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
    failure,
    narrowed,
    padded,
    record,
    scoped,
    search_terms,
)
from investigator.integrations import TokenProvider
from investigator.tools import AccessContext

NAME = "jira"
KEY = re.compile(r"^[A-Z][A-Z0-9_]+-\d+$")
ISSUE_FIELDS = "summary,status,assignee,reporter,priority,created,updated,description,labels,duedate,issuetype,project"
TRACKED_CHANGES = {"status", "assignee", "priority", "duedate", "resolution"}
MAX_PAGES = 5
_OFFSET = re.compile(r"([+-]\d{2})(\d{2})$")


def adf_to_text(node: Any) -> str:
    """Flatten Atlassian Document Format; unknown nodes contribute their children."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(adf_to_text(n) for n in node)
    kind = node.get("type")
    if kind == "text":
        return str(node.get("text", ""))
    if kind in {"mention", "emoji", "date", "status", "inlineCard"}:
        attrs = node.get("attrs", {})
        return str(attrs.get("text") or attrs.get("url") or "")
    if kind == "hardBreak":
        return "\n"
    inner = "".join(adf_to_text(c) for c in node.get("content", []))
    if kind in {
        "paragraph",
        "heading",
        "listItem",
        "codeBlock",
        "blockquote",
        "tableRow",
    }:
        return inner.strip("\n") + "\n"
    return inner.strip("\n") if kind == "doc" else inner


def parse_time(value: str) -> datetime:
    """Jira writes offsets as +0700; ISO parsing wants +07:00."""
    return datetime.fromisoformat(_OFFSET.sub(r"\1:\2", value))


def person(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    return user.get("displayName") or user.get("emailAddress")


def account_id(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    return user.get("accountId") or user.get("emailAddress")


def jql_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def issue_record(issue: dict[str, Any], site_url: str) -> EvidenceRecord:
    key, f = issue["key"], issue.get("fields", {})
    status = (f.get("status") or {}).get("name")
    lines = [
        f"{key} [{status or 'unknown status'}] {f.get('summary', '')}",
        f"Type: {(f.get('issuetype') or {}).get('name', 'unknown')}",
        f"Reporter: {person(f.get('reporter')) or 'unknown'}",
        f"Assignee: {person(f.get('assignee')) or 'unassigned'}",
        f"Priority: {(f.get('priority') or {}).get('name', 'unknown')}",
    ]
    if f.get("duedate"):
        lines.append(f"Due: {f['duedate']}")
    if f.get("labels"):
        lines.append("Labels: " + ", ".join(f["labels"]))
    if f.get("updated"):
        lines.append(f"Last updated: {f['updated']}")
    description = adf_to_text(f.get("description")).strip()
    if description:
        lines += ["", description]
    return record(
        id=f"{NAME}:{key}",
        source=NAME,
        title=f"{key}: {f.get('summary', '')}",
        author=person(f.get("reporter")),
        author_id=account_id(f.get("reporter")),
        meta={"jira_key": key, "labels": ",".join(f.get("labels") or [])},
        occurred_at=parse_time(f["created"]) if f.get("created") else None,
        timestamp_precision="exact" if f.get("created") else "unknown",
        excerpt="\n".join(lines),
        url=f"{site_url}/browse/{key}" if site_url else None,
        thread_id=f"{NAME}:{key}",
    )


def history_records(
    key: str, histories: list[dict[str, Any]], site_url: str
) -> list[EvidenceRecord]:
    out: list[EvidenceRecord] = []
    for h in histories:
        changes = [i for i in h.get("items", []) if i.get("field") in TRACKED_CHANGES]
        if not changes:
            continue
        text = "\n".join(
            f"{key}: {i['field']} {i.get('fromString') or '(none)'} → {i.get('toString') or '(none)'}"
            for i in changes
        )
        out.append(
            record(
                id=f"{NAME}:{key}:change:{h['id']}",
                source=NAME,
                title=f"{key}: {', '.join(i['field'] for i in changes)} changed",
                author=person(h.get("author")),
                author_id=account_id(h.get("author")),
                meta={"jira_key": key},
                occurred_at=parse_time(h["created"]),
                timestamp_precision="exact",
                excerpt=text,
                url=f"{site_url}/browse/{key}" if site_url else None,
                thread_id=f"{NAME}:{key}",
            )
        )
    return out


def comment_records(
    key: str, comments: list[dict[str, Any]], site_url: str
) -> list[EvidenceRecord]:
    return [
        record(
            id=f"{NAME}:{key}:comment:{c['id']}",
            source=NAME,
            title=f"{key}: comment",
            author=person(c.get("author")),
            author_id=account_id(c.get("author")),
            meta={"jira_key": key},
            occurred_at=parse_time(c["created"]),
            timestamp_precision="exact",
            excerpt=adf_to_text(c.get("body")).strip(),
            url=f"{site_url}/browse/{key}?focusedCommentId={c['id']}"
            if site_url
            else None,
            thread_id=f"{NAME}:{key}",
        )
        for c in comments
    ]


class JiraConnector(LiveConnector):
    name = NAME
    provider = "atlassian"
    label = "Jira"

    def __init__(
        self,
        tokens: TokenProvider,
        http: httpx.AsyncClient,
        *,
        project_keys: str = "",
        label: str = "",
        site_url: str = "",
    ) -> None:
        super().__init__(tokens, http)
        self._projects = scoped(project_keys)
        self._label = label.strip()
        self._wanted_site = site_url.rstrip("/")
        if self._label and not re.fullmatch(r"[A-Za-z0-9_.-]+", self._label):
            raise ValueError("JIRA_LABEL may only use letters, digits, . _ -")
        for project in self._projects:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]+", project):
                raise ValueError(f"{project!r} is not a Jira project key")

    async def _site(self, ctx: AccessContext) -> tuple[str, str]:
        """(API base, human site URL) for this user's Jira site."""
        cloud_id, url = await cloud_site(self._tokens, ctx, self._wanted_site, "Jira")
        return f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3", url

    def _limits(self, ctx: AccessContext) -> tuple[frozenset[str], list[str]]:
        """(projects the case may read, labels it is limited to)."""
        f = self.case_filter(ctx)
        if f is None:
            return self._projects, ([self._label] if self._label else [])
        labels = f.jira_labels or ([self._label] if self._label else [])
        return narrowed(self._projects, f.jira_projects), labels

    def _in_scope(self, key: str, ctx: AccessContext) -> bool:
        projects, _ = self._limits(ctx)
        return not projects or key.split("-")[0] in projects

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        api, site = await self._site(ctx)
        projects, labels = self._limits(ctx)
        f = self.case_filter(ctx)
        if f is not None and f.jira_projects and self._projects and not projects:
            return done(
                NAME,
                [],
                detail="The projects mapped to this case are outside the Jira projects this server may read.",
            )
        clauses: list[str] = []
        if projects:
            clauses.append("project in (" + ", ".join(sorted(projects)) + ")")
        if labels:
            clauses.append(
                "labels in (" + ", ".join(jql_quote(x) for x in labels) + ")"
            )
        clauses += [f"text ~ {jql_quote(t)}" for t in search_terms(query.text)]
        if query.date_from:
            clauses.append(f'updated >= "{query.date_from:%Y-%m-%d}"')
        if query.date_to:
            clauses.append(f'updated < "{padded(query.date_to, 1):%Y-%m-%d}"')
        params: dict[str, Any] = {
            "jql": " AND ".join(clauses) + " ORDER BY updated DESC",
            "fields": ISSUE_FIELDS,
            "maxResults": PAGE_SIZE,
        }
        if query.cursor:
            params["nextPageToken"] = query.cursor
        page = await self._get(f"{api}/search/jql", token, params)
        records = [issue_record(i, site) for i in page.get("issues", [])]
        more = None if page.get("isLast", True) else page.get("nextPageToken")
        note = (
            "No Jira project is mapped to this case, so the search was not narrowed."
            if f is not None and f.is_empty()
            else None
        )
        return done(NAME, records, more, detail=note)

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        key = thread_id.removeprefix(f"{NAME}:")
        if not KEY.match(key) or not self._in_scope(key, ctx):
            return failure(
                NAME,
                "permission_denied",
                f"{key} is outside the configured Jira scope.",
            )
        api, site = await self._site(ctx)
        issue = await self._get(f"{api}/issue/{key}", token, {"fields": ISSUE_FIELDS})
        histories, h_more = await self._pages(
            f"{api}/issue/{key}/changelog", token, "values"
        )
        comments, c_more = await self._pages(
            f"{api}/issue/{key}/comment", token, "comments"
        )
        records = [
            issue_record(issue, site),
            *history_records(key, histories, site),
            *comment_records(key, comments, site),
        ]
        records.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        truncated = h_more or c_more
        return done(
            NAME,
            records,
            partial=truncated,
            detail=f"{key} has more history or comments than were read."
            if truncated
            else None,
        )

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        parts = record_id.removeprefix(f"{NAME}:").split(":")
        thread = await self._get_thread(token, f"{NAME}:{parts[0]}", ctx)
        if thread.coverage.status in {"permission_denied", "failed", "not_connected"}:
            return thread
        wanted = [r for r in thread.records if r.id == record_id]
        if not wanted:
            return done(NAME, [], detail=f"{record_id} was not found in {parts[0]}.")
        return done(NAME, wanted)

    async def _suggest(self, token: str, ctx: AccessContext) -> list[dict[str, str]]:
        api, _ = await self._site(ctx)
        data = await self._get(f"{api}/project/search", token, {"maxResults": 100})
        return [
            {"id": p["key"], "label": f"{p['key']} · {p.get('name', '')}".strip(" ·")}
            for p in data.get("values", [])
            if p.get("key")
        ]

    async def _pages(
        self, url: str, token: str, field: str
    ) -> tuple[list[dict[str, Any]], bool]:
        out: list[dict[str, Any]] = []
        start = 0
        for _ in range(MAX_PAGES):
            page = await self._get(url, token, {"startAt": start, "maxResults": 100})
            items = page.get(field, [])
            out += items
            start += len(items)
            if page.get("isLast", start >= page.get("total", start)) or not items:
                return out, False
        return out, True
