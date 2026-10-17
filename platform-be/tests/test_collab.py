"""Working together: queued runs through the API, owner, re-run, notes and reviews, export."""

from __future__ import annotations

from uuid import UUID

import httpx

from investigator.api.app import AppState, create_app
from investigator.directory import Customer, Directory, MemoryDirectoryStore, Project
from investigator.investigations.annotations import MemoryAnnotationStore
from investigator.investigations.events import MemoryEventStore
from investigator.jobs import JobWorker, MemoryJobQueue
from investigator.jobs.handler import RunHandler
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import ScriptedLlm
from tests.scenario import make_graph, structured

ACCESS = AccessContext(user_id="local", permitted_sources=frozenset({"email", "chat"}))
H = {"x-actor": "Sam Kim"}


class Rig:
    def __init__(self, directory: Directory | None = None) -> None:
        self.store = MemoryStore()
        self.queue = MemoryJobQueue()
        self.events = MemoryEventStore()
        self.annotations = MemoryAnnotationStore()
        self.graph = make_graph(ScriptedLlm(structured=structured()))
        self.directory = MemoryDirectoryStore(directory or Directory())
        state = AppState(
            store=self.store,
            graph=self.graph,
            access=ACCESS,
            events=self.events,
            directory=self.directory,
            queue=self.queue,
            annotations=self.annotations,
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(state)), base_url="http://t"
        )
        handler = RunHandler(
            self.graph, self.store, ACCESS, self.events, self.directory
        )
        self.worker = JobWorker(self.queue, handler, worker_id="w")

    async def start(self) -> str:
        created = await self.client.post(
            "/investigations", json={"question": "Why was the form late?"}, headers=H
        )
        assert created.status_code == 202
        return created.json()["id"]  # type: ignore[no-any-return]


# ---- the queue is how runs start ------------------------------------------------------


async def test_creating_queues_a_job_and_a_worker_does_the_run() -> None:
    rig = Rig()
    inv_id = await rig.start()
    assert (await rig.client.get(f"/investigations/{inv_id}")).json()[
        "status"
    ] == "queued"
    (job,) = rig.queue.rows.values()
    assert (
        job["kind"] == "start"
        and job["payload"]["question"] == "Why was the form late?"
    )
    assert job["payload"]["actor"] == "Sam Kim" and job["payload"]["run_no"] == 1

    assert await rig.worker.run_once()
    got = (await rig.client.get(f"/investigations/{inv_id}")).json()
    assert got["status"] == "needs_review" and got["awaiting"] == "review"

    resumed = await rig.client.post(
        f"/investigations/{inv_id}/resume",
        json={"value": {"decision": "approved"}},
        headers=H,
    )
    assert resumed.status_code == 202 and resumed.json()["status"] == "investigating"
    assert await rig.worker.run_once()
    got = (await rig.client.get(f"/investigations/{inv_id}")).json()
    assert got["awaiting"] == "draft_approval"


async def test_the_name_header_is_cleaned_and_optional() -> None:
    rig = Rig()
    await rig.client.post(
        "/investigations", json={"question": "q"}, headers={"x-actor": "  Sam   Kim  "}
    )
    await rig.client.post("/investigations", json={"question": "q"})
    actors = [r["payload"]["actor"] for r in rig.queue.rows.values()]
    assert actors == ["Sam Kim", None]


# ---- owner ----------------------------------------------------------------------------


async def test_an_investigation_can_be_assigned_and_unassigned() -> None:
    rig = Rig()
    inv_id = await rig.start()
    assigned = await rig.client.patch(
        f"/investigations/{inv_id}", json={"owner": "  Priya   Raman "}
    )
    assert assigned.status_code == 200 and assigned.json()["owner"] == "Priya Raman"
    cleared = await rig.client.patch(f"/investigations/{inv_id}", json={"owner": None})
    assert cleared.json()["owner"] is None
    missing = await rig.client.patch(
        "/investigations/00000000-0000-0000-0000-000000000001", json={"owner": "x"}
    )
    assert missing.status_code == 404


