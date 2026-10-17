"""Users, sessions and in-flight sign-in attempts. Only a hash of a session token is stored."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg_pool import AsyncConnectionPool

from investigator.auth.models import Kind, Principal, User, principal_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY,
    kind text NOT NULL DEFAULT 'user',
    google_sub text UNIQUE,
    email text,
    name text,
    picture text,
    created_ip text,
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS users_demo_idx ON users (kind, last_seen_at);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    ip text,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
CREATE TABLE IF NOT EXISTS auth_states (
    state text PRIMARY KEY,
    verifier text NOT NULL,
    nonce text NOT NULL,
    next text NOT NULL,
    expires_at timestamptz NOT NULL
);
"""


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class PendingLogin:
    state: str
    verifier: str
    nonce: str
    next: str
    expires_at: datetime


class AuthStore(Protocol):
    async def upsert_google(
        self, sub: str, email: str | None, name: str | None, picture: str | None
    ) -> User: ...

    async def create_demo(self, ip: str | None) -> User: ...

    async def demos_from(self, ip: str, since: datetime) -> int: ...

    async def create_session(
        self,
        user_id: UUID,
        token: str,
        expires_at: datetime,
        ip: str | None,
        agent: str | None,
    ) -> None: ...

    async def principal(
        self, token: str, now: datetime, extend_to: datetime | None
    ) -> Principal | None: ...

    async def end_session(self, token: str) -> None: ...

    async def save_state(self, pending: PendingLogin, now: datetime) -> None: ...

    async def pop_state(self, state: str) -> PendingLogin | None: ...

    async def idle_demo_ids(self, before: datetime) -> list[UUID]: ...

    async def delete_users(self, ids: list[UUID]) -> None: ...


class PostgresAuthStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)

    @staticmethod
    def _user(r: dict[str, Any]) -> User:
        return User(
            id=r["id"], kind=r["kind"], email=r["email"], name=r["name"], picture=r["picture"],
            google_sub=r["google_sub"], created_at=r["created_at"],
        )  # fmt: skip

    async def upsert_google(
        self, sub: str, email: str | None, name: str | None, picture: str | None
    ) -> User:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO users (id, kind, google_sub, email, name, picture) "
                "VALUES (%s, 'user', %s, %s, %s, %s) ON CONFLICT (google_sub) DO UPDATE SET "
                "email = EXCLUDED.email, name = EXCLUDED.name, picture = EXCLUDED.picture, "
                "last_seen_at = now() RETURNING *",
                (uuid4(), sub, email, name, picture),
            )
            row = await cur.fetchone()
            assert row is not None
            return self._user(row)

    async def create_demo(self, ip: str | None) -> User:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "INSERT INTO users (id, kind, name, created_ip) VALUES (%s, 'demo', 'Demo visitor', %s) RETURNING *",
                (uuid4(), ip),
            )
            row = await cur.fetchone()
            assert row is not None
            return self._user(row)

    async def demos_from(self, ip: str, since: datetime) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM users WHERE kind = 'demo' AND created_ip = %s AND created_at >= %s",
                (ip, since),
            )
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

    async def create_session(
        self,
        user_id: UUID,
        token: str,
        expires_at: datetime,
        ip: str | None,
        agent: str | None,
    ) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at, ip, user_agent) VALUES (%s,%s,%s,%s,%s)",
                (digest(token), user_id, expires_at, ip, (agent or "")[:200]),
            )

    async def principal(
        self, token: str, now: datetime, extend_to: datetime | None
    ) -> Principal | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE s.token_hash = %s AND s.expires_at > %s",
                (digest(token), now),
            )
            row = await cur.fetchone()
            if row is None:
                return None
            if extend_to is not None:
                await conn.execute(
                    "UPDATE sessions SET expires_at = %s WHERE token_hash = %s",
                    (extend_to, digest(token)),
                )
            await conn.execute(
                "UPDATE users SET last_seen_at = %s WHERE id = %s", (now, row["id"])
            )
            return principal_of(self._user(row))

    async def end_session(self, token: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM sessions WHERE token_hash = %s", (digest(token),)
            )

    async def save_state(self, pending: PendingLogin, now: datetime) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM auth_states WHERE expires_at < %s", (now,))
            await conn.execute(
                "INSERT INTO auth_states (state, verifier, nonce, next, expires_at) VALUES (%s,%s,%s,%s,%s)",
                (
                    pending.state,
                    pending.verifier,
                    pending.nonce,
                    pending.next,
                    pending.expires_at,
                ),
            )

    async def pop_state(self, state: str) -> PendingLogin | None:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "DELETE FROM auth_states WHERE state = %s RETURNING *", (state,)
            )
            r = await cur.fetchone()
            return (
                PendingLogin(
                    r["state"], r["verifier"], r["nonce"], r["next"], r["expires_at"]
                )
                if r
                else None
            )

    async def idle_demo_ids(self, before: datetime) -> list[UUID]:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT id FROM users WHERE kind = 'demo' AND last_seen_at < %s",
                (before,),
            )
            return [r["id"] for r in await cur.fetchall()]

    async def delete_users(self, ids: list[UUID]) -> None:
        if not ids:
            return
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM sessions WHERE user_id = ANY(%s)", (ids,))
            await conn.execute("DELETE FROM users WHERE id = ANY(%s)", (ids,))


