"""Numbers the placeholders: the first person seen in an investigation is PERSON_1, the
next PERSON_2, and the same person is the same number every time.

Only a keyed hash of the value is ever stored, never the value, so this table is not a
second copy of anyone's personal data."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool


class AliasBook(Protocol):
    async def ordinal(self, scope: str, kind: str, norm: str) -> int: ...


def _digest(secret: bytes, scope: str, kind: str, norm: str) -> str:
    key = hmac.new(secret, scope.encode(), hashlib.sha256).digest()
    return hmac.new(key, f"{kind}\x1f{norm}".encode(), hashlib.sha256).hexdigest()


class MemoryAliasBook:
    """Numbers held in this process. Enough on its own: every prompt is numbered afresh and
    every answer is restored before it is stored, so no number outlives a call."""

    def __init__(self, secret: bytes = b"memory") -> None:
        self._secret = secret
        self._seen: dict[tuple[str, str], dict[str, int]] = {}
        self._lock = asyncio.Lock()

    async def ordinal(self, scope: str, kind: str, norm: str) -> int:
        async with self._lock:
            book = self._seen.setdefault((scope, kind), {})
            key = _digest(self._secret, scope, kind, norm)
            if key not in book:
                book[key] = len(book) + 1
            return book[key]

    def drop(self, scope: str) -> None:
        for k in [k for k in self._seen if k[0] == scope]:
            del self._seen[k]


ALIAS_SCHEMA = """
CREATE TABLE IF NOT EXISTS pii_alias (
    scope_id TEXT NOT NULL, kind TEXT NOT NULL, value_hmac TEXT NOT NULL, ordinal INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_id, kind, value_hmac),
    UNIQUE (scope_id, kind, ordinal)
);
"""


class PostgresAliasBook:
    """Numbers shared by every process, so an investigation, its re-runs and its chat all
    call a person by the same placeholder. Expects an autocommit pool with dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any], secret: bytes) -> None:
        self._pool = pool
        self._secret = secret
        self._cache: dict[str, int] = {}

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(ALIAS_SCHEMA)

    async def ordinal(self, scope: str, kind: str, norm: str) -> int:
        digest = _digest(self._secret, scope, kind, norm)
        cache_key = f"{scope}\x1f{kind}\x1f{digest}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        async with self._pool.connection() as conn:
            for _ in range(
                8
            ):  # two writers racing for one number: the loser tries again
                cur = await conn.execute(
                    "SELECT ordinal FROM pii_alias WHERE scope_id=%s AND kind=%s AND value_hmac=%s",
                    (scope, kind, digest),
                )
                row = await cur.fetchone()
                if row:
                    self._cache[cache_key] = row["ordinal"]
                    if len(self._cache) > 20000:
                        self._cache.pop(next(iter(self._cache)))
                    return int(row["ordinal"])
                await conn.execute(
                    "INSERT INTO pii_alias (scope_id, kind, value_hmac, ordinal) "
                    "SELECT %s, %s, %s, coalesce(max(ordinal), 0) + 1 FROM pii_alias "
                    "WHERE scope_id=%s AND kind=%s ON CONFLICT DO NOTHING",
                    (scope, kind, digest, scope, kind),
                )
        raise RuntimeError("could not assign a placeholder number")
