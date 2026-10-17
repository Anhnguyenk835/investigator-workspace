"""The fictional records a demo visitor searches, kept in Postgres.

A demo corpus is a few hundred records, so the whole set is held in memory and searched with
plain code: one code path for tests and production, and the same "every word must match"
meaning the live connectors have. The database is where it lives and is replaced from.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from investigator.connectors.base import EvidenceRecord
from investigator.directory import SourceFilter
from investigator.guardrails.pii.detect import fold

SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_records (
    id text PRIMARY KEY,
    source text NOT NULL,
    thread_id text,
    occurred_at timestamptz,
    record jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS demo_records_source_idx ON demo_records (source, occurred_at DESC);
CREATE TABLE IF NOT EXISTS demo_dataset (
    id int PRIMARY KEY DEFAULT 1,
    version text NOT NULL,
    built_at timestamptz NOT NULL DEFAULT now(),
    truth jsonb NOT NULL DEFAULT '[]'
);
"""

RELOAD_AFTER = 60.0
EARLIEST = datetime.min.replace(tzinfo=UTC)


def _flat(r: EvidenceRecord) -> str:
    return fold(f"{r.title}\n{r.author or ''}\n{r.excerpt}")


class DemoIndex:
    """Searches a fixed list of records the way the live connectors search their source."""

    def __init__(self, records: list[EvidenceRecord]) -> None:
        self.records = records
        self._text = {r.id: _flat(r) for r in records}
        self._by_id = {r.id: r for r in records}
        self.sources = sorted({r.source for r in records})

    @staticmethod
    def _domains(r: EvidenceRecord) -> set[str]:
        addresses = [*r.participants, r.author_id or ""]
        return {a.rsplit("@", 1)[-1].lower() for a in addresses if "@" in a}

    def _in_scope(self, r: EvidenceRecord, f: SourceFilter | None) -> bool:
        """The same narrowing the directory asks of a live source. Empty means no restriction."""
        if f is None or f.is_empty():
            return True
        if r.source == "slack":
            return not f.channels or r.meta.get("channel") in f.channels
        if r.source == "jira":
            prefix = r.meta.get("jira_key", "").split("-")[0].upper()
            labels = {x.lower() for x in r.meta.get("labels", "").split(",") if x}
            projects_ok = not f.jira_projects or prefix in [
                p.upper() for p in f.jira_projects
            ]
            labels_ok = not f.jira_labels or bool(
                labels & {x.lower() for x in f.jira_labels}
            )
            return projects_ok and labels_ok
        if r.source == "gmail":
            if not (f.gmail_labels or f.gmail_domains):
                return True
            labels = {x.lower() for x in r.meta.get("labels", "").split(",") if x}
            return bool(labels & {x.lower() for x in f.gmail_labels}) or bool(
                self._domains(r) & {d.lstrip("@").lower() for d in f.gmail_domains}
            )
        if r.source == "confluence":
            return not f.confluence_spaces or r.meta.get("space") in f.confluence_spaces
        return True

    def search(
        self,
        source: str,
        terms: list[str],
        start: datetime | None,
        end: datetime | None,
        f: SourceFilter | None,
    ) -> list[EvidenceRecord]:
        """Newest first. Every term must appear; an undated record is never cut by date."""
        wanted = [fold(t) for t in terms]
        found = [
            r
            for r in self.records
            if r.source == source
            and all(w in self._text[r.id] for w in wanted)
            and self._in_scope(r, f)
            and (
                r.occurred_at is None
                or (
                    (start is None or r.occurred_at >= start)
                    and (end is None or r.occurred_at < end)
                )
            )
        ]
        found.sort(
            key=lambda r: (r.occurred_at is not None, r.occurred_at or EARLIEST),
            reverse=True,
        )
        return found

    def get(self, record_id: str) -> EvidenceRecord | None:
        return self._by_id.get(record_id)

    def thread(self, thread_id: str) -> list[EvidenceRecord]:
        rows = [r for r in self.records if r.thread_id == thread_id]
        return sorted(
            rows, key=lambda r: (r.occurred_at is None, r.occurred_at or EARLIEST)
        )

    def options(self, source: str) -> list[dict[str, str]]:
        """What a project could be mapped to in a source: its channels, projects, labels, spaces."""
        out: dict[str, str] = {}
        for r in self.records:
            if r.source != source:
                continue
            if source == "slack" and r.meta.get("channel"):
                out[r.meta["channel"]] = r.title
            if source == "jira":
                key = r.meta.get("jira_key", "").split("-")[0]
                if key:
                    out[key] = key
            if source == "confluence" and r.meta.get("space"):
                out[r.meta["space"]] = r.meta["space"]
            if source == "gmail":
                for lab in r.meta.get("labels", "").split(","):
                    if lab:
                        out[lab] = lab
        return [{"id": k, "label": v} for k, v in sorted(out.items())]


