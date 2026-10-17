"""Runs against docker-compose Postgres; skipped when it is not reachable."""

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from psycopg import AsyncConnection, OperationalError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from investigator.agents.investigation import InvestigationState, ReviewResume
from investigator.agents.investigation.schemas import CaseContext
from investigator.investigations import PostgresInvestigationStore
from investigator.investigations.checkpoint import checkpoint_serde
from investigator.settings import get_settings
from tests.fakes import ScriptedLlm
from tests.scenario import advance, make_graph, structured


@pytest.fixture
async def pool() -> AsyncIterator[AsyncConnectionPool[Any]]:
    url = get_settings().database_url
    try:
        conn = await AsyncConnection.connect(url, connect_timeout=2)
        await conn.close()
    except OperationalError:
        pytest.skip("Postgres not reachable")
    async with AsyncConnectionPool(
        url, kwargs={"autocommit": True, "row_factory": dict_row}, open=False
    ) as p:
        yield p


async def test_store_roundtrip_including_a_pause(
    pool: AsyncConnectionPool[Any],
) -> None:
    store = PostgresInvestigationStore(pool)
    await store.setup()
    inv = await store.create("roundtrip", CaseContext(project_id="p1"))
    assert inv.status == "queued" and inv.context.project_id == "p1"

    state = InvestigationState(question="roundtrip", summary="s", context=inv.context)
    await store.save_result(
        inv.id,
        state,
        status="needs_review",
        awaiting="review",
        pending={"kind": "review"},
    )
    got = await store.get(inv.id)
    assert (
        got is not None and got.summary == "s" and got.context.project_id == "p1"
    )  # context survives
    assert got.awaiting == "review" and got.pending == {"kind": "review"}

    await store.set_status(inv.id, "investigating")  # moving again clears the pause
    got = await store.get(inv.id)
    assert got is not None and got.awaiting is None and got.pending is None
    assert (
        await store.fail_unfinished("x") >= 1
    )  # investigating runs do not survive a restart

    async with pool.connection() as conn:
        await conn.execute("DELETE FROM investigations WHERE id = %s", (inv.id,))


async def test_a_paused_run_resumes_from_postgres_after_a_restart(
    pool: AsyncConnectionPool[Any],
) -> None:
    saver = AsyncPostgresSaver(pool, serde=checkpoint_serde())
    await saver.setup()
    thread = str(uuid4())

    first = make_graph(ScriptedLlm(structured=structured()))
    first.checkpointer = saver
    state, pending = await advance(first, {"question": "Why late?"}, thread)
    assert pending is not None and pending["kind"] == "review"

    # A new graph object (as after a restart) picks up the saved pause.
    second = make_graph(ScriptedLlm(structured=structured()))
    second.checkpointer = saver
    resume: Command[Any] = Command(
        resume=ReviewResume(decision="approved").model_dump()
    )
    state, pending = await advance(second, resume, thread)
    assert pending is not None and pending["kind"] == "draft_approval"
    assert {e.id for e in state.evidence} == {
        "e1",
        "c1",
    } and state.draft_status == "drafted"


async def test_credential_store_roundtrip_and_single_use_state(
    pool: AsyncConnectionPool[Any],
) -> None:
    from datetime import UTC, datetime, timedelta

    from investigator.integrations import PostgresCredentialStore
    from investigator.integrations.models import PendingAuthorization

    store = PostgresCredentialStore(pool)
    await store.setup()
    user = f"test-{uuid4()}"
    now = datetime.now(UTC)

    await store.put(user, "google", b"sealed-1")
    await store.put(user, "google", b"sealed-2")  # upsert
    await store.put(user, "slack", b"sealed-3")
    assert await store.get(user, "google") == b"sealed-2"
    assert set(await store.list(user)) == {"google", "slack"}
    await store.delete(user, "google")
    assert await store.get(user, "google") is None

    pending = PendingAuthorization(
        state=f"s-{uuid4()}",
        user_id=user,
        provider="google",
        code_verifier="v",
        expires_at=now + timedelta(minutes=10),
    )
    await store.save_pending(pending, now)
    assert await store.pop_pending(pending.state) == pending
    assert await store.pop_pending(pending.state) is None  # single use

    await store.delete(user, "slack")


