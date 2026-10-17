"""What every live connector shares: token use, HTTP, error-to-coverage mapping,
search-term handling and text cleanup. A connector then only says how its source
is queried and how a payload becomes an `EvidenceRecord`."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any, ClassVar

import httpx

from investigator.connectors.base import (
    CoverageStatus,
    EvidenceRecord,
    SearchQuery,
    SearchResult,
    SourceCoverage,
)
from investigator.connectors.privacy import redact_secrets
from investigator.directory import SourceFilter
from investigator.integrations import (
    NotConnectedError,
    OAuthError,
    ProviderNotConfiguredError,
    ReauthRequiredError,
    TokenProvider,
)
from investigator.tools import AccessContext

PAGE_SIZE = 20  # equals the harness cap, so a page is never silently cut
MAX_TERMS = 4
VIETNAMESE_FILLER = (
    "và của là có cho không được trong với các những này đó khi để một như thì mà "
    "đã sẽ đang cũng rất hay hoặc vì nên bị từ về tại theo ra vào lại ai gì sao "
    "nào đâu bao nhiêu thế"
)
RETRIES = 2
DEFAULT_BACKOFF = 1.0
MAX_BACKOFF = 4.0
# Words every document contains. Search engines ignore them, so ANDing them in would
# turn a natural question into an empty result.
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "and",
        "or",
        "but",
        "if",
        "so",
        "than",
        "then",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "as",
        "from",
        "into",
        "about",
        "why",
        "what",
        "when",
        "who",
        "whom",
        "which",
        "how",
        "did",
        "do",
        "does",
        "done",
        "has",
        "have",
        "had",
        "will",
        "would",
        "can",
        "could",
        "should",
        "not",
        "no",
        "there",
        "their",
        "they",
        "them",
        "we",
        "us",
        "our",
        "you",
        "your",
        "he",
        "she",
        "his",
        "her",
        "i",
        "me",
        "my",
    ]
)


class SourceHttpError(Exception):
    """A non-success answer from a source. Carries the status, never the body."""

    def __init__(
        self, status: int, retry_after: float | None = None, code: str | None = None
    ) -> None:
        super().__init__(f"HTTP {status}" + (f" ({code})" if code else ""))
        self.status = status
        self.retry_after = retry_after
        self.code = code


def _error_reason(resp: httpx.Response) -> str | None:
    """A short machine reason from the error body (Google's `reason`), never free text."""
    try:
        errors = resp.json()["error"]["errors"]
        reason = str(errors[0]["reason"])
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    return reason if re.fullmatch(r"[A-Za-z_]{1,40}", reason) else None


NOT_ENABLED = {"accessNotConfigured", "SERVICE_DISABLED"}


class SourceDenied(Exception):
    """The source refused this user (revoked token, missing scope, no access)."""


STOPWORDS_ALL = STOPWORDS | frozenset(VIETNAMESE_FILLER.split())


def search_terms(text: str) -> list[str]:
    """Words of a query. Sources AND them, so a natural phrase still matches when the
    words are not adjacent."""
    words = [
        w.strip(".'-")
        for w in re.findall(r"[\w@.'-]{2,}", text, flags=re.UNICODE)
        if w.strip(".'-")
    ]
    meaningful = [w for w in words if w.lower() not in STOPWORDS_ALL] or words
    if len(meaningful) <= MAX_TERMS:
        return meaningful
    # Too many ANDed words match nothing: keep the most distinctive (longest) ones.
    keep = sorted(range(len(meaningful)), key=lambda i: -len(meaningful[i]))[:MAX_TERMS]
    return [meaningful[i] for i in sorted(keep)]


def window_bounds(query: SearchQuery) -> tuple[datetime | None, datetime | None]:
    """Inclusive start and exclusive end, in UTC, from the query's dates."""
    start = (
        datetime.combine(query.date_from, datetime.min.time(), UTC)
        if query.date_from
        else None
    )
    end = (
        datetime.combine(query.date_to + timedelta(days=1), datetime.min.time(), UTC)
        if query.date_to
        else None
    )
    return start, end


def in_bounds(
    moment: datetime | None, bounds: tuple[datetime | None, datetime | None]
) -> bool:
    start, end = bounds
    if moment is None:
        return True  # an undated record cannot be excluded by date
    return (start is None or moment >= start) and (end is None or moment < end)


def padded(day: date, days: int) -> date:
    return day + timedelta(days=days)


class _Text(HTMLParser):
    BLOCK: ClassVar[frozenset[str]] = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "pre"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in {"script", "style"}:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = max(0, self._skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _Text()
    parser.feed(markup)
    parser.close()
    lines = (
        re.sub(r"[ \t\xa0]+", " ", line).strip()
        for line in "".join(parser.parts).splitlines()
    )
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def clean(text: str) -> str:
    return redact_secrets(text.strip())


def record(**fields: Any) -> EvidenceRecord:
    """Build a record with secrets redacted from every free-text field."""
    for key in ("title", "excerpt", "author"):
        if isinstance(fields.get(key), str):
            fields[key] = clean(fields[key])
    return EvidenceRecord(**fields)


def done(
    source: str,
    records: list[EvidenceRecord],
    cursor: str | None = None,
    detail: str | None = None,
    *,
    partial: bool = False,
) -> SearchResult:
    """`no_matches` only when nothing was found and nothing is left to read."""
    status: CoverageStatus
    if partial:
        status = "partial"
    elif records or cursor:
        status = "searched"
    else:
        status = "no_matches"
    return SearchResult(
        coverage=SourceCoverage(source=source, status=status, detail=detail),
        records=records,
        next_cursor=cursor,
    )


def failure(source: str, status: CoverageStatus, detail: str) -> SearchResult:
    return SearchResult(
        coverage=SourceCoverage(source=source, status=status, detail=detail)
    )


async def gather_limited[T](
    items: Iterable[T], work: Callable[[T], Awaitable[Any]], limit: int = 5
) -> list[Any]:
    gate = asyncio.Semaphore(limit)

    async def one(item: T) -> Any:
        async with gate:
            return await work(item)

    return list(await asyncio.gather(*(one(i) for i in items)))


def enrich(name: str, result: SearchResult, ctx: AccessContext) -> SearchResult:
    """Attach customer, project and the author's side (customer or internal) from the
    directory. Only facts the directory knows; nothing is guessed."""
    directory = ctx.directory
    if directory is None or not result.records:
        return result
    records: list[EvidenceRecord] = []
    for r in result.records:
        who = r.author_id or ""
        addresses = [*r.participants, *([who] if "@" in who else [])]
        customer, project = directory.classify(
            name,
            channel=r.meta.get("channel"),
            jira_key=r.meta.get("jira_key"),
            space=r.meta.get("space"),
            emails=addresses,
            labels=[x for x in r.meta.get("labels", "").split(",") if x],
        )
        person = directory.person_for(
            email=who if "@" in who else None,
            slack_id=who if name == "slack" else None,
            jira_id=who if name == "jira" else None,
            name=r.author,
        )
        update: dict[str, Any] = {}
        if customer and not r.customer_id:
            update["customer_id"] = customer
        if project and not r.project_id:
            update["project_id"] = project
        if person:
            update["author_side"] = person.side
            update["author_role"] = person.role
        records.append(r.model_copy(update=update) if update else r)
    return result.model_copy(update={"records": records})


class LiveConnector:
    """Subclasses set `name` and `provider` and implement the three `_` methods."""

    name: str
    provider: str
    label: str

    def __init__(self, tokens: TokenProvider, http: httpx.AsyncClient) -> None:
        self._tokens = tokens
        self._http = http

    # ---- to implement ---------------------------------------------------------------

    async def _search(
        self, token: str, query: SearchQuery, ctx: AccessContext
    ) -> SearchResult:
        raise NotImplementedError

    async def _get_record(
        self, token: str, record_id: str, ctx: AccessContext
    ) -> SearchResult:
        raise NotImplementedError

    async def _get_thread(
        self, token: str, thread_id: str, ctx: AccessContext
    ) -> SearchResult:
        raise NotImplementedError

    async def _suggest(self, token: str, ctx: AccessContext) -> list[dict[str, str]]:
        return []

    async def suggestions(self, ctx: AccessContext) -> tuple[str, list[dict[str, str]]]:
        """What a person could map a project to in this source (channels, projects,
        labels, spaces) as (status, [{id, label}]). Never raises."""
        try:
            token = await self._tokens.access_token(ctx.user_id, self.provider)
            return "ok", await self._suggest(token, ctx)
        except (NotConnectedError, ProviderNotConfiguredError, ReauthRequiredError):
            return "not_connected", []
        except (SourceHttpError, SourceDenied, OAuthError, httpx.HTTPError):
            return "failed", []

    # ---- the SourceConnector protocol -------------------------------------------------

    async def search(self, query: SearchQuery, ctx: AccessContext) -> SearchResult:
        found = await self._guard(ctx, lambda t: self._search(t, query, ctx))
        relaxed = self._relaxed(query)
        if found.coverage.status != "no_matches" or relaxed is None:
            return found
        # Nothing contained every word. Try the two most distinctive words before
        # reporting no matches, and say so: a looser match is not the same as a match.
        retry = await self._guard(ctx, lambda t: self._search(t, relaxed, ctx))
        if not retry.records:
            return found
        return SearchResult(
            coverage=SourceCoverage(
                source=self.name,
                status="searched",
                detail=f'No record contained every word; these match "{relaxed.text}".',
            ),
            records=retry.records,
            # The cursor belongs to the looser query, which the caller does not know about.
            next_cursor=None,
        )

    @staticmethod
    def _relaxed(query: SearchQuery) -> SearchQuery | None:
        terms = search_terms(query.text)
        if query.cursor or len(terms) <= 2:
            return None
        keep = sorted(range(len(terms)), key=lambda i: -len(terms[i]))[:2]
        return query.model_copy(
            update={"text": " ".join(terms[i] for i in sorted(keep))}
        )

    async def get_record(self, record_id: str, ctx: AccessContext) -> SearchResult:
        return await self._guard(ctx, lambda t: self._get_record(t, record_id, ctx))

    async def get_thread(self, thread_id: str, ctx: AccessContext) -> SearchResult:
        return await self._guard(ctx, lambda t: self._get_thread(t, thread_id, ctx))

    # ---- plumbing ---------------------------------------------------------------------

    async def _guard(
        self, ctx: AccessContext, run: Callable[[str], Awaitable[SearchResult]]
    ) -> SearchResult:
        """Turn every failure into an honest coverage status. "Could not search" must
        never read as "nothing found"."""
        try:
            token = await self._tokens.access_token(ctx.user_id, self.provider)
            return self._enrich(await run(token), ctx)
        except (NotConnectedError, ProviderNotConfiguredError):
            return failure(
                self.name, "not_connected", f"{self.label} is not connected."
            )
        except ReauthRequiredError:
            return failure(
                self.name,
                "not_connected",
                f"{self.label} access expired; connect it again.",
            )
        except SourceDenied as exc:
            return failure(self.name, "permission_denied", str(exc))
        except SourceHttpError as exc:
            if exc.code in NOT_ENABLED:
                # A server setup problem, not something this user is forbidden to read.
                return failure(
                    self.name,
                    "failed",
                    f"The {self.label} API is not enabled for this server's app registration.",
                )
            if exc.status in (401, 403):
                return failure(
                    self.name,
                    "permission_denied",
                    f"{self.label} rejected the token or it lacks the needed permissions "
                    f"({exc}); connect it again.",
                )
            if exc.status == 429:
                wait = (
                    f" Retry after {exc.retry_after:.0f}s." if exc.retry_after else ""
                )
                return failure(
                    self.name, "failed", f"{self.label} rate limit reached.{wait}"
                )
            return failure(self.name, "failed", f"{self.label} request failed ({exc}).")
        except OAuthError as exc:
            return failure(
                self.name,
                "failed",
                f"{self.label} credentials unavailable ({exc.code}).",
            )
        except httpx.HTTPError:
            return failure(self.name, "failed", f"{self.label} could not be reached.")

    def case_filter(self, ctx: AccessContext) -> SourceFilter | None:
        """How the directory narrows this source for the case; None when it does not."""
        return ctx.filter_for(self.name)

    def _enrich(self, result: SearchResult, ctx: AccessContext) -> SearchResult:
        return enrich(self.name, result, ctx)

    async def _request(
        self,
        method: str,
        url: str,
        token: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        for attempt in range(RETRIES + 1):
            resp = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    **(headers or {}),
                },
            )
            retry = resp.headers.get("retry-after")
            wait = float(retry) if retry and retry.isdigit() else None
            # A short rate-limit or "try again" answer is worth waiting out once; a long
            # one is reported as it is, since the caller has a time limit of its own.
            if (
                resp.status_code in (429, 503)
                and attempt < RETRIES
                and (wait or DEFAULT_BACKOFF) <= MAX_BACKOFF
            ):
                await asyncio.sleep(wait or DEFAULT_BACKOFF)
                continue
            break
        if resp.status_code >= 400:
            raise SourceHttpError(resp.status_code, wait, _error_reason(resp))
        try:
            return resp.json()
        except ValueError as exc:
            raise SourceHttpError(502, code="invalid_json") from exc

    async def _get(
        self, url: str, token: str, params: dict[str, Any] | None = None, **kw: Any
    ) -> Any:
        return await self._request("GET", url, token, params=params, **kw)


def narrowed(configured: frozenset[str], wanted: list[str]) -> frozenset[str]:
    """What a source may read: the deployment's limit and the case's mapping together.
    A side with nothing set does not restrict."""
    mapped = frozenset(wanted)
    if configured and mapped:
        return configured & mapped
    return configured or mapped


def scoped(items: str) -> frozenset[str]:
    """Comma-separated config value to a set; empty means "no restriction"."""
    return frozenset(p.strip() for p in items.split(",") if p.strip())