class DemoStore(Protocol):
    async def load(self) -> tuple[str, list[EvidenceRecord]]:
        """(dataset version, records). Version "" and no records: nothing has been loaded."""
        ...

    async def replace(
        self, version: str, records: list[EvidenceRecord], truth: list[dict[str, Any]]
    ) -> None: ...

    async def truth(self) -> list[dict[str, Any]]: ...


class MemoryDemoStore:
    def __init__(self, records: list[EvidenceRecord] | None = None) -> None:
        self.version = "memory" if records else ""
        self.records = list(records or [])
        self._truth: list[dict[str, Any]] = []

    async def load(self) -> tuple[str, list[EvidenceRecord]]:
        return self.version, list(self.records)

    async def replace(
        self, version: str, records: list[EvidenceRecord], truth: list[dict[str, Any]]
    ) -> None:
        self.version, self.records, self._truth = version, list(records), truth

    async def truth(self) -> list[dict[str, Any]]:
        return self._truth


class PostgresDemoStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def load(self) -> tuple[str, list[EvidenceRecord]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT version FROM demo_dataset WHERE id = 1")
            row = await cur.fetchone()
            if row is None:
                return "", []
            cur = await conn.execute("SELECT record FROM demo_records")
            return str(row["version"]), [
                EvidenceRecord.model_validate(r["record"]) for r in await cur.fetchall()
            ]

    async def replace(
        self, version: str, records: list[EvidenceRecord], truth: list[dict[str, Any]]
    ) -> None:
        async with self._pool.connection() as conn, conn.transaction():
            await conn.execute("DELETE FROM demo_records")
            for r in records:
                await conn.execute(
                    "INSERT INTO demo_records (id, source, thread_id, occurred_at, record) VALUES (%s,%s,%s,%s,%s)",
                    (
                        r.id,
                        r.source,
                        r.thread_id,
                        r.occurred_at,
                        Jsonb(r.model_dump(mode="json")),
                    ),
                )
            await conn.execute(
                "INSERT INTO demo_dataset (id, version, truth) VALUES (1, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version, built_at = now(), truth = EXCLUDED.truth",
                (version, Jsonb(truth)),
            )

    async def truth(self) -> list[dict[str, Any]]:
        async with self._pool.connection() as conn:
            cur = await conn.execute("SELECT truth FROM demo_dataset WHERE id = 1")
            row = await cur.fetchone()
            return list(row["truth"]) if row else []


class DemoCorpus:
    """The in-memory index over a store, rebuilt when the stored dataset changes."""

    def __init__(self, store: DemoStore, clock: Any = time.monotonic) -> None:
        self.store = store
        self._clock = clock
        self._index = DemoIndex([])
        self._version = "\0"
        self._checked = -1e9

    async def index(self) -> DemoIndex:
        if self._clock() - self._checked >= RELOAD_AFTER:
            version, records = await self.store.load()
            if version != self._version:
                self._index, self._version = DemoIndex(records), version
            self._checked = self._clock()
        return self._index

    async def refresh(self) -> DemoIndex:
        self._checked = -1e9
        return await self.index()