# ---- re-run ---------------------------------------------------------------------------


async def test_rerun_starts_a_new_run_only_when_nothing_is_running() -> None:
    rig = Rig()
    inv_id = await rig.start()
    assert (
        await rig.client.post(f"/investigations/{inv_id}/rerun")
    ).status_code == 409  # still queued
    await rig.worker.run_once()

    again = await rig.client.post(f"/investigations/{inv_id}/rerun", headers=H)
    assert (
        again.status_code == 202
        and again.json()["run_no"] == 2
        and again.json()["status"] == "queued"
    )
    job = list(rig.queue.rows.values())[-1]
    assert job["kind"] == "rerun" and job["payload"]["run_no"] == 2
    assert job["payload"]["question"] == "Why was the form late?"
    await rig.worker.run_once()
    got = (await rig.client.get(f"/investigations/{inv_id}")).json()
    assert got["status"] == "needs_review" and got["run_no"] == 2


# ---- notes and reviews ----------------------------------------------------------------


async def finished(rig: Rig) -> tuple[str, str]:
    inv_id = await rig.start()
    await rig.worker.run_once()
    finding = (await rig.client.get(f"/investigations/{inv_id}")).json()["findings"][0][
        "id"
    ]
    return inv_id, finding


async def test_notes_reviews_and_disputes_attach_to_a_claim_with_their_author() -> None:
    rig = Rig()
    inv_id, finding = await finished(rig)
    base = f"/investigations/{inv_id}/annotations"
    note = await rig.client.post(
        base,
        json={
            "target_id": finding,
            "kind": "note",
            "text": "  Check the second email  ",
        },
        headers=H,
    )
    assert (
        note.status_code == 201
        and note.json()["author"] == "Sam Kim"
        and note.json()["text"] == "Check the second email"
    )
    assert (
        await rig.client.post(
            base, json={"target_id": finding, "kind": "reviewed"}, headers=H
        )
    ).status_code == 201
    assert (
        await rig.client.post(
            base,
            json={"target_id": finding, "kind": "disputed", "text": "Date is wrong"},
            headers={"x-actor": "Priya"},
        )
    ).status_code == 201
    listing = (await rig.client.get(base)).json()
    assert [(a["kind"], a["author"]) for a in listing] == [
        ("note", "Sam Kim"),
        ("reviewed", "Sam Kim"),
        ("disputed", "Priya"),
    ]


async def test_annotations_are_checked_and_only_their_author_removes_them() -> None:
    rig = Rig()
    inv_id, finding = await finished(rig)
    base = f"/investigations/{inv_id}/annotations"
    assert (
        await rig.client.post(
            base, json={"target_id": "fd_nope", "kind": "note", "text": "x"}, headers=H
        )
    ).status_code == 422
    assert (
        await rig.client.post(
            base, json={"target_id": finding, "kind": "note", "text": "  "}, headers=H
        )
    ).status_code == 422
    assert (
        await rig.client.post(
            base, json={"target_id": finding, "kind": "flag"}, headers=H
        )
    ).status_code == 422
    made = (
        await rig.client.post(
            base, json={"target_id": finding, "kind": "note", "text": "mine"}, headers=H
        )
    ).json()
    assert (
        await rig.client.delete(f"{base}/{made['id']}", headers={"x-actor": "Priya"})
    ).status_code == 404
    assert (
        await rig.client.delete(f"{base}/{made['id']}", headers=H)
    ).status_code == 204
    assert (await rig.client.get(base)).json() == []


