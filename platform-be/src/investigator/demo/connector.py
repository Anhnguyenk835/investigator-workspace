"""Demo sources: the same four connectors, reading the stored corpus instead of the live APIs."""

from __future__ import annotations

from investigator.connectors.base import (
    SearchQuery,
    SearchResult,
    SourceConnector,
    SourceCoverage,
)
from investigator.connectors.support import (
    PAGE_SIZE,
    done,
    enrich,
    failure,
    search_terms,
    window_bounds,
)
from investigator.demo.corpus import DemoCorpus
from investigator.tools import AccessContext

LABELS = {
    "gmail": "Gmail",
    "slack": "Slack",
    "jira": "Jira",
    "confluence": "Confluence",
    "notion": "Notion",
}


class DemoConnector:
    def __init__(self, name: str, corpus: DemoCorpus) -> None:
        self.name = name
        self._corpus = corpus

    async def _has_data(self) -> bool:
        return self.name in (await self._corpus.index()).sources

    def _none(self) -> SearchResult:
        return failure(
            self.name,
            "not_connected",
            f"{LABELS.get(self.name, self.name)} is not part of the demo data.",
        )

    async def search(self, query: SearchQuery, ctx: AccessContext) -> SearchResult:
        if not await self._has_data():
            return self._none()
        index = await self._corpus.index()
        f = ctx.filter_for(self.name)
        start, end = window_bounds(query)
        terms = search_terms(query.text)
        rows = index.search(self.name, terms, start, end, f)
        relaxed_note: str | None = None
        if not rows and not query.cursor and len(terms) > 2:
            # As the live sources do: when no record has every word, try the two most
            # distinctive, and say that this is a looser match.
            keep = sorted(range(len(terms)), key=lambda i: -len(terms[i]))[:2]
            loose = [terms[i] for i in sorted(keep)]
            rows = index.search(self.name, loose, start, end, f)
            if rows:
                relaxed_note = (
                    f'No record contained every word; these match "{" ".join(loose)}".'
                )
        offset = int(query.cursor) if query.cursor and query.cursor.isdigit() else 0
        page = rows[offset : offset + PAGE_SIZE]
        cursor = (
            str(offset + PAGE_SIZE)
            if offset + PAGE_SIZE < len(rows) and not relaxed_note
            else None
        )
        note = relaxed_note or (
            "No label or customer domain is mapped to this case, so the search was not narrowed."
            if f is not None and f.is_empty()
            else None
        )
        page.sort(key=lambda r: (r.occurred_at is None, r.occurred_at))
        result = done(self.name, page, cursor, detail=note)
        if relaxed_note and page:
            result = result.model_copy(
                update={
                    "coverage": SourceCoverage(
                        source=self.name, status="searched", detail=relaxed_note
                    )
                }
            )
        return enrich(self.name, result, ctx)

    async def get_record(self, record_id: str, ctx: AccessContext) -> SearchResult:
        found = (await self._corpus.index()).get(record_id)
        if found is None or found.source != self.name:
            return done(
                self.name, [], detail=f"{record_id} is not a record of this source."
            )
        return enrich(self.name, done(self.name, [found]), ctx)

    async def get_thread(self, thread_id: str, ctx: AccessContext) -> SearchResult:
        rows = [
            r
            for r in (await self._corpus.index()).thread(thread_id)
            if r.source == self.name
        ]
        if not rows:
            return done(
                self.name, [], detail=f"{thread_id} is not a thread of this source."
            )
        return enrich(self.name, done(self.name, rows), ctx)

    async def suggestions(self, ctx: AccessContext) -> tuple[str, list[dict[str, str]]]:
        index = await self._corpus.index()
        return (
            ("ok", index.options(self.name))
            if self.name in index.sources
            else ("not_connected", [])
        )


class RoutedConnector:
    """One source, two places to read it: the live API, or (for a demo visitor) the stored corpus."""

    def __init__(self, live: SourceConnector, demo: DemoConnector) -> None:
        self.name = live.name
        self._live = live
        self._demo = demo

    def _for(self, ctx: AccessContext) -> SourceConnector:
        return self._demo if ctx.demo else self._live

    async def search(self, query: SearchQuery, ctx: AccessContext) -> SearchResult:
        return await self._for(ctx).search(query, ctx)

    async def get_record(self, record_id: str, ctx: AccessContext) -> SearchResult:
        return await self._for(ctx).get_record(record_id, ctx)

    async def get_thread(self, thread_id: str, ctx: AccessContext) -> SearchResult:
        return await self._for(ctx).get_thread(thread_id, ctx)

    async def suggestions(self, ctx: AccessContext) -> tuple[str, list[dict[str, str]]]:
        target = self._for(ctx)
        if hasattr(target, "suggestions"):
            return await target.suggestions(ctx)  # type: ignore[no-any-return]
        return "not_connected", []