class MemoryAuthStore:
    """For tests and single-process development."""

    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.seen: dict[UUID, datetime] = {}
        self.ips: dict[UUID, str | None] = {}
        self.sessions: dict[str, tuple[UUID, datetime]] = {}
        self.states: dict[str, PendingLogin] = {}

    async def upsert_google(
        self, sub: str, email: str | None, name: str | None, picture: str | None
    ) -> User:
        found = next((u for u in self.users.values() if u.google_sub == sub), None)
        user = User(
            id=found.id if found else uuid4(), kind="user", google_sub=sub, email=email, name=name,
            picture=picture, created_at=found.created_at if found else datetime.now(UTC),
        )  # fmt: skip
        self.users[user.id] = user
        return user

    async def create_demo(self, ip: str | None) -> User:
        user = User(
            id=uuid4(), kind="demo", name="Demo visitor", created_at=datetime.now(UTC)
        )
        self.users[user.id] = user
        self.ips[user.id] = ip
        self.seen[user.id] = datetime.now(UTC)
        return user

    async def demos_from(self, ip: str, since: datetime) -> int:
        return sum(
            1 for i, u in self.users.items()
            if u.kind == "demo" and self.ips.get(i) == ip and (u.created_at or since) >= since
        )  # fmt: skip

    async def create_session(
        self,
        user_id: UUID,
        token: str,
        expires_at: datetime,
        ip: str | None,
        agent: str | None,
    ) -> None:
        self.sessions[digest(token)] = (user_id, expires_at)

    async def principal(
        self, token: str, now: datetime, extend_to: datetime | None
    ) -> Principal | None:
        got = self.sessions.get(digest(token))
        if got is None or got[1] <= now:
            return None
        if extend_to is not None:
            self.sessions[digest(token)] = (got[0], extend_to)
        self.seen[got[0]] = now
        return principal_of(self.users[got[0]])

    async def end_session(self, token: str) -> None:
        self.sessions.pop(digest(token), None)

    async def save_state(self, pending: PendingLogin, now: datetime) -> None:
        self.states = {k: v for k, v in self.states.items() if v.expires_at >= now}
        self.states[pending.state] = pending

    async def pop_state(self, state: str) -> PendingLogin | None:
        return self.states.pop(state, None)

    async def idle_demo_ids(self, before: datetime) -> list[UUID]:
        return [
            i
            for i, u in self.users.items()
            if u.kind == "demo" and self.seen.get(i, before) < before
        ]

    async def delete_users(self, ids: list[UUID]) -> None:
        for i in ids:
            self.users.pop(i, None)
            self.sessions = {k: v for k, v in self.sessions.items() if v[0] != i}


_ = (Kind, timedelta)
