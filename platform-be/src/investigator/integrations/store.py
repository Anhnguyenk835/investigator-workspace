"""Where encrypted credentials and in-flight authorizations live."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from investigator.integrations.models import PendingAuthorization

SCHEMA = """
CREATE TABLE IF NOT EXISTS oauth_credentials (
    user_id text NOT NULL,
    provider text NOT NULL,
    ciphertext bytea NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, provider)
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state text PRIMARY KEY,
    user_id text NOT NULL,
    provider text NOT NULL,
    code_verifier text,
    expires_at timestamptz NOT NULL
);
"""


class CredentialStore(Protocol):
    """Holds opaque encrypted blobs; it never sees a token."""

    async def put(self, user_id: str, provider: str, blob: bytes) -> None: ...
    async def get(self, user_id: str, provider: str) -> bytes | None: ...
    async def list(self, user_id: str) -> dict[str, bytes]: ...
    async def delete(self, user_id: str, provider: str) -> None: ...
    async def save_pending(self, pending: PendingAuthorization, now: datetime) -> None:
        """Also drops expired pending authorizations."""
        ...

    async def pop_pending(self, state: str) -> PendingAuthorization | None:
        """Single use: a state value works once."""
        ...


class PostgresCredentialStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    async def put(self, user_id: str, provider: str, blob: bytes) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO oauth_credentials (user_id, provider, ciphertext) "
                "VALUES (%s, %s, %s) ON CONFLICT (user_id, provider) "
                "DO UPDATE SET ciphertext = EXCLUDED.ciphertext, updated_at = now()",
                (user_id, provider, blob),
            )

    async def get(self, user_id: str, provider: str) -> bytes | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT ciphertext FROM oauth_credentials "
                "WHERE user_id = %s AND provider = %s",
                (user_id, provider),
            )
            row = await cur.fetchone()
            return bytes(row["ciphertext"]) if row else None

    async def list(self, user_id: str) -> dict[str, bytes]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT provider, ciphertext FROM oauth_credentials WHERE user_id = %s",
                (user_id,),
            )
            return {r["provider"]: bytes(r["ciphertext"]) for r in await cur.fetchall()}

    async def delete(self, user_id: str, provider: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM oauth_credentials WHERE user_id = %s AND provider = %s",
                (user_id, provider),
            )

    async def save_pending(self, pending: PendingAuthorization, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM oauth_states WHERE expires_at < %s", (now,))
            await conn.execute(
                "INSERT INTO oauth_states (state, user_id, provider, code_verifier, expires_at) "
                "VALUES (%s, %s, %s, %s, %s)",
                (
                    pending.state,
                    pending.user_id,
                    pending.provider,
                    pending.code_verifier,
                    pending.expires_at,
                ),
            )

    async def pop_pending(self, state: str) -> PendingAuthorization | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "DELETE FROM oauth_states WHERE state = %s RETURNING *", (state,)
            )
            row = await cur.fetchone()
            return PendingAuthorization(**row) if row else None
