"""Conversation about one investigation, streamed as Server-Sent Events."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from investigator.api.dispatch import actor_of, ip_of, verified_actor
from investigator.api.session import principal_of, visible_investigation
from investigator.api.sse import SSE_HEADERS, frame
from investigator.chat import ChatService, ChatUnavailableError
from investigator.chat.service import MAX_MESSAGE_CHARS, message_out

router = APIRouter(tags=["chat"])


class SendMessage(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class RenameConversation(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _chat(request: Request) -> ChatService:
    service: ChatService | None = request.app.state.app.chat
    if service is None:
        raise HTTPException(
            503, "The assistant is not available. Set LITELLM_API_KEY and restart."
        )
    return service


async def _investigation(
    request: Request, investigation_id: UUID, *, write: bool = False
) -> None:
    await visible_investigation(request, investigation_id, write=write)


def _stream(
    service: ChatService,
    request: Request,
    investigation_id: UUID,
    conversation_id: UUID | None,
    text: str,
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        async for name, data in service.stream(
            investigation_id,
            text,
            conversation_id=conversation_id,
            actor=actor_of(request),
            ip=ip_of(request),
            principal=principal_of(request),
            verified=verified_actor(request),
        ):
            yield frame(name, data)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )


async def _send(
    request: Request,
    investigation_id: UUID,
    conversation_id: UUID | None,
    body: SendMessage,
) -> StreamingResponse:
    service = _chat(request)
    text = body.message.strip()
    if not text:
        raise HTTPException(422, "The message is empty.")
    try:
        await service.check(investigation_id, conversation_id, principal_of(request))
    except ChatUnavailableError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    return _stream(service, request, investigation_id, conversation_id, text)


# ---- conversations: many per investigation ------------------------------------------


@router.get("/investigations/{investigation_id}/conversations")
async def conversations(investigation_id: UUID, request: Request) -> dict[str, Any]:
    service = _chat(request)
    await _investigation(request, investigation_id)
    found = await service.conversations(investigation_id, principal_of(request))
    return {"conversations": [c.model_dump(mode="json") for c in found]}


@router.post("/investigations/{investigation_id}/conversations", status_code=201)
async def create_conversation(
    investigation_id: UUID, request: Request
) -> dict[str, Any]:
    service = _chat(request)
    await _investigation(request, investigation_id)
    return (await service.create(investigation_id, principal_of(request))).model_dump(
        mode="json"
    )


@router.patch("/investigations/{investigation_id}/conversations/{conversation_id}")
async def rename_conversation(
    investigation_id: UUID,
    conversation_id: UUID,
    body: RenameConversation,
    request: Request,
) -> dict[str, Any]:
    service = _chat(request)
    title = " ".join(body.title.split())
    if not title:
        raise HTTPException(422, "The title is empty.")
    try:
        return (
            await service.rename(
                investigation_id, conversation_id, title, principal_of(request)
            )
        ).model_dump(mode="json")
    except ChatUnavailableError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.delete(
    "/investigations/{investigation_id}/conversations/{conversation_id}",
    status_code=204,
)
async def delete_conversation(
    investigation_id: UUID, conversation_id: UUID, request: Request
) -> None:
    service = _chat(request)
    try:
        await service.delete(investigation_id, conversation_id, principal_of(request))
    except ChatUnavailableError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.get(
    "/investigations/{investigation_id}/conversations/{conversation_id}/messages"
)
async def conversation_messages(
    investigation_id: UUID, conversation_id: UUID, request: Request
) -> dict[str, Any]:
    service = _chat(request)
    try:
        await service.conversation(
            investigation_id, conversation_id, principal_of(request)
        )
    except ChatUnavailableError as exc:
        raise HTTPException(exc.status, str(exc)) from exc
    rows = await service.history(
        investigation_id, conversation_id, principal_of(request)
    )
    return {"messages": [message_out(m) for m in rows]}


@router.post("/investigations/{investigation_id}/conversations/{conversation_id}/chat")
async def send_in_conversation(
    investigation_id: UUID, conversation_id: UUID, body: SendMessage, request: Request
) -> StreamingResponse:
    """Streams the answer inside one conversation. Same events as the single-chat endpoint."""
    return await _send(request, investigation_id, conversation_id, body)


# ---- the single conversation of before: the most recently used one -------------------


@router.get("/investigations/{investigation_id}/chat")
async def history(investigation_id: UUID, request: Request) -> dict[str, Any]:
    service = _chat(request)
    await _investigation(request, investigation_id)
    return {
        "messages": [message_out(m) for m in await service.history(investigation_id)]
    }


@router.post("/investigations/{investigation_id}/chat")
async def send(
    investigation_id: UUID, body: SendMessage, request: Request
) -> StreamingResponse:
    """Streams the answer. Events: `user_message`, `delta`, `turn_end`, `tool`, then
    `done` (with the stored message) or `error`. The connection ends after that."""
    return await _send(request, investigation_id, None, body)


@router.delete("/investigations/{investigation_id}/chat", status_code=204)
async def clear(investigation_id: UUID, request: Request) -> None:
    service = _chat(request)
    await _investigation(request, investigation_id)
    await service.clear(investigation_id, principal=principal_of(request))
