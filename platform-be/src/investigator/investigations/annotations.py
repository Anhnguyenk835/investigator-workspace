"""What people add to an investigation: notes, and whether they reviewed or dispute a claim.

They are attached to a claim by its id, which is stable across re-runs, so a reviewer's
work is still there when the investigation is run again."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

AnnotationKind = Literal["note", "reviewed", "disputed"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS annotations (
    id uuid PRIMARY KEY,
    investigation_id uuid NOT NULL,
    target_id text NOT NULL,
    kind text NOT NULL,
    text text NOT NULL DEFAULT '',
    author text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS annotations_inv_idx ON annotations (investigation_id, created_at);
"""


class Annotation(BaseModel):
    id: UUID
    investigation_id: UUID
    target_id: str
    kind: AnnotationKind
    text: str = ""
    author: str
    created_at: datetime


class AnnotationStore(Protocol):
    async def add(
        self,
        investigation_id: UUID,
        target_id: str,
        kind: AnnotationKind,
        text: str,
        author: str,
    ) -> Annotation: ...

    async def list(self, investigation_id: UUID) -> list[Annotation]: ...

    async def delete(
        self, investigation_id: UUID, annotation_id: UUID, author: str
    ) -> bool:
        """Only the author may remove their own annotation."""
        ...


class PostgresAnnotationStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def add(
        self,
        investigation_id: UUID,
        target_id: str,
        kind: AnnotationKind,
        text: str,
        author: str,
    ) -> Annotation:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "INSERT INTO annotations (id, investigation_id, target_id, kind, text, author) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (uuid4(), investigation_id, target_id, kind, text, author),
            )
            row = await cur.fetchone()
            assert row is not None
            return Annotation(**row)

    async def list(self, investigation_id: UUID) -> list[Annotation]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT * FROM annotations WHERE investigation_id = %s ORDER BY created_at, id",
                (investigation_id,),
            )
            return [Annotation(**r) for r in await cur.fetchall()]

    async def delete(
        self, investigation_id: UUID, annotation_id: UUID, author: str
    ) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM annotations WHERE id = %s AND investigation_id = %s AND author = %s",
                (annotation_id, investigation_id, author),
            )
            return bool(cur.rowcount > 0)


class MemoryAnnotationStore:
    def __init__(self) -> None:
        self.items: list[Annotation] = []

    async def add(
        self,
        investigation_id: UUID,
        target_id: str,
        kind: AnnotationKind,
        text: str,
        author: str,
    ) -> Annotation:
        item = Annotation(
            id=uuid4(),
            investigation_id=investigation_id,
            target_id=target_id,
            kind=kind,
            text=text,
            author=author,
            created_at=datetime.now(UTC),
        )
        self.items.append(item)
        return item

    async def list(self, investigation_id: UUID) -> list[Annotation]:
        return [a for a in self.items if a.investigation_id == investigation_id]

    async def delete(
        self, investigation_id: UUID, annotation_id: UUID, author: str
    ) -> bool:
        keep = [
            a
            for a in self.items
            if not (
                a.id == annotation_id
                and a.investigation_id == investigation_id
                and a.author == author
            )
        ]
        removed = len(keep) != len(self.items)
        self.items = keep
        return removed