async def test_event_and_chat_stores_roundtrip(pool: AsyncConnectionPool[Any]) -> None:
    from investigator.chat import PostgresChatStore
    from investigator.investigations.events import PostgresEventStore

    events = PostgresEventStore(pool)
    chats = PostgresChatStore(pool)
    await events.setup()
    await chats.setup()
    inv = uuid4()

    await events.append(inv, "run", {"mode": "start"})
    await events.append(inv, "step", {"node": "intake"})
    got = await events.after(inv, 0)
    assert [e.kind for e in got] == ["run", "step"] and got[1].data == {
        "node": "intake"
    }
    assert [e.kind for e in await events.after(inv, got[0].id)] == ["step"]
    assert await events.after(uuid4(), 0) == []

    first = await chats.add(inv, "user", "hello")
    await chats.add(
        inv,
        "assistant",
        "hi [E:e1]",
        {"citations": ["e1"], "warnings": ["w"], "tools": [{"tool": "t"}]},
    )
    listed = await chats.list(inv)
    assert [m.role for m in listed] == ["user", "assistant"] and listed[
        0
    ].id == first.id
    assert listed[1].citations == ["e1"] and listed[1].warnings == ["w"]
    await chats.clear(inv)
    assert await chats.list(inv) == []

    async with pool.connection() as conn:
        await conn.execute(
            "DELETE FROM investigation_events WHERE investigation_id = %s", (inv,)
        )


def test_the_real_app_wires_every_store_it_exposes(pool: Any) -> None:
    """The lifespan builds the real AppState; a store left out shows up as a 503 here."""
    import psycopg
    from fastapi.testclient import TestClient

    from investigator.api.app import create_app

    def forget_test_visitors() -> None:
        # Demo sessions are limited per address; earlier runs of this test must not use it up.
        with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
            # A fresh database (CI) has no users table until the app has started once.
            if conn.execute("SELECT to_regclass('users')").fetchone()[0] is not None:  # type: ignore[index]
                conn.execute("DELETE FROM users WHERE created_ip = 'testclient'")

    forget_test_visitors()
    with TestClient(create_app()) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/directory").status_code == 401  # signed out
        assert (
            client.post("/auth/demo").status_code == 200
        )  # a session, so the rest is reachable
        assert client.get("/directory").status_code == 200
        assert client.get("/integrations").status_code == 200
        assert client.get("/investigations").status_code == 200
        state = client.app.state.app  # type: ignore[attr-defined]
        assert state.events is not None and state.directory is not None
        forget_test_visitors()
        assert state.connectors, (
            "connectors must be handed to the API for source suggestions"
        )


async def test_job_queue_leases_retries_and_never_hands_one_job_to_two_workers(
    pool: AsyncConnectionPool[Any],
) -> None:
    import asyncio

    from investigator.jobs import PostgresJobQueue

    q = PostgresJobQueue(pool)
    await q.setup()
    async with pool.connection() as conn:
        await conn.execute("DELETE FROM jobs")
    inv = uuid4()
    ids = [await q.enqueue("start", inv, {"n": n}) for n in range(4)]

    # Several workers claiming at once each get a different job.
    claimed = await asyncio.gather(*(q.claim(f"w{n}", 30) for n in range(4)))
    assert {j.id for j in claimed if j} == set(ids)
    assert await q.claim("late", 30) is None
    assert await q.has_active(inv)

    first = claimed[0]
    assert first is not None
    holder = next(f"w{n}" for n, j in enumerate(claimed) if j and j.id == first.id)
    assert await q.heartbeat(first.id, holder, 30)  # the holder can renew
    assert not await q.heartbeat(first.id, "someone-else", 30)
    await q.complete(first.id, holder)

    # A job whose lease ran out is claimed again with one more attempt.
    second = claimed[1]
    assert second is not None
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE jobs SET locked_until = now() - interval '1 second' WHERE id = %s",
            (second.id,),
        )
    again = await q.claim("w9", 30)
    assert again is not None and again.id == second.id and again.attempts == 2

    # And one that has used its attempts is failed, not retried forever.
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE jobs SET locked_until = now() - interval '1 second', attempts = max_attempts WHERE id = %s",
            (second.id,),
        )
    await q.claim("w10", 30)
    async with pool.connection() as conn:
        cur = await conn.execute("SELECT status FROM jobs WHERE id = %s", (second.id,))
        row = await cur.fetchone()
        assert row is not None and row["status"] == "failed"
        await conn.execute("DELETE FROM jobs")


