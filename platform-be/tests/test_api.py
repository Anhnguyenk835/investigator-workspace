from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
from langgraph.types import Command

from investigator.agents.investigation import InvestigationState
from investigator.api.app import AppState, create_app
from investigator.tools import AccessContext
from tests.conftest import MemoryStore


class Snapshot:
    """The slice of a LangGraph state snapshot the runner reads."""

    def __init__(
        self, state: InvestigationState, pending: dict[str, Any] | None
    ) -> None:
        self.values = state.model_dump()
        self.tasks = (
            [type("T", (), {"interrupts": [type("I", (), {"value": pending})()]})()]
            if pending
            else []
        )


class PausingGraph:
    """Pauses for review on the first call, finishes on resume."""

    def __init__(self) -> None:
        self.starts: list[Any] = []

    async def astream(
        self, start: Any, config: dict[str, Any], **_: Any
    ) -> AsyncIterator[tuple[tuple[str, ...], str, dict[str, Any]]]:
        assert (
            config["configurable"]["thread_id"]
            and config["configurable"]["access"].user_id == "local"
        )
        self.starts.append(start)
        return
        yield  # an empty async generator: the run reports nothing

    async def aget_state(self, config: dict[str, Any]) -> Snapshot:
        resumed = any(isinstance(s, Command) for s in self.starts)
        state = InvestigationState(
            **self.starts[0], status="resolved" if resumed else "investigating"
        )
        return Snapshot(state, None if resumed else {"kind": "review", "findings": 1})


class BoomGraph:
    async def astream(
        self, start: Any, config: dict[str, Any], **_: Any
    ) -> AsyncIterator[tuple[tuple[str, ...], str, dict[str, Any]]]:
        raise RuntimeError("boom")
        yield


def client(graph: Any) -> TestClient:
    return TestClient(
        create_app(
            AppState(
                store=MemoryStore(),
                graph=graph,
                access=AccessContext(
                    user_id="local", permitted_sources=frozenset({"email", "chat"})
                ),
            )
        )
    )


def test_create_passes_case_context_and_records_the_pause() -> None:
    graph = PausingGraph()
    c = client(graph)
    created = c.post(
        "/investigations",
        json={
            "question": " why late? ",
            "project_id": "p1",
            "date_from": "2026-10-01",
            "sources": ["email"],
        },
    )
    assert created.status_code == 202 and created.json()["status"] == "queued"
    assert (
        graph.starts[0]["context"]["project_id"] == "p1"
        and graph.starts[0]["question"] == "why late?"
    )
    got = c.get(f"/investigations/{created.json()['id']}").json()
    assert got["status"] == "needs_review" and got["awaiting"] == "review"
    assert got["pending"]["kind"] == "review" and got["context"]["sources"] == ["email"]


def test_create_rejects_input_that_cannot_describe_a_case() -> None:
    c = client(PausingGraph())

    def post(**body: object) -> int:
        return c.post("/investigations", json={"question": "q", **body}).status_code

    assert post(date_from="2026-10-10", date_to="2026-10-01") == 422  # backwards window
    assert post(date_from="2026-10-01", date_to="2026-10-01") == 202  # one day is fine
    assert post(sources=["email", "myspace"]) == 422
    assert post(sources=["email", "chat"]) == 202
    assert post(ticket_ids=["not a ticket"]) == 422
    assert post(ticket_ids=["IMPL-482", "hpf_2-9"]) == 202
    unknown = c.post("/investigations", json={"question": "q", "sources": ["myspace"]})
    assert "myspace" in unknown.json()["detail"] and "email" in unknown.json()["detail"]


def test_resume_validates_by_checkpoint_and_continues() -> None:
    graph = PausingGraph()
    c = client(graph)
    inv_id = c.post("/investigations", json={"question": "q"}).json()["id"]

    bad = c.post(
        f"/investigations/{inv_id}/resume", json={"value": {"decision": "maybe"}}
    )
    assert bad.status_code == 422

    ok = c.post(
        f"/investigations/{inv_id}/resume", json={"value": {"decision": "approved"}}
    )
    assert ok.status_code == 202 and ok.json()["status"] == "investigating"
    assert isinstance(graph.starts[-1], Command) and graph.starts[-1].resume == {
        "decision": "approved",
        "note": "",
    }
    final = c.get(f"/investigations/{inv_id}").json()
    assert final["status"] == "resolved" and final["awaiting"] is None

    again = c.post(
        f"/investigations/{inv_id}/resume", json={"value": {"decision": "approved"}}
    )
    assert again.status_code == 409  # nothing is waiting any more


def test_graph_crash_is_recorded_as_failed() -> None:
    c = client(BoomGraph())
    created = c.post("/investigations", json={"question": "q"}).json()
    got = c.get(f"/investigations/{created['id']}").json()
    assert got["status"] == "failed" and "boom" in got["error"]


def test_unconfigured_llm_is_503() -> None:
    c = client(None)
    assert c.get("/health").json()["llm_configured"] is False
    assert c.post("/investigations", json={"question": "q"}).status_code == 503
    # What is not there is a 404 whether or not a model is configured.
    assert (
        c.post(
            "/investigations/00000000-0000-0000-0000-000000000000/resume",
            json={"value": {}},
        ).status_code
        == 404
    )


def test_validation_and_404() -> None:
    c = client(PausingGraph())
    assert c.post("/investigations", json={"question": ""}).status_code == 422
    assert (
        c.get("/investigations/00000000-0000-0000-0000-000000000000").status_code == 404
    )
    assert (
        c.post(
            "/investigations/00000000-0000-0000-0000-000000000000/resume",
            json={"value": {}},
        ).status_code
        == 404
    )