async def test_notes_survive_a_rerun_and_stay_with_the_claim_when_it_is_worded_the_same() -> (
    None
):
    rig = Rig()
    inv_id, finding = await finished(rig)
    await rig.client.post(
        f"/investigations/{inv_id}/annotations",
        json={"target_id": finding, "kind": "reviewed"},
        headers=H,
    )
    await rig.client.post(f"/investigations/{inv_id}/rerun")
    await rig.worker.run_once()
    now = {
        f["id"]
        for f in (await rig.client.get(f"/investigations/{inv_id}")).json()["findings"]
    }
    assert finding in now  # same claim, same id
    assert (
        len((await rig.client.get(f"/investigations/{inv_id}/annotations")).json()) == 1
    )


# ---- export ---------------------------------------------------------------------------

ACME = Customer(id="c1", name="Acme Fund")
PROJECT = Project(id="p1", customer_id="c1", name="Fund IV Close")


async def test_markdown_export_keeps_every_claim_tied_to_numbered_evidence() -> None:
    rig = Rig(Directory(customers=[ACME], projects=[PROJECT]))
    inv_id, finding = await finished(rig)
    await rig.client.post(
        f"/investigations/{inv_id}/annotations",
        json={"target_id": finding, "kind": "disputed", "text": "Wrong date"},
        headers=H,
    )
    await rig.client.patch(f"/investigations/{inv_id}", json={"owner": "Priya"})
    res = await rig.client.get(f"/investigations/{inv_id}/export?format=md")
    assert res.status_code == 200 and res.headers["content-type"].startswith(
        "text/markdown"
    )
    assert 'filename="investigation-' in res.headers["content-disposition"]
    md = res.text
    assert md.startswith("# Why was the form late?")
    assert "Generated by AI" in md and "not a conclusion" in md
    assert (
        "**Owner:** Priya" in md and "## Findings" in md and "## Source coverage" in md
    )
    assert (
        "Client asked for the form update [1]" in md
    )  # the claim and its evidence number
    assert "Disputed by Sam Kim" in md and "Wrong date" in md
    evidence = md.split("## Evidence")[1]
    assert "| 1 |" in evidence and "(e1)" in evidence
    assert "Unanchored idea" not in md  # nothing the validation rejected leaks in


async def test_html_export_escapes_content_and_json_export_is_the_record() -> None:
    rig = Rig()
    inv_id = await rig.start()
    await rig.worker.run_once()
    await rig.store.set_owner(UUID(inv_id), "<script>alert(1)</script>")
    html_res = await rig.client.get(f"/investigations/{inv_id}/export?format=html")
    assert html_res.headers["content-type"].startswith("text/html")
    assert (
        "<script>alert(1)</script>" not in html_res.text
        and "&lt;script&gt;" in html_res.text
    )
    assert (
        html_res.text.startswith("<!doctype html>") and "@media print" in html_res.text
    )

    data = (await rig.client.get(f"/investigations/{inv_id}/export?format=json")).json()
    assert data["investigation"]["id"] == inv_id and data["annotations"] == []
    assert (
        await rig.client.get(f"/investigations/{inv_id}/export?format=pdf")
    ).status_code == 422
    assert (
        await rig.client.get(
            "/investigations/00000000-0000-0000-0000-000000000001/export"
        )
    ).status_code == 404


async def test_a_run_with_no_findings_still_exports_honestly() -> None:
    rig = Rig()
    inv_id = await rig.start()  # not run yet: nothing found
    md = (await rig.client.get(f"/investigations/{inv_id}/export")).text
    assert (
        "No source was searched." in md
        and "No finding is supported" in md
        and "## Evidence" not in md
    )


def test_the_browser_may_use_every_method_the_web_app_needs() -> None:
    """CORS preflight for PUT, PATCH and DELETE must pass, or those buttons fail silently."""
    from fastapi.testclient import TestClient

    client = TestClient(
        create_app(AppState(store=MemoryStore(), graph=None, access=ACCESS))
    )
    for method in ("PUT", "PATCH", "DELETE"):
        res = client.options(
            "/directory/projects/x",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "x-actor,content-type",
            },
        )
        assert (
            res.status_code == 200
            and method in res.headers["access-control-allow-methods"]
        )
