"""What a worker does with a job: run the investigation graph."""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from investigator.auth import Principal, directory_owner
from investigator.auth.models import LOCAL_ID
from investigator.directory import DirectoryStore
from investigator.investigations.events import EventStore
from investigator.investigations.runner import run_investigation, thread_id_for
from investigator.investigations.store import InvestigationStore
from investigator.jobs.models import Job
from investigator.tools import AccessContext


async def continue_from_checkpoint(graph: Any, thread_id: str) -> bool:
    """True when the thread was cut off mid-run, so the graph can carry on from where it
    stopped. A thread waiting at a human checkpoint, or never started, is not that."""
    snapshot = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    waiting = any(task.interrupts for task in snapshot.tasks)
    return bool(snapshot.next) and not waiting


class RunHandler:
    """Turns a queued job into a graph run. One handler serves every worker in a process."""

    def __init__(
        self,
        graph: Any,
        store: InvestigationStore,
        access: AccessContext,
        events: EventStore | None,
        directory: DirectoryStore | None,
    ) -> None:
        self._graph = graph
        self._store = store
        self._access = access
        self._events = events
        self._directory = directory

    async def __call__(self, job: Job) -> None:
        payload = job.payload
        thread = thread_id_for(job.investigation_id, int(payload.get("run_no", 1)))
        start: dict[str, Any] | Command[Any] | None
        if job.kind == "resume":
            start = Command(resume=payload["resume"])
        else:
            start = {"question": payload["question"], "context": payload["context"]}
        if job.attempts > 1 and await continue_from_checkpoint(self._graph, thread):
            # An earlier worker died partway: carry on instead of starting over.
            start = None
        who = Principal(
            user_id=str(payload.get("user_id") or LOCAL_ID),
            kind="demo" if payload.get("demo") else "user",
        )
        await run_investigation(
            self._graph,
            self._store,
            job.investigation_id,
            start,
            self._access.model_copy(
                update={"user_id": who.user_id, "demo": who.is_demo}
            ),
            events=self._events,
            directory=await self._directory.load(directory_owner(who))
            if self._directory
            else None,
            thread_id=thread,
            actor=payload.get("actor"),
            ip=payload.get("ip"),
            verified=bool(payload.get("verified")),
            demo=who.is_demo,
            mode="rerun" if job.kind == "rerun" else None,
        )
