"""The run queue: leases, retries after a worker dies, and workers that keep going."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from langgraph.types import Command

from investigator.agents.investigation.schemas import CaseContext, ReviewResume
from investigator.investigations import run_investigation
from investigator.investigations.events import MemoryEventStore
from investigator.investigations.runner import thread_id_for
from investigator.jobs import Job, JobWorker, MemoryJobQueue
from investigator.jobs.handler import RunHandler, continue_from_checkpoint
from tests.conftest import MemoryStore
from tests.fakes import ScriptedLlm, access
from tests.scenario import make_graph, structured


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, 9, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


# ---- the queue ------------------------------------------------------------------------


async def test_jobs_come_out_in_order_and_one_worker_gets_each() -> None:
    q = MemoryJobQueue()
    a, b = uuid4(), uuid4()
    first = await q.enqueue("start", a, {"n": 1})
    await q.enqueue("start", b, {"n": 2})
    one = await q.claim("w1", 60)
    two = await q.claim("w2", 60)
    assert one is not None and one.id == first and one.attempts == 1
    assert two is not None and two.investigation_id == b
    assert await q.claim("w3", 60) is None  # both are leased
    assert await q.has_active(a)


async def test_a_job_whose_worker_stopped_is_picked_up_again_with_one_more_attempt() -> (
    None
):
    clock = Clock()
    q = MemoryJobQueue(clock)
    inv = uuid4()
    await q.enqueue("start", inv, {})
    first = await q.claim("w1", 60)
    assert first is not None and first.attempts == 1
    assert await q.claim("w2", 60) is None  # still leased
    clock.advance(61)  # w1 died and stopped renewing
    again = await q.claim("w2", 60)
    assert again is not None and again.id == first.id and again.attempts == 2
    assert not await q.heartbeat(first.id, "w1", 60)  # the old holder no longer owns it
    assert await q.heartbeat(again.id, "w2", 60)


async def test_a_job_that_keeps_killing_workers_is_given_up_on() -> None:
    clock = Clock()
    q = MemoryJobQueue(clock)
    inv = uuid4()
    job_id = await q.enqueue("start", inv, {})
    for n in range(3):
        job = await q.claim(f"w{n}", 10)
        assert job is not None and job.attempts == n + 1
        clock.advance(11)
    assert await q.claim("w9", 10) is None
    assert q.rows[job_id]["status"] == "failed" and "Gave up" in q.rows[job_id]["error"]
    assert not await q.has_active(inv)


async def test_heartbeat_extends_the_lease() -> None:
    clock = Clock()
    q = MemoryJobQueue(clock)
    await q.enqueue("start", uuid4(), {})
    job = await q.claim("w1", 60)
    assert job is not None
    clock.advance(50)
    assert await q.heartbeat(job.id, "w1", 60)
    clock.advance(50)  # 100s in, but renewed at 50s
    assert await q.claim("w2", 60) is None


# ---- workers --------------------------------------------------------------------------


async def test_a_worker_runs_a_job_then_marks_it_done() -> None:
    q = MemoryJobQueue()
    job_id = await q.enqueue("start", uuid4(), {"x": 1})
    seen: list[Job] = []

    async def handle(job: Job) -> None:
        seen.append(job)

    worker = JobWorker(q, handle, worker_id="w")
    assert await worker.run_once() is True and await worker.run_once() is False
    assert seen[0].payload == {"x": 1} and q.rows[job_id]["status"] == "done"


async def test_a_job_that_raises_is_failed_and_the_worker_carries_on() -> None:
    q = MemoryJobQueue()
    bad = await q.enqueue("start", uuid4(), {})
    good = await q.enqueue("start", uuid4(), {})

    async def handle(job: Job) -> None:
        if job.id == bad:
            raise RuntimeError("boom")

    worker = JobWorker(q, handle, worker_id="w")
    await worker.run_once()
    await worker.run_once()
    assert (
        q.rows[bad]["status"] == "failed"
        and "RuntimeError: boom" in q.rows[bad]["error"]
    )
    assert q.rows[good]["status"] == "done"


async def test_a_long_job_keeps_its_lease_while_it_runs() -> None:
    q = MemoryJobQueue()
    await q.enqueue("start", uuid4(), {})
    beats = {"n": 0}
    original = q.heartbeat

    async def counting(job_id: Any, worker_id: str, lease_s: float) -> bool:
        beats["n"] += 1
        return await original(job_id, worker_id, lease_s)

    q.heartbeat = counting  # type: ignore[method-assign]

    async def slow(job: Job) -> None:
        await asyncio.sleep(0.25)

    await JobWorker(q, slow, worker_id="w", lease_s=0.15).run_once()
    assert beats["n"] >= 2


async def test_a_worker_stopped_mid_job_leaves_it_for_another_worker() -> None:
    clock = Clock()
    q = MemoryJobQueue(clock)
    job_id = await q.enqueue("start", uuid4(), {})
    started = asyncio.Event()

    async def hang(job: Job) -> None:
        started.set()
        await asyncio.sleep(60)

    task = asyncio.create_task(
        JobWorker(q, hang, worker_id="w1", lease_s=30).run_once()
    )
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert q.rows[job_id]["status"] == "running"  # neither done nor failed
    clock.advance(31)
    assert (await q.claim("w2", 30)) is not None


# ---- running investigations from jobs -------------------------------------------------


def handler_for(graph: Any, store: MemoryStore, events: MemoryEventStore) -> RunHandler:
    return RunHandler(graph, store, access("email", "chat"), events, None)


async def test_a_start_job_runs_the_graph_and_a_resume_job_continues_it() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    inv = await store.create("Why late?", CaseContext())
    handle = handler_for(graph, store, events)

    await handle(
        Job(
            id=uuid4(),
            kind="start",
            investigation_id=inv.id,
            payload={"question": "Why late?", "context": {}, "run_no": 1},
        )
    )
    got = await store.get(inv.id)
    assert got is not None and got.status == "needs_review" and got.awaiting == "review"

    resume = {"resume": ReviewResume(decision="approved").model_dump()}
    await handle(
        Job(
            id=uuid4(),
            kind="resume",
            investigation_id=inv.id,
            payload={**resume, "run_no": 1},
        )
    )
    got = await store.get(inv.id)
    assert got is not None and got.awaiting == "draft_approval"


async def test_a_rerun_is_its_own_thread_so_the_first_runs_state_is_untouched() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    inv = await store.create("Why late?", CaseContext())
    handle = handler_for(graph, store, events)
    payload = {"question": "Why late?", "context": {}}
    await handle(
        Job(
            id=uuid4(),
            kind="start",
            investigation_id=inv.id,
            payload={**payload, "run_no": 1},
        )
    )
    await handle(
        Job(
            id=uuid4(),
            kind="rerun",
            investigation_id=inv.id,
            payload={**payload, "run_no": 2},
        )
    )

    first = await graph.aget_state(
        {"configurable": {"thread_id": thread_id_for(inv.id, 1)}}
    )
    second = await graph.aget_state(
        {"configurable": {"thread_id": thread_id_for(inv.id, 2)}}
    )
    assert first.values and second.values
    modes = [
        e.data["mode"] for e in await events.after(inv.id, 0, 1000) if e.kind == "run"
    ]
    assert modes == ["start", "rerun"]
    assert thread_id_for(inv.id, 1) == str(inv.id) and thread_id_for(
        inv.id, 3
    ).endswith(":r3")


class _Snapshot:
    def __init__(self, nxt: tuple[str, ...], waiting: bool) -> None:
        self.next = nxt
        self.tasks = [type("T", (), {"interrupts": [object()] if waiting else []})()]


class _Graph:
    def __init__(self, snapshot: _Snapshot) -> None:
        self.snapshot = snapshot
        self.started_with: list[Any] = []

    async def aget_state(self, config: Any) -> _Snapshot:
        return self.snapshot

    async def astream(self, start: Any, **_: Any) -> Any:
        self.started_with.append(start)
        return
        yield


async def test_a_retried_job_carries_on_from_the_checkpoint_only_if_the_run_was_cut_off() -> (
    None
):
    store = MemoryStore()
    inv = await store.create("q", CaseContext())
    payload = {"question": "q", "context": {}, "run_no": 1}

    cut_off = _Graph(_Snapshot(("analyze_evidence",), waiting=False))
    await handler_for(cut_off, store, MemoryEventStore())(
        Job(
            id=uuid4(),
            kind="start",
            investigation_id=inv.id,
            payload=payload,
            attempts=2,
        )
    )
    assert cut_off.started_with == [
        None
    ]  # no new start: the graph resumes where it stopped

    first_try = _Graph(_Snapshot(("analyze_evidence",), waiting=False))
    await handler_for(first_try, store, MemoryEventStore())(
        Job(
            id=uuid4(),
            kind="start",
            investigation_id=inv.id,
            payload=payload,
            attempts=1,
        )
    )
    assert first_try.started_with == [{"question": "q", "context": {}}]

    at_review = _Graph(_Snapshot(("human_review",), waiting=True))
    await handler_for(at_review, store, MemoryEventStore())(
        Job(
            id=uuid4(),
            kind="resume",
            investigation_id=inv.id,
            payload={"resume": {"decision": "approved"}, "run_no": 1},
            attempts=2,
        )
    )
    assert isinstance(
        at_review.started_with[0], Command
    )  # still waiting: the answer is sent
    assert (
        await continue_from_checkpoint(_Graph(_Snapshot((), waiting=False)), "t")
        is False
    )


async def test_the_name_a_person_gave_is_recorded_as_who_resolved_it() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    inv = await store.create("Why late?", CaseContext())
    acc = access("email", "chat")
    await run_investigation(
        graph,
        store,
        inv.id,
        {"question": "Why late?"},
        acc,
        events=events,
        actor="Sam Kim",
    )
    await run_investigation(
        graph,
        store,
        inv.id,
        Command(resume=ReviewResume(decision="approved").model_dump()),
        acc,
        events=events,
        actor="Sam Kim",
    )
    from investigator.agents.investigation.schemas import DraftResume

    await run_investigation(
        graph,
        store,
        inv.id,
        Command(resume=DraftResume(approved=True).model_dump()),
        acc,
        events=events,
        actor="Sam Kim",
    )
    got = await store.get(inv.id)
    assert got is not None and got.status == "resolved" and got.resolved_by == "Sam Kim"
