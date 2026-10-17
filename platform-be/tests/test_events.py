"""Progress events: what a run reports, and the SSE stream that replays them."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from langgraph.types import Command

from investigator.agents.investigation.schemas import ReviewResume
from investigator.api.app import AppState, create_app
from investigator.investigations import run_investigation
from investigator.investigations.events import MemoryEventStore
from investigator.llm import LlmError
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import ScriptedLlm, access
from tests.scenario import make_graph, structured

CONTEXT: Any = None


async def start(
    graph: Any,
    store: MemoryStore,
    events: MemoryEventStore,
    question: str = "Why late?",
) -> UUID:
    from investigator.agents.investigation.schemas import CaseContext

    record = await store.create(question, CaseContext())
    await run_investigation(
        graph,
        store,
        record.id,
        {"question": question},
        access("email", "chat"),
        events=events,
    )
    return record.id


async def all_events(events: MemoryEventStore, id: UUID) -> list[Any]:
    return await events.after(id, 0, limit=10_000)


async def test_a_run_reports_its_steps_searches_and_where_it_stopped() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    id = await start(graph, store, events)
    got = await all_events(events, id)

    kinds = [e.kind for e in got]
    assert kinds[0] == "run" and got[0].data == {"mode": "start"}
    assert kinds[1] == "status" and got[1].data == {"status": "investigating"}
    assert kinds[-2:] == ["status", "done"]
    assert got[-1].data == {"status": "needs_review", "awaiting": "review"}

    steps = [e.data["node"] for e in got if e.kind == "step"]
    for node in (
        "intake",
        "plan_investigation",
        "retrieve_evidence",
        "normalize_dedupe",
        "analyze_evidence",
        "synthesize_findings",
        "validate_claims",
        "recommend_actions",
    ):
        assert node in steps
    assert steps.index("plan_investigation") < steps.index("retrieve_evidence")
    assert steps.index("retrieve_evidence") < steps.index("synthesize_findings")

    plan = next(e for e in got if e.data.get("node") == "plan_investigation")
    assert plan.data["label"] == "Planning the search"
    nested = next(e for e in got if e.data.get("node") == "seed_search")
    assert (
        nested.data["parent"] == "retrieve_evidence"
    )  # work inside a subgraph says so
    assert (
        next(e for e in got if e.data.get("node") == "normalize_dedupe").data["records"]
        == 2
    )

    first_tool = next(i for i, e in enumerate(got) if e.kind == "tool")
    seed_done = next(
        i for i, e in enumerate(got) if e.data.get("node") == "seed_search"
    )
    assert (
        first_tool < seed_done
    )  # a search is reported when it finishes, not at the end

    tools = [e.data for e in got if e.kind == "tool"]
    assert {t["source"] for t in tools} == {"email", "chat"}
    searches = [t for t in tools if t["tool"] == "search_records"]
    assert searches and all(t["records"] == 1 for t in searches)
    assert any(
        t["tool"] == "get_thread" for t in tools
    )  # conversations are read by rule


async def test_events_never_carry_record_content() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    id = await start(make_graph(ScriptedLlm(structured=structured())), store, events)
    text = json.dumps([e.data for e in await all_events(events, id)])
    assert "Please update the form" not in text and "We expect it ready" not in text


async def test_partial_results_are_saved_while_the_run_is_going() -> None:
    saves: list[tuple[str, int]] = []

    class Spy(MemoryStore):
        async def save_result(
            self, investigation_id: Any, state: Any, **kw: Any
        ) -> None:
            saves.append((kw["status"], len(state.evidence)))
            await super().save_result(investigation_id, state, **kw)

    await start(
        make_graph(ScriptedLlm(structured=structured())), Spy(), MemoryEventStore()
    )
    running = [n for status, n in saves if status == "investigating"]
    assert running and max(running) == 2  # evidence was visible before the run ended
    assert saves[-1][0] == "needs_review"


async def test_a_resume_is_its_own_run_with_the_same_event_log() -> None:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    id = await start(graph, store, events)
    await run_investigation(
        graph,
        store,
        id,
        Command(resume=ReviewResume(decision="approved").model_dump()),
        access("email", "chat"),
        events=events,
    )
    got = await all_events(events, id)
    runs = [e.data["mode"] for e in got if e.kind == "run"]
    assert runs == ["start", "resume"]
    assert got[-1].kind == "done" and got[-1].data["awaiting"] == "draft_approval"


async def test_a_crash_is_reported_and_closed_with_done() -> None:
    s = structured()
    from investigator.agents.investigation.schemas import TimelineDraft

    s[TimelineDraft] = LlmError("boom")
    store, events = MemoryStore(), MemoryEventStore()
    id = await start(make_graph(ScriptedLlm(structured=s)), store, events)
    got = await all_events(events, id)
    # an LLM error fails the run inside the graph: it is reported as a normal finish
    assert got[-1].kind == "done" and got[-1].data["status"] == "failed"


async def test_an_exception_outside_the_graph_logs_an_error_event() -> None:
    class Exploding:
        async def astream(self, *a: Any, **k: Any) -> Any:
            raise RuntimeError("boom")
            yield

    store, events = MemoryStore(), MemoryEventStore()
    id = await start(Exploding(), store, events)
    got = await all_events(events, id)
    assert [e.kind for e in got][-2:] == ["error", "done"]
    assert "RuntimeError: boom" in got[-2].data["message"]


# ---- the SSE stream -------------------------------------------------------------------


def parse(body: str) -> list[dict[str, Any]]:
    out = []
    for block in body.strip().split("\n\n"):
        if block.startswith(":"):
            continue
        item: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(": ")
            item[key] = value
        out.append(item)
    return out


async def seeded(running: bool = False) -> tuple[TestClient, UUID, MemoryEventStore]:
    store, events = MemoryStore(), MemoryEventStore()
    graph = make_graph(ScriptedLlm(structured=structured()))
    id = await start(graph, store, events)
    if running:
        await store.set_status(id, "investigating")
    client = TestClient(
        create_app(
            AppState(
                store=store,
                graph=None,
                access=AccessContext(user_id="local"),
                events=events,
            )
        )
    )
    return client, id, events


async def test_the_stream_replays_history_then_ends_when_the_run_is_at_rest() -> None:
    client, id, events = await seeded()
    resp = client.get(f"/investigations/{id}/events")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"].startswith("no-cache")
    items = parse(resp.text)
    assert items[0]["event"] == "run"
    assert (
        items[-1]["event"] == "end"
        and json.loads(items[-1]["data"])["status"] == "needs_review"
    )
    stored = await all_events(events, id)
    assert [int(i["id"]) for i in items[:-1]] == [e.id for e in stored]
    assert "at" in json.loads(items[0]["data"])


async def test_after_and_last_event_id_skip_what_the_client_has() -> None:
    client, id, events = await seeded()
    total = len(await all_events(events, id))
    by_param = parse(client.get(f"/investigations/{id}/events?after={total - 2}").text)
    assert [i["event"] for i in by_param] == ["status", "done", "end"]
    by_header = parse(
        client.get(
            f"/investigations/{id}/events", headers={"Last-Event-ID": str(total)}
        ).text
    )
    assert [i["event"] for i in by_header] == [
        "end"
    ]  # nothing new, at rest: just close


async def test_unknown_investigation_and_missing_event_store() -> None:
    client, _, _ = await seeded()
    assert (
        client.get(
            "/investigations/00000000-0000-0000-0000-000000000000/events"
        ).status_code
        == 404
    )
    bare = TestClient(
        create_app(
            AppState(
                store=MemoryStore(), graph=None, access=AccessContext(user_id="local")
            )
        )
    )
    assert (
        bare.get(
            "/investigations/00000000-0000-0000-0000-000000000000/events"
        ).status_code
        == 503
    )
