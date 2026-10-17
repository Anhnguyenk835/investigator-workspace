from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from investigator.chat.models import (
    DEFAULT_TITLE,
    Conversation,
    StoredMessage,
    title_from,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id uuid PRIMARY KEY,
    investigation_id uuid NOT NULL,
    role text NOT NULL,
    content text NOT NULL,
    meta jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_messages_inv_idx
    ON chat_messages (investigation_id, created_at);
CREATE TABLE IF NOT EXISTS chat_conversations (
    id uuid PRIMARY KEY,
    investigation_id uuid NOT NULL,
    title text NOT NULL DEFAULT 'New chat',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS chat_conversations_inv_idx
    ON chat_conversations (investigation_id, updated_at DESC);
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS conversation_id uuid;
ALTER TABLE chat_conversations ADD COLUMN IF NOT EXISTS owner_id text;
CREATE INDEX IF NOT EXISTS chat_messages_conv_idx
    ON chat_messages (conversation_id, created_at);
"""

# Messages written before conversations existed become one conversation per investigation.
MIGRATE = """
WITH orphans AS (
    SELECT investigation_id, min(created_at) AS first_at, max(created_at) AS last_at,
           (array_agg(content ORDER BY created_at) FILTER (WHERE role = 'user'))[1] AS first_q
    FROM chat_messages WHERE conversation_id IS NULL GROUP BY investigation_id
), made AS (
    INSERT INTO chat_conversations (id, investigation_id, title, created_at, updated_at)
    SELECT gen_random_uuid(), investigation_id, left(coalesce(first_q, 'Conversation'), 60),
           first_at, last_at FROM orphans
    RETURNING id, investigation_id
)
UPDATE chat_messages m SET conversation_id = made.id
FROM made WHERE m.investigation_id = made.investigation_id AND m.conversation_id IS NULL;
"""

Conversations = list[Conversation]

META = ("citations", "new_evidence", "warnings", "tools")


class ChatStore(Protocol):
    async def add(
        self,
        investigation_id: UUID,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
        conversation_id: UUID | None = None,
    ) -> StoredMessage: ...

    async def list(
        self,
        investigation_id: UUID,
        limit: int = 200,
        conversation_id: UUID | None = None,
    ) -> list[StoredMessage]: ...

    async def clear(
        self, investigation_id: UUID, conversation_id: UUID | None = None
    ) -> None: ...

    async def conversations(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> Conversations: ...

    async def create_conversation(
        self,
        investigation_id: UUID,
        title: str = DEFAULT_TITLE,
        owner_id: str | None = None,
    ) -> Conversation: ...

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...

    async def rename(self, conversation_id: UUID, title: str) -> None: ...

    async def delete_conversation(self, conversation_id: UUID) -> None: ...

    async def default_conversation(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> Conversation: ...

    async def count_questions(self, owner_id: str) -> int:
        """How many questions this account has asked, across its conversations."""
        ...

    async def delete_by_owner(self, owner_id: str) -> int:
        """Every conversation (and its messages) this account started, anywhere."""
        ...


def _model(row: dict[str, Any]) -> StoredMessage:
    return StoredMessage(
        id=row["id"],
        investigation_id=row["investigation_id"],
        conversation_id=row.get("conversation_id"),
        role=row["role"],
        content=row["content"],
        created_at=row["created_at"],
        **(row["meta"] or {}),
    )


CONV_SELECT = (
    "SELECT c.*, (SELECT count(*) FROM chat_messages m WHERE m.conversation_id = c.id) "
    "AS message_count FROM chat_conversations c"
)


class PostgresChatStore:
    """Expects a pool opened with autocommit=True and row_factory=dict_row."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def setup(self) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(SCHEMA)
            await conn.execute(MIGRATE)

    # ---- conversations -------------------------------------------------------------

    async def conversations(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> list[Conversation]:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                f"{CONV_SELECT} WHERE c.investigation_id = %s "
                "AND c.owner_id IS NOT DISTINCT FROM %s ORDER BY c.updated_at DESC",
                (investigation_id, owner_id),
            )
            return [Conversation(**r) for r in await cur.fetchall()]

    async def create_conversation(
        self,
        investigation_id: UUID,
        title: str = DEFAULT_TITLE,
        owner_id: str | None = None,
    ) -> Conversation:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "INSERT INTO chat_conversations (id, investigation_id, title, owner_id) "
                "VALUES (%s, %s, %s, %s) RETURNING *, 0 AS message_count",
                (uuid4(), investigation_id, title, owner_id),
            )
            row = await cur.fetchone()
            assert row is not None
            return Conversation(**row)

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(f"{CONV_SELECT} WHERE c.id = %s", (conversation_id,))
            row = await cur.fetchone()
            return Conversation(**row) if row else None

    async def rename(self, conversation_id: UUID, title: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "UPDATE chat_conversations SET title = %s WHERE id = %s",
                (title, conversation_id),
            )

    async def delete_conversation(self, conversation_id: UUID) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM chat_messages WHERE conversation_id = %s",
                (conversation_id,),
            )
            await conn.execute(
                "DELETE FROM chat_conversations WHERE id = %s", (conversation_id,)
            )

    async def default_conversation(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> Conversation:
        """The most recently used conversation; one is made if there is none."""
        found = await self.conversations(investigation_id, owner_id)
        return (
            found[0]
            if found
            else await self.create_conversation(investigation_id, owner_id=owner_id)
        )

    # ---- messages ------------------------------------------------------------------

    async def delete_by_owner(self, owner_id: str) -> int:
        async with self._pool.connection() as conn:
            mine = "(SELECT id FROM chat_conversations WHERE owner_id = %s)"
            await conn.execute(
                f"DELETE FROM chat_messages WHERE conversation_id IN {mine}",
                (owner_id,),
            )
            cur = await conn.execute(
                "DELETE FROM chat_conversations WHERE owner_id = %s", (owner_id,)
            )
            return int(cur.rowcount)

    async def count_questions(self, owner_id: str) -> int:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                "SELECT count(*) AS n FROM chat_messages m JOIN chat_conversations c "
                "ON c.id = m.conversation_id WHERE c.owner_id = %s AND m.role = 'user'",
                (owner_id,),
            )
            row = await cur.fetchone()
            return int(row["n"]) if row else 0

    async def add(
        self,
        investigation_id: UUID,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
        conversation_id: UUID | None = None,
    ) -> StoredMessage:
        if conversation_id is None:
            conversation_id = (await self.default_conversation(investigation_id)).id
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "INSERT INTO chat_messages (id, investigation_id, conversation_id, role, content, meta) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (
                    uuid4(),
                    investigation_id,
                    conversation_id,
                    role,
                    content,
                    Jsonb(meta or {}),
                ),
            )
            row = await cur.fetchone()
            assert row is not None
            # A conversation is named after its first question and moves to the top.
            await cur.execute(
                "UPDATE chat_conversations SET updated_at = now(), "
                "title = CASE WHEN title = %s AND %s = 'user' THEN %s ELSE title END WHERE id = %s",
                (DEFAULT_TITLE, role, title_from(content), conversation_id),
            )
            return _model(row)

    async def list(
        self,
        investigation_id: UUID,
        limit: int = 200,
        conversation_id: UUID | None = None,
    ) -> list[StoredMessage]:
        if conversation_id is None:
            conversation_id = (await self.default_conversation(investigation_id)).id
        async with (
            self._pool.connection() as conn,
            conn.cursor(row_factory=dict_row) as cur,
        ):
            await cur.execute(
                "SELECT * FROM (SELECT * FROM chat_messages WHERE conversation_id = %s "
                "ORDER BY created_at DESC, id DESC LIMIT %s) t ORDER BY created_at, id",
                (conversation_id, limit),
            )
            return [_model(r) for r in await cur.fetchall()]

    async def clear(
        self, investigation_id: UUID, conversation_id: UUID | None = None
    ) -> None:
        """One conversation's messages, or every conversation of the investigation."""
        async with self._pool.connection() as conn:
            if conversation_id is not None:
                await conn.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                return
            await conn.execute(
                "DELETE FROM chat_messages WHERE investigation_id = %s",
                (investigation_id,),
            )
            await conn.execute(
                "DELETE FROM chat_conversations WHERE investigation_id = %s",
                (investigation_id,),
            )