async def test_owner_rerun_orphans_and_annotations_in_postgres(
    pool: AsyncConnectionPool[Any],
) -> None:
    from investigator.investigations.annotations import PostgresAnnotationStore
    from investigator.jobs import PostgresJobQueue

    store = PostgresInvestigationStore(pool)
    await store.setup()
    await PostgresJobQueue(pool).setup()
    inv = await store.create("owner test", CaseContext())
    assert inv.owner is None and inv.run_no == 1

    await store.set_owner(inv.id, "Priya")
    assert (await store.next_run(inv.id)) == 2
    got = await store.get(inv.id)
    assert (
        got is not None
        and got.owner == "Priya"
        and got.run_no == 2
        and got.status == "queued"
    )

    # A run that looks active but has no job and has been quiet for a while is failed.
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE investigations SET updated_at = now() - interval '5 minutes' WHERE id = %s",
            (inv.id,),
        )
    assert await store.fail_orphans("lost") >= 1
    got = await store.get(inv.id)
    assert got is not None and got.status == "failed" and got.error == "lost"

    notes = PostgresAnnotationStore(pool)
    await notes.setup()
    a = await notes.add(inv.id, "fd_1", "note", "check this", "Sam")
    await notes.add(inv.id, "fd_1", "reviewed", "", "Priya")
    assert [(x.kind, x.author) for x in await notes.list(inv.id)] == [
        ("note", "Sam"),
        ("reviewed", "Priya"),
    ]
    assert not await notes.delete(inv.id, a.id, "Priya") and await notes.delete(
        inv.id, a.id, "Sam"
    )

    async with pool.connection() as conn:
        await conn.execute(
            "DELETE FROM annotations WHERE investigation_id = %s", (inv.id,)
        )
        await conn.execute("DELETE FROM investigations WHERE id = %s", (inv.id,))


async def test_guard_audit_tables_are_idempotent_and_hold_no_content(
    pool: AsyncConnectionPool[Any],
) -> None:
    from investigator.guardrails import (
        BufferedAuditSink,
        GuardedLlm,
        GuardRuntime,
        PostgresAuditSink,
        bind,
    )
    from investigator.llm import ChatMessage
    from tests.fakes import ScriptedLlm, text_turn

    run = f"pg-audit-{uuid4()}"
    store = PostgresAuditSink(pool)
    await store.setup()
    await store.setup()  # running twice must not fail
    sink = BufferedAuditSink(store)
    sink.start()
    rt = GuardRuntime.for_tests(sink=sink)
    llm = GuardedLlm(ScriptedLlm([text_turn("reply")]), rt)
    with bind(run_id=run, actor="Sam", ip="10.1.1.1", purpose="chat"):
        await llm.complete_with_tools(
            [ChatMessage(role="user", content="private words")], []
        )
        await rt.emit("pii", "email", enforced=False, action="redact")
    await sink.aclose()
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM llm_call_audit WHERE run_id = %s", (run,)
        )
        rows = await cur.fetchall()
        ev = await (
            await conn.execute(
                "SELECT guard, enforced FROM guard_event WHERE run_id = %s", (run,)
            )
        ).fetchall()
    assert len(rows) == 1 and rows[0]["actor"] == "Sam" and rows[0]["ip"] == "10.1.1.1"
    assert "private words" not in str(rows[0]) and "reply" not in str(rows[0])
    assert ev == [{"guard": "pii", "enforced": False}]


async def test_placeholder_numbers_are_shared_between_processes_and_hold_no_values(
    pool: AsyncConnectionPool[Any],
) -> None:
    import asyncio

    from investigator.guardrails.pii.aliases import PostgresAliasBook

    scope = f"inv-{uuid4()}"
    one = PostgresAliasBook(pool, b"secret")
    two = PostgresAliasBook(pool, b"secret")  # another process: its own cache
    await one.setup()
    await one.setup()
    values = [f"person{i}@x.co" for i in range(12)]
    got = await asyncio.gather(*(one.ordinal(scope, "EMAIL", v) for v in values))
    assert sorted(got) == list(range(1, 13))  # racing writers never share a number
    again = await asyncio.gather(*(two.ordinal(scope, "EMAIL", v) for v in values))
    assert again == got  # the same value, the same number, from another process
    other = await two.ordinal(f"inv-{uuid4()}", "EMAIL", values[0])
    assert other == 1  # numbering starts afresh per investigation
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT * FROM pii_alias WHERE scope_id = %s", (scope,)
        )
        rows = await cur.fetchall()
    assert len(rows) == 12 and "person0@x.co" not in str(rows)


async def test_old_audit_rows_can_be_purged(pool: AsyncConnectionPool[Any]) -> None:
    from datetime import UTC, datetime, timedelta

    from investigator.guardrails import GuardEvent, PostgresAuditSink

    store = PostgresAuditSink(pool)
    await store.setup()
    tag = f"purge-{uuid4()}"
    old = datetime.now(UTC) - timedelta(days=400)
    await store.event(
        GuardEvent(guard="pii", rule=tag, action="redact", enforced=True, at=old)
    )
    await store.event(GuardEvent(guard="pii", rule=tag, action="redact", enforced=True))
    assert await store.purge_older_than(365) >= 1
    async with pool.connection() as conn:
        cur = await conn.execute(
            "SELECT count(*) AS n FROM guard_event WHERE rule = %s", (tag,)
        )
        row = await cur.fetchone()
    assert row is not None and row["n"] == 1


