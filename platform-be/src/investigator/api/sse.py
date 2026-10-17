"""Server-Sent Events plumbing shared by the progress and chat streams."""

from __future__ import annotations

import json
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Tell reverse proxies (nginx) not to hold the stream back.
    "X-Accel-Buffering": "no",
}

KEEP_ALIVE = ": keep-alive\n\n"


def frame(event: str, data: Any, event_id: int | None = None) -> str:
    """One SSE message. `data` is JSON, so a newline inside it can never end the frame."""
    lines = [f"event: {event}", f"data: {json.dumps(data, default=str)}"]
    if event_id is not None:
        lines.insert(0, f"id: {event_id}")
    return "\n".join(lines) + "\n\n"
