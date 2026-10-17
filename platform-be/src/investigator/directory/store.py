from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel

from investigator.directory.models import (
    Customer,
    CustomerInput,
    Directory,
    Person,
    PersonInput,
    Project,
    ProjectInput,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS directory_entries (
    id text PRIMARY KEY,
    kind text NOT NULL,
    data jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS directory_entries_kind_idx ON directory_entries (kind);
ALTER TABLE directory_entries ADD COLUMN IF NOT EXISTS owner_id text;
CREATE INDEX IF NOT EXISTS directory_entries_owner_idx ON directory_entries (owner_id);
"""

KINDS: dict[str, type[BaseModel]] = {
    "customer": Customer,
    "project": Project,
    "person": Person,
}


class DirectoryStore(Protocol):
    """Every directory belongs to one owner (an account id; None is the one from before
    sign-in, or the single local user)."""

    async def load(self, owner: str | None = None) -> Directory: ...
    async def put(
        self, kind: str, entry: BaseModel, owner: str | None = None
    ) -> None: ...
    async def delete(
        self, kind: str, entry_id: str, owner: str | None = None
    ) -> bool: ...


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


def build(
    kind: str,
    data: CustomerInput | ProjectInput | PersonInput,
    entry_id: str | None = None,
) -> Customer | Project | Person:
    """An input plus an id (a new one unless the entry is being edited)."""
    ident = entry_id or new_id(kind[:3])
    if kind == "customer":
        return Customer(id=ident, **data.model_dump())
    if kind == "project":
        return Project(id=ident, **data.model_dump())
    return Person(id=ident, **data.model_dump())


class PostgresDirectoryStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def load(self, owner: str | None = None) -> Directory:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT kind, data FROM directory_entries "
                "WHERE owner_id IS NOT DISTINCT FROM %s ORDER BY id",
                (owner,),
            )
            rows = await cur.fetchall()
        by_kind: dict[str, list[Any]] = {"customer": [], "project": [], "person": []}
        for r in rows:
            if r["kind"] in KINDS:
                by_kind[r["kind"]].append(KINDS[r["kind"]].model_validate(r["data"]))
        return Directory(
            customers=sorted(by_kind["customer"], key=lambda c: c.name.lower()),
            projects=sorted(by_kind["project"], key=lambda p: p.name.lower()),
            people=sorted(by_kind["person"], key=lambda p: p.name.lower()),
        )

    async def put(self, kind: str, entry: BaseModel, owner: str | None = None) -> None:
        async with self._pool.connection() as conn:
            # The owner is part of the match: nobody can overwrite another account's entry.
            await conn.execute(
                "INSERT INTO directory_entries (id, kind, data, owner_id) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, updated_at = now() "
                "WHERE directory_entries.owner_id IS NOT DISTINCT FROM EXCLUDED.owner_id",
                (getattr(entry, "id"), kind, Jsonb(entry.model_dump()), owner),  # noqa: B009
            )

    async def delete(self, kind: str, entry_id: str, owner: str | None = None) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM directory_entries WHERE id = %s AND kind = %s "
                "AND owner_id IS NOT DISTINCT FROM %s",
                (entry_id, kind, owner),
            )
            return bool(cur.rowcount > 0)


class MemoryDirectoryStore:
    def __init__(self, directory: Directory | None = None) -> None:
        # (owner, id) -> (kind, entry); an initial directory belongs to the local owner.
        self._items: dict[tuple[str | None, str], tuple[str, BaseModel]] = {}
        for c in directory.customers if directory else []:
            self._items[(None, c.id)] = ("customer", c)
        for p in directory.projects if directory else []:
            self._items[(None, p.id)] = ("project", p)
        for q in directory.people if directory else []:
            self._items[(None, q.id)] = ("person", q)

    async def load(self, owner: str | None = None) -> Directory:
        def of(kind: str) -> list[Any]:
            return [
                e for (o, _), (k, e) in self._items.items() if o == owner and k == kind
            ]

        return Directory(
            customers=of("customer"), projects=of("project"), people=of("person")
        )

    async def put(self, kind: str, entry: BaseModel, owner: str | None = None) -> None:
        self._items[(owner, getattr(entry, "id"))] = (kind, entry)  # noqa: B009

    async def delete(self, kind: str, entry_id: str, owner: str | None = None) -> bool:
        item = self._items.get((owner, entry_id))
        if item is None or item[0] != kind:
            return False
        del self._items[(owner, entry_id)]
        return True