async def test_conversations_roundtrip_and_old_messages_become_a_conversation(
    pool: AsyncConnectionPool[Any],
) -> None:
    from investigator.chat import PostgresChatStore

    chats = PostgresChatStore(pool)
    await chats.setup()
    inv = uuid4()
    # Messages written before conversations existed carry no conversation id.
    async with pool.connection() as conn:
        for role, text in (
            ("user", "Why was it late? And a long second sentence."),
            ("assistant", "Because."),
        ):
            await conn.execute(
                "INSERT INTO chat_messages (id, investigation_id, role, content) VALUES (%s, %s, %s, %s)",
                (uuid4(), inv, role, text),
            )
    await chats.setup()  # the migration runs on every start and is safe to repeat
    await chats.setup()
    (old,) = await chats.conversations(inv)
    assert old.title.startswith("Why was it late?") and old.message_count == 2
    assert [m.role for m in await chats.list(inv, conversation_id=old.id)] == [
        "user",
        "assistant",
    ]

    fresh = await chats.create_conversation(inv)
    assert fresh.title == "New chat"
    first = await chats.add(
        inv, "user", "Second thread question", conversation_id=fresh.id
    )
    assert first.conversation_id == fresh.id
    listed = await chats.conversations(inv)
    assert listed[0].id == fresh.id and listed[0].title == "Second thread question"
    assert (await chats.list(inv, conversation_id=old.id))[0].content.startswith(
        "Why was it late?"
    )
    await chats.rename(fresh.id, "Renamed")
    got = await chats.get_conversation(fresh.id)
    assert got is not None and got.title == "Renamed" and got.message_count == 1
    await chats.delete_conversation(fresh.id)
    assert await chats.get_conversation(fresh.id) is None
    assert len(await chats.conversations(inv)) == 1
    await chats.clear(inv)
    assert await chats.conversations(inv) == []


async def test_owner_scoping_in_postgres(pool: AsyncConnectionPool[Any]) -> None:
    from investigator.agents.investigation.schemas import CaseContext
    from investigator.auth import MemoryAuthStore, PostgresAuthStore
    from investigator.chat import PostgresChatStore
    from investigator.directory import CustomerInput, PostgresDirectoryStore, build

    ada, bob = f"ada-{uuid4()}", f"bob-{uuid4()}"
    inv = PostgresInvestigationStore(pool)
    await inv.setup()
    a1 = await inv.create("q1", CaseContext(), ada)
    b1 = await inv.create("q2", CaseContext(), bob)
    legacy = await inv.create("q3", CaseContext(), None)
    assert {i.id for i in await inv.list(200, [ada])} == {a1.id}
    assert {i.id for i in await inv.list(200, [ada, bob])} == {a1.id, b1.id}
    assert legacy.id in {i.id for i in await inv.list(200, [None])}
    assert legacy.id not in {i.id for i in await inv.list(200, [ada, bob])}
    assert await inv.count_by_owner(ada) == 1

    directory = PostgresDirectoryStore(pool)
    await directory.setup()
    entry = build("customer", CustomerInput(name=f"Acme {ada}"))
    await directory.put("customer", entry, ada)
    assert [c.name for c in (await directory.load(ada)).customers] == [entry.name]
    assert (await directory.load(bob)).customers == []
    await directory.put(
        "customer", build("customer", CustomerInput(name="Hijack"), entry.id), bob
    )
    assert [c.name for c in (await directory.load(ada)).customers] == [entry.name]
    assert not await directory.delete("customer", entry.id, bob)
    assert await directory.delete("customer", entry.id, ada)

    chats = PostgresChatStore(pool)
    await chats.setup()
    mine = await chats.create_conversation(a1.id, owner_id=ada)
    await chats.add(a1.id, "user", "hi", conversation_id=mine.id)
    assert [c.id for c in await chats.conversations(a1.id, ada)] == [mine.id]
    assert await chats.conversations(a1.id, bob) == []

    auth = PostgresAuthStore(pool)
    await auth.setup()
    await auth.setup()
    user = await auth.upsert_google(f"sub-{uuid4()}", "x@y.example", "X", None)
    token = f"tok-{uuid4()}"
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    await auth.create_session(user.id, token, now + timedelta(days=1), "1.1.1.1", "ua")
    got = await auth.principal(token, now, None)
    assert got is not None and got.email == "x@y.example"
    assert await auth.principal(token, now + timedelta(days=2), None) is None  # expired
    assert await auth.principal("not-a-token", now, None) is None
    await auth.end_session(token)
    assert await auth.principal(token, now, None) is None
    demo = await auth.create_demo("9.9.9.9")
    assert await auth.demos_from("9.9.9.9", now - timedelta(hours=1)) >= 1
    assert demo.id in await auth.idle_demo_ids(now + timedelta(days=1))
    await auth.delete_users([demo.id, user.id])
    _ = MemoryAuthStore
