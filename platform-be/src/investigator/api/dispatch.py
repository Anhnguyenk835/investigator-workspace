"""Hand a run to the queue (or, with no queue, to this process)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Request
from langgraph.types import Command

from investigator.auth import LOCAL, Principal, directory_owner
from investigator.auth.models import LOCAL_ID
from investigator.investigations import run_investigation
from investigator.investigations.runner import thread_id_for
from investigator.jobs.models import JobKind


def actor_of(request: Request) -> str | None:
    """Who did it: the signed-in account, or (sign-in off) the name the browser sent, which is
    a label and not a login."""
    p: Principal | None = getattr(request.state, "principal", None)
    if p is not None and p.user_id != LOCAL_ID:
        return p.actor[:80]
    name = " ".join(request.headers.get("x-actor", "").split())[:80]
    return name or None


def verified_actor(request: Request) -> bool:
    p: Principal | None = getattr(request.state, "principal", None)
    return p is not None and p.user_id != LOCAL_ID


def ip_of(request: Request) -> str | None:
    """The address the request came from. Behind a proxy this is the proxy until the
    deployment says which hops to trust; it keys quotas and audit, and proves nothing."""
    return request.client.host if request.client else None


async def dispatch(
    app_state: Any,
    background: BackgroundTasks,
    *,
    kind: JobKind,
    investigation_id: UUID,
    run_no: int,
    payload: dict[str, Any],
    actor: str | None,
    ip: str | None = None,
    principal: Principal = LOCAL,
) -> None:
    """`payload` is {"question", "context"} for a start or re-run, {"resume": value} to resume."""
    if app_state.queue is not None:
        await app_state.queue.enqueue(
            kind,
            investigation_id,
            {
                **payload,
                "run_no": run_no,
                "actor": actor,
                "ip": ip,
                "user_id": principal.user_id,
                "demo": principal.is_demo,
                "verified": principal.user_id != LOCAL_ID,
            },
        )
        return
    start: dict[str, Any] | Command[Any] = (
        Command(resume=payload["resume"])
        if kind == "resume"
        else {"question": payload["question"], "context": payload["context"]}
    )
    background.add_task(
        run_investigation,
        app_state.graph,
        app_state.store,
        investigation_id,
        start,
        app_state.access.model_copy(
            update={"user_id": principal.user_id, "demo": principal.is_demo}
        ),
        events=app_state.events,
        directory=await app_state.directory.load(directory_owner(principal))
        if app_state.directory
        else None,
        thread_id=thread_id_for(investigation_id, run_no),
        actor=actor,
        ip=ip,
        verified=principal.user_id != LOCAL_ID,
        demo=principal.is_demo,
        mode="rerun" if kind == "rerun" else None,
    )
