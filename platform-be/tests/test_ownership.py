"""Whose data is whose. Every route that takes an id answers 404 to someone who does not own
it, and a demo visitor reads the shared samples but cannot change them."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from investigator.agents.chat import ChatDeps, build_chat_graph
from investigator.agents.investigation.schemas import CaseContext
from investigator.api.app import AppState, create_app
from investigator.auth import SAMPLE_OWNER, AuthService, GoogleOidc, MemoryAuthStore
from investigator.chat import ChatService, MemoryChatStore
from investigator.directory import Directory, MemoryDirectoryStore
from investigator.investigations.annotations import MemoryAnnotationStore
from investigator.investigations.events import MemoryEventStore
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import ScriptedLlm, text_turn

WEB = "http://localhost:5173"
ACCESS = AccessContext(user_id="local", permitted_sources=frozenset({"email"}))
SAMPLE = str(SAMPLE_OWNER)


class World:
    """One app, several people, each with their own browser (cookie jar)."""

    def __init__(self) -> None:
        self.store = MemoryStore()
        self.auth_store = MemoryAuthStore()
        self.auth = AuthService(
            self.auth_store,
            GoogleOidc(
                "c", "s", f"{WEB}/api/auth/google/callback", httpx.AsyncClient()
            ),
            web_url=WEB,
            origins=frozenset({WEB}),
        )
        llm = ScriptedLlm(turns=[text_turn("Answer [E:e1].")] * 20)
        self.chats = MemoryChatStore()
        graph = build_chat_graph(ChatDeps(llm=llm, connectors=[]))  # type: ignore[arg-type]
        self.directory = MemoryDirectoryStore(Directory())
        state = AppState(
            store=self.store,
            graph=None,
            access=ACCESS,
            events=MemoryEventStore(),
            annotations=MemoryAnnotationStore(),
            directory=self.directory,
            chat=ChatService(graph, self.chats, self.store, ACCESS, self.directory),
            auth=self.auth,
        )
        state.graph = object()  # something to run on; no worker is started
        self.app = create_app(state)

    async def person(self, sub: str) -> tuple[TestClient, str]:
        user = await self.auth_store.upsert_google(
            sub, f"{sub}@x.example", sub.title(), None
        )
        token, _ = await self.auth.start_session(user, "1.1.1.1", None)
        client = TestClient(self.app, headers={"Origin": WEB})
        client.cookies.set("inv_session", token)
        return client, str(user.id)

    async def demo(self) -> tuple[TestClient, str]:
        user = await self.auth.start_demo("2.2.2.2")
        token, _ = await self.auth.start_session(user, "2.2.2.2", None)
        client = TestClient(self.app, headers={"Origin": WEB})
        client.cookies.set("inv_session", token)
        return client, str(user.id)

    async def investigation(
        self, owner: str | None, status: str = "needs_review"
    ) -> UUID:
        inv = await self.store.create("What happened?", CaseContext(), owner)
        await self.store.set_status(inv.id, status)  # type: ignore[arg-type]
        return inv.id


@pytest.fixture
def world() -> World:
    return World()


# ---- the matrix: another person's investigation is not there -------------------------


ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/investigations/{i}", None),
    ("POST", "/investigations/{i}/resume", {"value": {}}),
    ("GET", "/investigations/{i}/events", None),
    ("POST", "/investigations/{i}/rerun", None),
    ("PATCH", "/investigations/{i}", {"owner": "Sam"}),
    ("GET", "/investigations/{i}/annotations", None),
    (
        "POST",
        "/investigations/{i}/annotations",
        {"target_id": "x", "kind": "note", "text": "hi"},
    ),
    ("GET", "/investigations/{i}/export?format=json", None),
    ("GET", "/investigations/{i}/chat", None),
    ("POST", "/investigations/{i}/chat", {"message": "hello"}),
    ("DELETE", "/investigations/{i}/chat", None),
    ("GET", "/investigations/{i}/conversations", None),
    ("POST", "/investigations/{i}/conversations", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
async def test_a_stranger_gets_a_404_on_every_route_for_someone_elses_investigation(
    world: World, method: str, path: str, body: dict[str, Any] | None
) -> None:
    _, ada_id = await world.person("ada")
    bob, _ = await world.person("bob")
    inv = await world.investigation(ada_id)
    r = bob.request(method, path.format(i=inv), json=body)
    assert r.status_code == 404, (method, path, r.status_code)
    missing = bob.request(method, path.format(i=uuid4()), json=body)
    assert missing.status_code == 404  # indistinguishable from one that does not exist


async def test_the_owner_reaches_the_same_routes(world: World) -> None:
    ada, ada_id = await world.person("ada")
    inv = await world.investigation(ada_id)
    assert ada.get(f"/investigations/{inv}").status_code == 200
    assert ada.get(f"/investigations/{inv}/export?format=json").status_code == 200
    assert ada.get(f"/investigations/{inv}/conversations").status_code == 200


async def test_the_list_shows_only_your_own(world: World) -> None:
    ada, ada_id = await world.person("ada")
    bob, bob_id = await world.person("bob")
    mine, theirs = await world.investigation(ada_id), await world.investigation(bob_id)
    legacy = await world.investigation(None)  # from before sign-in
    ids = {i["id"] for i in ada.get("/investigations").json()}
    assert ids == {str(mine)} and str(theirs) not in ids and str(legacy) not in ids
    assert ada.get(f"/investigations/{legacy}").status_code == 404


async def test_a_new_investigation_belongs_to_whoever_started_it(world: World) -> None:
    world.app.state.app.graph = (
        object()
    )  # something to run on; the queue is not started
    ada, ada_id = await world.person("ada")
    bob, _ = await world.person("bob")
    r = ada.post("/investigations", json={"question": "Why was it late?"})
    assert r.status_code == 202 and r.json()["owner_id"] == ada_id
    assert bob.get("/investigations").json() == []


# ---- conversations belong to a person --------------------------------------------------


async def test_two_people_never_see_each_others_conversations_on_a_shared_sample(
    world: World,
) -> None:
    sample = await world.investigation(SAMPLE)
    one, _ = await world.demo()
    two, _ = await world.demo()
    made = one.post(f"/investigations/{sample}/conversations").json()["id"]
    assert (
        one.post(
            f"/investigations/{sample}/conversations/{made}/chat",
            json={"message": "hi"},
        ).status_code
        == 200
    )
    assert [
        c["title"]
        for c in one.get(f"/investigations/{sample}/conversations").json()[
            "conversations"
        ]
    ] == ["hi"]
    assert two.get(f"/investigations/{sample}/conversations").json() == {
        "conversations": []
    }
    for method, suffix in (("GET", "/messages"), ("PATCH", ""), ("DELETE", "")):
        r = two.request(
            method,
            f"/investigations/{sample}/conversations/{made}{suffix}",
            json={"title": "x"},
        )
        assert r.status_code == 404, (method, suffix)
    assert (
        two.post(
            f"/investigations/{sample}/conversations/{made}/chat", json={"message": "x"}
        ).status_code
        == 404
    )


# ---- the demo -------------------------------------------------------------------------


async def test_a_demo_visitor_reads_the_samples_but_cannot_change_them(
    world: World,
) -> None:
    sample = await world.investigation(SAMPLE)
    demo, _ = await world.demo()
    assert [i["id"] for i in demo.get("/investigations").json()] == [str(sample)]
    got = demo.get(f"/investigations/{sample}")
    assert got.status_code == 200 and got.json()["sample"] is True
    assert demo.get(f"/investigations/{sample}/export?format=json").status_code == 200
    for method, path, body in (
        ("POST", f"/investigations/{sample}/rerun", None),
        ("PATCH", f"/investigations/{sample}", {"owner": "x"}),
        (
            "POST",
            f"/investigations/{sample}/annotations",
            {"target_id": "x", "kind": "note", "text": "t"},
        ),
        ("POST", f"/investigations/{sample}/resume", {"value": {}}),
    ):
        assert demo.request(method, path, json=body).status_code == 403, path
    assert (
        demo.post(
            f"/investigations/{sample}/chat", json={"message": "hello"}
        ).status_code
        == 200
    )  # chat is allowed


async def test_samples_are_invisible_to_signed_in_users_and_a_demo_sees_no_one_elses(
    world: World,
) -> None:
    sample = await world.investigation(SAMPLE)
    ada, ada_id = await world.person("ada")
    mine = await world.investigation(ada_id)
    demo, _ = await world.demo()
    assert ada.get(f"/investigations/{sample}").status_code == 404
    assert demo.get(f"/investigations/{mine}").status_code == 404
    assert {i["id"] for i in ada.get("/investigations").json()} == {str(mine)}


async def test_a_demo_visitor_cannot_connect_sources_or_edit_the_directory(
    world: World,
) -> None:
    demo, _ = await world.demo()
    assert demo.delete("/integrations/google").status_code in (403, 503)
    assert demo.post("/directory/customers", json={"name": "Acme"}).status_code == 403
    assert demo.put("/directory/customers/x", json={"name": "Acme"}).status_code == 403
    assert demo.delete("/directory/customers/x").status_code == 403
    assert demo.get("/directory").status_code == 200


# ---- the directory is per person ---------------------------------------------------------


async def test_each_person_has_their_own_directory(world: World) -> None:
    ada, _ = await world.person("ada")
    bob, _ = await world.person("bob")
    made = ada.post(
        "/directory/customers",
        json={"name": "Acme Fund", "email_domains": ["acme.example"]},
    )
    assert made.status_code == 201
    assert [c["name"] for c in ada.get("/directory").json()["customers"]] == [
        "Acme Fund"
    ]
    assert bob.get("/directory").json()["customers"] == []
    cid = made.json()["id"]
    assert (
        bob.put(f"/directory/customers/{cid}", json={"name": "Hijack"}).status_code
        == 404
    )
    assert bob.delete(f"/directory/customers/{cid}").status_code == 404
    assert [c["name"] for c in ada.get("/directory").json()["customers"]] == [
        "Acme Fund"
    ]


async def test_the_demo_directory_is_shared_and_separate_from_anyone_elses(
    world: World,
) -> None:
    from investigator.directory import CustomerInput, build

    await world.directory.put(
        "customer", build("customer", CustomerInput(name="Sample Fund")), SAMPLE
    )
    ada, _ = await world.person("ada")
    demo, _ = await world.demo()
    assert [c["name"] for c in demo.get("/directory").json()["customers"]] == [
        "Sample Fund"
    ]
    assert ada.get("/directory").json()["customers"] == []


async def test_a_write_from_another_site_is_refused_even_with_a_valid_session(
    world: World,
) -> None:
    ada, ada_id = await world.person("ada")
    inv = await world.investigation(ada_id)
    r = ada.patch(
        f"/investigations/{inv}",
        json={"owner": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
