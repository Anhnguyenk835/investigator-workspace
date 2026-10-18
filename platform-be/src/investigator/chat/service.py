"""One conversation turn: persist the question, stream the answer, persist the answer."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from investigator.agents.chat import ChatState
from investigator.agents.chat.context import render_context
from investigator.auth import LOCAL, Principal, can_read, directory_owner, owner_for_new
from investigator.chat.availability import Availability, SourceNow
from investigator.chat.models import Conversation, StoredMessage
from investigator.chat.store import ChatStore
from investigator.directory import DirectoryStore
from investigator.guardrails import bind
from investigator.guardrails.pii.names import directory_names
from investigator.investigations.store import InvestigationStore
from investigator.llm import ChatMessage
from investigator.tools import AccessContext

log = logging.getLogger(__name__)

RUNNING = {"queued", "investigating"}
MAX_MESSAGE_CHARS = 4000

ChatEvent = tuple[str, dict[str, Any]]


class ChatUnavailableError(Exception):
    """The request cannot start a turn; `status` is the HTTP code to answer with."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def message_out(m: StoredMessage) -> dict[str, Any]:
    return m.model_dump(mode="json")


class ChatService:
    def __init__(
        self,
        graph: Any,
        chats: ChatStore,
        investigations: InvestigationStore,
        access: AccessContext,
        directory: DirectoryStore | None = None,
        demo_max_turns: int = 40,
        availability: Availability | None = None,
    ) -> None:
        self._availability = availability
        self._demo_max_turns = demo_max_turns
        self._directory = directory
        self._graph = graph
        self._chats = chats
        self._investigations = investigations
        self._access = access
        self._active: set[UUID] = set()

    async def _sources_now(self, principal: Principal) -> list[SourceNow] | None:
        """What this person has connected at the time of the question; None when unknown
        (then the conversation falls back to the sources the server can read)."""
        if self._availability is None:
            return None
        try:
            return await self._availability(principal)
        except Exception:
            log.warning("source availability could not be read", exc_info=True)
            return None

    @staticmethod
    def _owner(principal: Principal) -> str | None:
        """Conversations belong to the account that started them."""
        return owner_for_new(principal)

    async def history(
        self,
        investigation_id: UUID,
        conversation_id: UUID | None = None,
        principal: Principal = LOCAL,
    ) -> list[StoredMessage]:
        if conversation_id is None:
            conversation_id = (
                await self._chats.default_conversation(
                    investigation_id, self._owner(principal)
                )
            ).id
        else:
            await self.conversation(investigation_id, conversation_id, principal)
        return await self._chats.list(investigation_id, conversation_id=conversation_id)

    async def clear(
        self,
        investigation_id: UUID,
        conversation_id: UUID | None = None,
        principal: Principal = LOCAL,
    ) -> None:
        """One conversation's messages, or all of this person's for the investigation."""
        if conversation_id is not None:
            await self.conversation(investigation_id, conversation_id, principal)
            await self._chats.clear(investigation_id, conversation_id)
            return
        for c in await self._chats.conversations(
            investigation_id, self._owner(principal)
        ):
            await self._chats.delete_conversation(c.id)

    # ---- conversations -------------------------------------------------------------

    async def conversations(
        self, investigation_id: UUID, principal: Principal = LOCAL
    ) -> list[Conversation]:
        """Those with something in them: a new chat that was never asked anything is not listed."""
        found = await self._chats.conversations(
            investigation_id, self._owner(principal)
        )
        return [c for c in found if c.message_count > 0]

    async def conversation(
        self,
        investigation_id: UUID,
        conversation_id: UUID,
        principal: Principal = LOCAL,
    ) -> Conversation:
        """The conversation, if it is this person's and belongs to this investigation."""
        found = await self._chats.get_conversation(conversation_id)
        if (
            found is None
            or found.investigation_id != investigation_id
            or found.owner_id != self._owner(principal)
        ):
            raise ChatUnavailableError(404, "Conversation not found.")
        return found

    async def forget(self, owner_id: str) -> None:
        """Delete a (demo) account's conversations."""
        await self._chats.delete_by_owner(owner_id)

    async def create(
        self, investigation_id: UUID, principal: Principal = LOCAL
    ) -> Conversation:
        return await self._chats.create_conversation(
            investigation_id, owner_id=self._owner(principal)
        )

    async def rename(
        self,
        investigation_id: UUID,
        conversation_id: UUID,
        title: str,
        principal: Principal = LOCAL,
    ) -> Conversation:
        await self.conversation(investigation_id, conversation_id, principal)
        await self._chats.rename(conversation_id, title)
        return await self.conversation(investigation_id, conversation_id, principal)

    async def delete(
        self,
        investigation_id: UUID,
        conversation_id: UUID,
        principal: Principal = LOCAL,
    ) -> None:
        await self.conversation(investigation_id, conversation_id, principal)
        await self._chats.delete_conversation(conversation_id)

    async def check(
        self,
        investigation_id: UUID,
        conversation_id: UUID | None = None,
        principal: Principal = LOCAL,
    ) -> None:
        """Raise if a turn cannot start now. Nothing is written."""
        record = await self._investigations.get(investigation_id)
        if record is None or not can_read(principal, record.owner_id):
            raise ChatUnavailableError(404, "Investigation not found.")
        if record.status in RUNNING:
            raise ChatUnavailableError(
                409,
                "The investigation is still running. Ask again when it has finished.",
            )
        if conversation_id is not None:
            await self.conversation(investigation_id, conversation_id, principal)
        if (
            principal.is_demo
            and await self._chats.count_questions(principal.user_id)
            >= self._demo_max_turns
        ):
            raise ChatUnavailableError(
                429,
                f"The demo allows {self._demo_max_turns} questions. "
                "Sign in with Google to keep going.",
            )
        if (conversation_id or investigation_id) in self._active:
            raise ChatUnavailableError(409, "The assistant is still answering.")

    async def stream(
        self,
        investigation_id: UUID,
        text: str,
        *,
        conversation_id: UUID | None = None,
        actor: str | None = None,
        ip: str | None = None,
        principal: Principal = LOCAL,
        verified: bool = False,
    ) -> AsyncIterator[ChatEvent]:
        """Events of one turn: user_message, delta, turn_end, tool, done | error."""
        busy = conversation_id or investigation_id
        if busy in self._active:
            yield "error", {"message": "The assistant is still answering."}
            return
        self._active.add(busy)
        try:
            record = await self._investigations.get(investigation_id)
            if record is None or not can_read(principal, record.owner_id):
                yield "error", {"message": "Investigation not found."}
                return
            if conversation_id is None:
                conversation_id = (
                    await self._chats.default_conversation(
                        investigation_id, self._owner(principal)
                    )
                ).id
            else:
                await self.conversation(investigation_id, conversation_id, principal)
            prior = await self._chats.list(
                investigation_id, conversation_id=conversation_id
            )
            asked = await self._chats.add(
                investigation_id, "user", text, conversation_id=conversation_id
            )
            yield "user_message", message_out(asked)

            now = await self._sources_now(principal)
            state = ChatState(
                question=text,
                history=[ChatMessage(role=m.role, content=m.content) for m in prior],
                context_text=render_context(record, now),
                known_ids=[e.id for e in record.evidence],
                context=record.context,
                evidence=list(record.evidence),
                coverage=list(record.coverage),
            )
            directory = (
                await self._directory.load(directory_owner(principal))
                if self._directory
                else None
            )
            access = self._access.model_copy(
                update={
                    "user_id": principal.user_id,
                    "demo": principal.is_demo,
                    # Only what is connected now is offered as a tool: the rest cannot be
                    # searched, and the model is told so by name.
                    "permitted_sources": self._access.permitted_sources
                    & {x.source for x in now if x.state == "connected"}
                    if now is not None
                    else self._access.permitted_sources,
                }
            )
            config = {
                "configurable": {"access": access, "directory": directory},
                "recursion_limit": 40,
            }
            tools: list[dict[str, Any]] = []
            final: Any = None
            with bind(
                run_id=str(investigation_id),
                thread_id=f"chat-{uuid4()}",  # one turn: the budget for a turn is its own
                actor=actor,
                ip=ip,
                verified=verified,
                demo=principal.is_demo,
                purpose="chat",
                names=directory_names(directory),
            ):
                async for mode, chunk in self._graph.astream(
                    state, config=config, stream_mode=["custom", "values"]
                ):
                    if mode == "values":
                        final = chunk
                        continue
                    kind = chunk.get("type")
                    if kind == "tool":
                        tools.append({k: v for k, v in chunk.items() if k != "type"})
                    yield str(kind), {k: v for k, v in chunk.items() if k != "type"}

            result = (
                final if isinstance(final, ChatState) else ChatState(**(final or {}))
            )
            if result.error or not result.answer:
                yield (
                    "error",
                    {"message": result.error or "The assistant returned no answer."},
                )
                return
            answered = await self._chats.add(
                investigation_id,
                "assistant",
                result.answer,
                {
                    "citations": result.citations,
                    "new_evidence": [
                        e.model_dump(mode="json") for e in result.new_evidence
                    ],
                    "warnings": result.warnings,
                    "tools": tools,
                },
                conversation_id=asked.conversation_id,
            )
            yield "done", {"message": message_out(answered)}
        except Exception as exc:  # noqa: BLE001  a failed turn must reach the client
            yield "error", {"message": f"{type(exc).__name__}: {exc}"}
        finally:
            self._active.discard(busy)
