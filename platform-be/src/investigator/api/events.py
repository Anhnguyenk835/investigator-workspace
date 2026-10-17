"""Live progress of an investigation run, as Server-Sent Events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from investigator.api.session import visible_investigation
from investigator.api.sse import KEEP_ALIVE, SSE_HEADERS, frame

router = APIRouter(tags=["investigations"])

POLL_SECONDS = 0.4
KEEP_ALIVE_SECONDS = 15.0
RUNNING = {"queued", "investigating"}


@router.get("/investigations/{investigation_id}/events")
async def investigation_events(
    investigation_id: UUID, request: Request, after: int = 0
) -> StreamingResponse:
    """Replays stored events after `after` (or `Last-Event-ID`), then follows new ones.

    The stream ends with an `end` event once the investigation is at rest and the
    client has everything, so a browser's automatic reconnect is not triggered.
    """
    app_state = request.app.state.app
    if app_state.events is None:
        raise HTTPException(503, "Progress events are not available.")
    await visible_investigation(request, investigation_id)
    header = request.headers.get("last-event-id", "")
    last = int(header) if header.isdigit() else after

    async def stream() -> AsyncIterator[str]:
        nonlocal last
        quiet = 0.0
        while not await request.is_disconnected():
            batch = await app_state.events.after(investigation_id, last)
            for event in batch:
                last = event.id
                yield frame(
                    event.kind,
                    {**event.data, "at": event.at.isoformat()},
                    event_id=event.id,
                )
            if batch:
                quiet = 0.0
                continue
            record = await app_state.store.get(investigation_id)
            if record is None or record.status not in RUNNING:
                yield frame("end", {"status": record.status if record else "gone"})
                return
            await asyncio.sleep(POLL_SECONDS)
            quiet += POLL_SECONDS
            if quiet >= KEEP_ALIVE_SECONDS:
                quiet = 0.0
                yield KEEP_ALIVE

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers=SSE_HEADERS
    )
