from __future__ import annotations

from typing import Any
from uuid import UUID

from langgraph.types import Command

from investigator.agents.investigation import InvestigationState, recursion_limit
from investigator.directory import Directory
from investigator.guardrails import bind
from investigator.guardrails.pii.names import directory_names
from investigator.investigations.events import EventStore
from investigator.investigations.models import Awaiting, InvestigationRunStatus
from investigator.investigations.progress import ProgressReporter
from investigator.investigations.store import InvestigationStore
from investigator.tools import AccessContext, HarnessLimits

# What each human checkpoint means for the record's status.
PAUSE_STATUS: dict[str, tuple[Awaiting, InvestigationRunStatus]] = {
    "clarification": ("clarification", "blocked"),
    "review": ("review", "needs_review"),
    "draft_approval": ("draft_approval", "needs_review"),
}


# After these top-level steps the partial result is saved, so a page that reloads
# mid-run shows what exists so far instead of nothing.
MILESTONES = {
    "retrieve_evidence",
    "normalize_dedupe",
    "assess_evidence",
    "analyze_evidence",
    "synthesize_findings",
    "validate_claims",
    "recommend_actions",
}


def thread_id_for(investigation_id: UUID, run_no: int) -> str:
    """The checkpoint thread of one run. The first run keeps the investigation's own id."""
    return str(investigation_id) if run_no <= 1 else f"{investigation_id}:r{run_no}"


async def run_investigation(
    graph: Any,
    store: InvestigationStore,
    investigation_id: UUID,
    start: dict[str, Any] | Command[Any] | None,
    access: AccessContext,
    limits: HarnessLimits | None = None,
    events: EventStore | None = None,
    directory: Directory | None = None,
    *,
    thread_id: str | None = None,
    actor: str | None = None,
    mode: str | None = None,
    ip: str | None = None,
    verified: bool = False,
    demo: bool = False,
) -> None:
    """Run (or resume) the graph, with the model calls under it attributed to this run."""
    with bind(
        run_id=str(investigation_id),
        thread_id=thread_id,
        actor=actor,
        ip=ip,
        verified=verified,
        demo=demo,
        purpose="investigation",
        names=directory_names(directory),
    ):
        await _run(
            graph,
            store,
            investigation_id,
            start,
            access,
            limits,
            events,
            directory,
            thread_id=thread_id,
            actor=actor,
            mode=mode,
        )


async def _run(
    graph: Any,
    store: InvestigationStore,
    investigation_id: UUID,
    start: dict[str, Any] | Command[Any] | None,
    access: AccessContext,
    limits: HarnessLimits | None = None,
    events: EventStore | None = None,
    directory: Directory | None = None,
    *,
    thread_id: str | None = None,
    actor: str | None = None,
    mode: str | None = None,
) -> None:
    """Run (or resume) the graph for one investigation and record where it stopped.

    The investigation id is the checkpoint thread id, so a run's graph state and
    its record share one key. Access rules come from the backend, never from the
    request body or the model. The graph can end, or pause at a human checkpoint;
    either way the latest state is saved and the pause is recorded.
    """
    await store.set_status(investigation_id, "investigating")
    config = {
        "configurable": {
            "thread_id": thread_id or str(investigation_id),
            "access": access,
            "directory": directory,
            "actor": actor,
        },
        "recursion_limit": recursion_limit(limits or HarnessLimits()),
    }
    report = ProgressReporter(events, investigation_id) if events else None
    if events:
        await events.append(
            investigation_id,
            "run",
            {
                "mode": mode or ("start" if isinstance(start, dict) else "resume"),
            },
        )
        await events.append(investigation_id, "status", {"status": "investigating"})
    try:
        async for namespace, kind, chunk in graph.astream(
            start, config=config, stream_mode=["updates", "custom"], subgraphs=True
        ):
            if kind == "custom":
                if report:
                    await report.custom(chunk)
                continue
            for node, delta in chunk.items():
                if report:
                    await report.update(tuple(namespace), node, delta)
                if not namespace and node in MILESTONES:
                    await _save_partial(graph, store, investigation_id, config)
        snapshot = await graph.aget_state(config)
        state = InvestigationState(**snapshot.values)
        interrupts = [i for task in snapshot.tasks for i in task.interrupts]
        if interrupts:
            payload = dict(interrupts[0].value)
            awaiting, status = PAUSE_STATUS[payload["kind"]]
            await store.save_result(
                investigation_id,
                state,
                status=status,
                awaiting=awaiting,
                pending=payload,
            )
            final: dict[str, Any] = {"status": status, "awaiting": awaiting}
        else:
            await store.save_result(investigation_id, state, status=state.status)
            final = {"status": state.status, "awaiting": None}
        if events:
            await events.append(investigation_id, "status", final)
            await events.append(investigation_id, "done", final)
    except Exception as exc:  # noqa: BLE001  any failure must land on the record
        message = f"{type(exc).__name__}: {exc}"
        await store.fail(investigation_id, message)
        if events:
            await events.append(investigation_id, "error", {"message": message})
            await events.append(
                investigation_id, "done", {"status": "failed", "awaiting": None}
            )


async def _save_partial(
    graph: Any,
    store: InvestigationStore,
    investigation_id: UUID,
    config: dict[str, Any],
) -> None:
    """Best effort: a failed progress save must never end a healthy run."""
    try:
        snapshot = await graph.aget_state(config)
        await store.save_result(
            investigation_id,
            InvestigationState(**snapshot.values),
            status="investigating",
        )
    except Exception:  # noqa: BLE001, S110
        pass