class MemoryChatStore:
    """For tests and single-process development."""

    def __init__(self) -> None:
        self.items: list[StoredMessage] = []
        self.convs: dict[UUID, Conversation] = {}

    def _counted(self, c: Conversation) -> Conversation:
        n = sum(1 for m in self.items if m.conversation_id == c.id)
        return c.model_copy(update={"message_count": n})

    async def conversations(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> list[Conversation]:
        mine = [
            c
            for c in self.convs.values()
            if c.investigation_id == investigation_id and c.owner_id == owner_id
        ]
        return [
            self._counted(c)
            for c in sorted(mine, key=lambda c: c.updated_at, reverse=True)
        ]

    async def create_conversation(
        self,
        investigation_id: UUID,
        title: str = DEFAULT_TITLE,
        owner_id: str | None = None,
    ) -> Conversation:
        now = datetime.now(UTC)
        c = Conversation(
            id=uuid4(), investigation_id=investigation_id, owner_id=owner_id, title=title,
            created_at=now, updated_at=now,
        )  # fmt: skip
        self.convs[c.id] = c
        return c

    async def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        c = self.convs.get(conversation_id)
        return self._counted(c) if c else None

    async def rename(self, conversation_id: UUID, title: str) -> None:
        if conversation_id in self.convs:
            self.convs[conversation_id] = self.convs[conversation_id].model_copy(
                update={"title": title}
            )

    async def delete_conversation(self, conversation_id: UUID) -> None:
        self.items = [m for m in self.items if m.conversation_id != conversation_id]
        self.convs.pop(conversation_id, None)

    async def default_conversation(
        self, investigation_id: UUID, owner_id: str | None = None
    ) -> Conversation:
        found = await self.conversations(investigation_id, owner_id)
        return (
            found[0]
            if found
            else await self.create_conversation(investigation_id, owner_id=owner_id)
        )

    async def delete_by_owner(self, owner_id: str) -> int:
        mine = {c.id for c in self.convs.values() if c.owner_id == owner_id}
        self.items = [m for m in self.items if m.conversation_id not in mine]
        for i in mine:
            del self.convs[i]
        return len(mine)

    async def count_questions(self, owner_id: str) -> int:
        mine = {c.id for c in self.convs.values() if c.owner_id == owner_id}
        return sum(
            1 for m in self.items if m.conversation_id in mine and m.role == "user"
        )

    async def add(
        self,
        investigation_id: UUID,
        role: str,
        content: str,
        meta: dict[str, Any] | None = None,
        conversation_id: UUID | None = None,
    ) -> StoredMessage:
        if conversation_id is None:
            conversation_id = (await self.default_conversation(investigation_id)).id
        message = StoredMessage(
            id=uuid4(),
            investigation_id=investigation_id,
            conversation_id=conversation_id,
            role=role,  # type: ignore[arg-type]
            content=content,
            created_at=datetime.now(UTC),
            **(meta or {}),
        )
        self.items.append(message)
        c = self.convs[conversation_id]
        update: dict[str, Any] = {"updated_at": message.created_at}
        if c.title == DEFAULT_TITLE and role == "user":
            update["title"] = title_from(content)
        self.convs[conversation_id] = c.model_copy(update=update)
        return message

    async def list(
        self,
        investigation_id: UUID,
        limit: int = 200,
        conversation_id: UUID | None = None,
    ) -> list[StoredMessage]:
        if conversation_id is None:
            conversation_id = (await self.default_conversation(investigation_id)).id
        return [m for m in self.items if m.conversation_id == conversation_id][-limit:]

    async def clear(
        self, investigation_id: UUID, conversation_id: UUID | None = None
    ) -> None:
        if conversation_id is not None:
            self.items = [m for m in self.items if m.conversation_id != conversation_id]
            return
        self.items = [m for m in self.items if m.investigation_id != investigation_id]
        self.convs = {
            k: c
            for k, c in self.convs.items()
            if c.investigation_id != investigation_id
        }
