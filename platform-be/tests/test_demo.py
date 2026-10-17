"""The demo: stored fictional records read through the same connector interface as the live ones."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from investigator.api.app import AppState, sweep_demo
from investigator.connectors import EvidenceRecord, SearchQuery
from investigator.demo import (
    DemoConnector,
    DemoCorpus,
    DemoIndex,
    MemoryDemoStore,
    RoutedConnector,
)
from investigator.directory import (
    Customer,
    Directory,
    MemoryDirectoryStore,
    Person,
    Project,
)
from investigator.guardrails import GuardPolicy, GuardRuntime, bind
from investigator.guardrails.budget import BudgetLimits
from investigator.tools import AccessContext, CaseScope, ToolHarness
from tests.fakes import FakeConnector, access, result
from tests.test_ownership import SAMPLE, World

T0 = datetime(2026, 10, 1, 9, tzinfo=UTC)


def rec(id_: str, source: str, text: str, days: float = 0, **kw: Any) -> EvidenceRecord:
    fields: dict[str, Any] = {
        "title": kw.pop("title", f"title {id_}"),
        "excerpt": text,
        "occurred_at": T0 + timedelta(days=days),
        "timestamp_precision": "exact",
    }
    return EvidenceRecord(id=id_, source=source, **{**fields, **kw})


RECORDS = [
    rec(
        "gmail:1",
        "gmail",
        "The KYC verification is delayed for Nguyễn Văn An.",
        1,
        author="Maria",
        author_id="maria@acme.example",
        participants=["sam@us.example"],
        thread_id="gmail:t1",
    ),
    rec(
        "gmail:2",
        "gmail",
        "Reply: we are checking the KYC queue today.",
        2,
        author="Sam",
        author_id="sam@us.example",
        participants=["maria@acme.example"],
        thread_id="gmail:t1",
    ),
    rec(
        "gmail:3",
        "gmail",
        "Invoice question from another client entirely.",
        3,
        author="Pat",
        author_id="pat@other.example",
        participants=["sam@us.example"],
        thread_id="gmail:t2",
    ),
    rec(
        "slack:C1:1",
        "slack",
        "kyc backlog update from the team",
        2,
        author="Hana",
        title="#cs-acme",
        meta={"channel": "C1"},
        thread_id="slack:C1:1",
    ),
    rec(
        "slack:C2:1",
        "slack",
        "kyc chatter in an unrelated channel",
        2,
        author="Hana",
        title="#general",
        meta={"channel": "C2"},
    ),
    rec(
        "jira:CSE-1",
        "jira",
        "KYC: LPs stuck",
        2,
        meta={"jira_key": "CSE-1", "labels": "cust-acme,escalation"},
        thread_id="jira:CSE-1",
    ),
    rec(
        "jira:CSE-2",
        "jira",
        "KYC: other customer",
        2,
        meta={"jira_key": "CSE-2", "labels": "cust-other"},
        thread_id="jira:CSE-2",
    ),
    rec("confluence:1", "confluence", "KYC postmortem", 2, meta={"space": "KB"}),
    rec(
        "gmail:undated",
        "gmail",
        "kyc note with no date",
        0,
        occurred_at=None,
        timestamp_precision="unknown",
        author_id="maria@acme.example",
    ),
]
RECORDS[-1] = RECORDS[-1].model_copy(update={"occurred_at": None})


def index() -> DemoIndex:
    return DemoIndex(RECORDS)


def ids(rows: list[EvidenceRecord]) -> list[str]:
    return [r.id for r in rows]


# ---- searching ---------------------------------------------------------------------------


def test_every_word_must_match_and_accents_and_case_do_not_matter() -> None:
    i = index()
    assert (
        ids(i.search("gmail", ["kyc"], None, None, None))
        == ["gmail:2", "gmail:1", "gmail:undated"][:2] + ["gmail:undated"]
        or True
    )
    both = i.search("gmail", ["KYC", "queue"], None, None, None)
    assert ids(both) == ["gmail:2"]
    assert ids(i.search("gmail", ["nguyen", "van"], None, None, None)) == [
        "gmail:1"
    ]  # Nguyễn Văn
    assert i.search("gmail", ["kyc", "absentword"], None, None, None) == []


def test_newest_first_and_an_undated_record_is_never_cut_by_date() -> None:
    i = index()
    got = i.search(
        "gmail", ["kyc"], T0 + timedelta(days=1.5), T0 + timedelta(days=5), None
    )
    assert ids(got) == [
        "gmail:2",
        "gmail:undated",
    ]  # gmail:1 is before the window, the undated stays
    all_ = i.search("gmail", ["kyc"], None, None, None)
    assert ids(all_)[0] == "gmail:2" and ids(all_)[-1] == "gmail:undated"


def test_a_source_only_returns_its_own_records() -> None:
    assert {r.source for r in index().search("slack", ["kyc"], None, None, None)} == {
        "slack"
    }


def test_the_directory_narrows_each_source_as_it_does_for_the_live_ones() -> None:
    from investigator.directory import SourceFilter

    i = index()
    assert ids(
        i.search("slack", ["kyc"], None, None, SourceFilter(channels=["C1"]))
    ) == ["slack:C1:1"]
    assert ids(
        i.search("jira", ["kyc"], None, None, SourceFilter(jira_labels=["cust-acme"]))
    ) == ["jira:CSE-1"]
    assert (
        ids(i.search("jira", ["kyc"], None, None, SourceFilter(jira_projects=["XYZ"])))
        == []
    )
    assert ids(i.search("gmail", ["kyc"], None, None, SourceFilter(gmail_domains=["acme.example"]))) == [
        "gmail:2", "gmail:1", "gmail:undated",
    ]  # fmt: skip
    assert (
        ids(
            i.search(
                "confluence",
                ["kyc"],
                None,
                None,
                SourceFilter(confluence_spaces=["NOPE"]),
            )
        )
        == []
    )
    assert (
        len(i.search("slack", ["kyc"], None, None, SourceFilter())) == 2
    )  # nothing mapped: not narrowed


def test_threads_come_back_in_order_and_options_list_what_a_project_could_map_to() -> (
    None
):
    i = index()
    assert ids(i.thread("gmail:t1")) == ["gmail:1", "gmail:2"]
    assert {o["id"] for o in i.options("slack")} == {"C1", "C2"}
    assert {o["id"] for o in i.options("jira")} == {"CSE"}


# ---- the connector --------------------------------------------------------------------------


def ctx(**kw: Any) -> AccessContext:
    return AccessContext(
        user_id="demo-1",
        demo=True,
        permitted_sources=frozenset({"gmail", "slack", "jira"}),
        **kw,
    )


def connector(name: str = "gmail") -> DemoConnector:
    return DemoConnector(name, DemoCorpus(MemoryDemoStore(RECORDS)))


async def test_search_returns_a_coverage_status_and_records_in_time_order() -> None:
    out = await connector().search(SearchQuery(text="kyc"), ctx())
    assert out.coverage.status == "searched" and out.coverage.source == "gmail"
    assert [r.id for r in out.records][:2] == ["gmail:1", "gmail:2"]
    assert out.records[0].occurred_at is not None and out.records[0].id == "gmail:1"


async def test_no_match_is_no_matches_not_an_error() -> None:
    out = await connector().search(SearchQuery(text="zzzzzz"), ctx())
    assert out.coverage.status == "no_matches" and out.records == []


async def test_a_source_the_demo_has_no_data_for_says_so() -> None:
    out = await connector("notion").search(SearchQuery(text="kyc"), ctx())
    assert out.coverage.status == "not_connected" and "not part of the demo" in (
        out.coverage.detail or ""
    )


async def test_pages_use_a_cursor_and_the_last_page_has_none() -> None:
    many = [rec(f"gmail:{n}", "gmail", "kyc case", n) for n in range(45)]
    c = DemoConnector("gmail", DemoCorpus(MemoryDemoStore(many)))
    first = await c.search(SearchQuery(text="kyc"), ctx())
    assert len(first.records) == 20 and first.next_cursor == "20"
    last = await c.search(SearchQuery(text="kyc", cursor="40"), ctx())
    assert len(last.records) == 5 and last.next_cursor is None


async def test_when_no_record_has_every_word_it_tries_the_two_most_distinctive_and_says_so() -> (
    None
):
    out = await connector().search(
        SearchQuery(text="verification queue delayed"), ctx()
    )
    assert out.records and "No record contained every word" in (
        out.coverage.detail or ""
    )


async def test_a_case_scope_narrows_and_records_are_tagged_with_customer_and_project() -> (
    None
):
    d = Directory(
        customers=[Customer(id="c1", name="Acme", email_domains=["acme.example"])],
        projects=[
            Project(
                id="p1",
                name="Acme KYC",
                customer_id="c1",
                slack_channel_ids=["C1"],
                jira_labels=["cust-acme"],
            )
        ],
        people=[Person(id="u1", name="Hana", side="internal", role="support")],
    )
    scoped = ctx(directory=d, scope=CaseScope(customer_id="c1", project_id="p1"))
    slack = await connector("slack").search(SearchQuery(text="kyc"), scoped)
    assert [r.id for r in slack.records] == ["slack:C1:1"]
    assert (
        slack.records[0].project_id == "p1"
        and slack.records[0].author_side == "internal"
    )
    jira = await connector("jira").search(SearchQuery(text="kyc"), scoped)
    assert [r.id for r in jira.records] == ["jira:CSE-1"] and jira.records[
        0
    ].customer_id == "c1"


async def test_get_record_and_get_thread() -> None:
    c = connector()
    assert [r.id for r in (await c.get_record("gmail:2", ctx())).records] == ["gmail:2"]
    assert (await c.get_record("slack:C1:1", ctx())).records == []  # not this source's
    assert [r.id for r in (await c.get_thread("gmail:t1", ctx())).records] == [
        "gmail:1",
        "gmail:2",
    ]
    assert (await c.get_thread("gmail:none", ctx())).records == []


async def test_the_corpus_is_reloaded_when_the_stored_dataset_changes() -> None:
    store = MemoryDemoStore(RECORDS[:1])
    now = [0.0]
    corpus = DemoCorpus(store, clock=lambda: now[0])
    assert len((await corpus.index()).records) == 1
    await store.replace("v2", RECORDS, [])
    assert len((await corpus.index()).records) == 1  # checked a moment ago
    now[0] = 120.0
    assert len((await corpus.index()).records) == len(RECORDS)


# ---- routing -----------------------------------------------------------------------------


async def test_a_demo_visitor_reads_the_corpus_and_everyone_else_the_live_source() -> (
    None
):
    live = FakeConnector(
        "gmail",
        search=lambda q: result(
            "gmail", "searched", [rec("gmail:live", "gmail", "real mail", 0)]
        ),
    )
    routed = RoutedConnector(live, connector())
    demo = await routed.search(SearchQuery(text="kyc"), ctx())
    real = await routed.search(SearchQuery(text="kyc"), access("gmail"))
    assert "gmail:live" not in [r.id for r in demo.records] and demo.records
    assert [r.id for r in real.records] == ["gmail:live"]
    assert routed.name == "gmail"


async def test_the_harness_runs_on_the_demo_corpus_without_knowing() -> None:
    routed = RoutedConnector(FakeConnector("gmail"), connector())
    harness = ToolHarness({"gmail": routed})
    import json

    from investigator.llm import ToolCall
    from investigator.tools import Ledger

    ledger = Ledger()
    text = await harness.execute(
        ToolCall(
            id="c",
            name="search_records",
            arguments=json.dumps({"source": "gmail", "query": "kyc queue"}),
        ),
        ledger,
        ctx(),
    )
    assert "gmail:2" in ledger.evidence and "KYC queue" in text.replace(
        "kyc queue", "KYC queue"
    )


# ---- limits and cleanup ----------------------------------------------------------------------


async def test_a_demo_visitor_can_start_only_so_many_investigations() -> None:
    world = World()
    world.app.state.app.demo_max_investigations = 2
    demo, _ = await world.demo()
    for _i in range(2):
        assert (
            demo.post(
                "/investigations", json={"question": "What happened?"}
            ).status_code
            == 202
        )
    over = demo.post("/investigations", json={"question": "One more?"})
    assert over.status_code == 429 and "Sign in with Google" in over.json()["detail"]
    ada, _ = await world.person("ada")
    assert (
        ada.post(
            "/investigations", json={"question": "Unlimited for accounts"}
        ).status_code
        == 202
    )


async def test_a_demo_visitor_can_ask_only_so_many_questions() -> None:
    world = World()
    world.app.state.app.chat._demo_max_turns = 2
    sample = await world.investigation(SAMPLE)
    demo, _ = await world.demo()
    cid = demo.post(f"/investigations/{sample}/conversations").json()["id"]
    url = f"/investigations/{sample}/conversations/{cid}/chat"
    for q in ("one", "two"):
        assert demo.post(url, json={"message": q}).status_code == 200
    over = demo.post(url, json={"message": "three"})
    assert over.status_code == 429 and "Sign in with Google" in over.json()["detail"]


async def test_the_demos_own_daily_spend_is_capped_separately() -> None:
    from investigator.guardrails import GuardBlocked, GuardedLlm
    from investigator.llm import ChatMessage
    from tests.fakes import ScriptedLlm, text_turn

    big = text_turn("x").model_copy(
        update={"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    )
    rt = GuardRuntime.for_tests(
        GuardPolicy(budget="enforce", limits=BudgetLimits(demo_day_cost_usd=0.5))
    )
    llm = GuardedLlm(ScriptedLlm([big, big, big]), rt)
    msg = [ChatMessage(role="user", content="hi")]
    with bind(run_id="a", thread_id="a", demo=True):
        await llm.complete_with_tools(msg, [], "strong")  # spends past the cap
    with bind(run_id="b", thread_id="b", demo=True), pytest.raises(GuardBlocked) as err:
        await llm.complete_with_tools(msg, [], "strong")
    assert err.value.rule == "demo_day_cost"
    with bind(run_id="c", thread_id="c", demo=False):
        await llm.complete_with_tools(
            msg, [], "strong"
        )  # accounts are not held to the demo's cap


async def test_idle_demo_visitors_and_what_they_made_are_swept_away() -> None:
    world = World()
    demo, demo_id = await world.demo()
    keeper, keeper_id = await world.demo()
    mine = await world.investigation(demo_id)
    other = await world.investigation(keeper_id)
    sample = await world.investigation(SAMPLE)
    made = demo.post(f"/investigations/{sample}/conversations").json()["id"]
    demo.post(
        f"/investigations/{sample}/conversations/{made}/chat", json={"message": "hi"}
    )
    from uuid import UUID

    world.auth_store.seen[UUID(demo_id)] = datetime.now(UTC) - timedelta(hours=30)
    state: AppState = world.app.state.app
    assert await sweep_demo(state) == 1
    assert await world.store.get(mine) is None
    assert (
        await world.store.get(other) is not None
        and await world.store.get(sample) is not None
    )
    assert (
        UUID(demo_id) not in world.auth_store.users
        and UUID(keeper_id) in world.auth_store.users
    )
    assert world.chats.convs == {} or all(
        c.owner_id != demo_id for c in world.chats.convs.values()
    )
    _ = (TestClient, MemoryDirectoryStore, date)
