"""A conversation reads what is connected now, not the snapshot the run left behind, and can
list and choose where to look."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from investigator.agents.chat import ChatDeps, build_chat_graph
from investigator.agents.chat.context import render_context
from investigator.agents.investigation.schemas import SupportDraft
from investigator.agents.investigation.state import InvestigationState
from investigator.auth import LOCAL, Principal
from investigator.chat import ChatService, MemoryChatStore
from investigator.chat.availability import SourceNow, build, from_integrations
from investigator.connectors import SourceCoverage
from investigator.integrations import IntegrationStatus
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import FakeConnector, ScriptedLlm, rec, result, text_turn, tool_turn
from tests.scenario import supports_everything
from tests.test_chat import NOW, state_with

SLACK_CHANNELS = [
    {"id": "C1", "label": "#general"},
    {"id": "C2", "label": "#escalations"},
]


def snapshot() -> InvestigationState:
    """An investigation that ran when only email was connected."""
    return state_with(
        coverage=[
            SourceCoverage(
                source="chat", status="not_connected", detail="Slack is not connected."
            ),
            SourceCoverage(source="email", status="searched"),
        ]
    )


async def service(
    llm: ScriptedLlm,
    connectors: list[FakeConnector],
    availability: Any,
) -> tuple[ChatService, UUID, MemoryStore]:
    store = MemoryStore()
    llm.structured.setdefault(SupportDraft, supports_everything)
    st = snapshot()
    inv = await store.create(st.question, st.context)
    await store.save_result(inv.id, st, status="needs_review")
    access = AccessContext(
        user_id="local", permitted_sources=frozenset(c.name for c in connectors)
    )
    graph = build_chat_graph(ChatDeps(llm=llm, connectors=connectors))  # type: ignore[arg-type]
    chat = ChatService(
        graph, MemoryChatStore(), store, access, availability=availability
    )
    return chat, inv.id, store


def now(**states: str) -> Any:
    async def read(_: Principal) -> list[SourceNow]:
        return [SourceNow(source=k, state=v) for k, v in states.items()]  # type: ignore[arg-type]

    return read


async def ask(
    chat: ChatService, id: UUID, text: str
) -> list[tuple[str, dict[str, Any]]]:
    return [e async for e in chat.stream(id, text, principal=LOCAL)]


# ---- what the model is told ------------------------------------------------------------


async def test_the_model_is_told_what_is_connected_now_and_that_the_run_was_a_snapshot() -> (
    None
):
    store = MemoryStore()
    st = snapshot()
    inv = await store.create(st.question, st.context)
    await store.save_result(inv.id, st, status="needs_review")
    record = await store.get(inv.id)
    assert record is not None
    text = render_context(
        record,
        [
            SourceNow(source="chat", state="connected", account="viet"),
            SourceNow(source="email", state="reconnect"),
            SourceNow(source="jira", state="not_connected"),
        ],
    )
    assert "Source availability now" in text
    assert "- chat: connected, can be searched now (viet)" in text
    assert "- email: connected but the access expired" in text
    assert "- jira: not connected" in text
    # the old coverage is still there, labelled as what it is
    assert "Coverage when the investigation last ran" in text
    assert "does not change when a source is connected afterwards" in text
    assert "- chat: not_connected (Slack is not connected.)" in text
    # without a reading, nothing is claimed about now
    assert "Source availability now" not in render_context(record)


async def test_only_what_is_connected_now_is_offered_as_a_tool() -> None:
    llm = ScriptedLlm(turns=[text_turn("Slack is connected.")])
    chat, id, _ = await service(
        llm,
        [FakeConnector("email"), FakeConnector("chat", options=SLACK_CHANNELS)],
        now(email="not_connected", chat="connected"),
    )
    await ask(chat, id, "is slack connected?")
    sent, tools = llm.tool_calls_seen[0]
    search = next(t for t in tools if t["function"]["name"] == "search_records")
    assert search["function"]["parameters"]["properties"]["source"]["enum"] == ["chat"]
    assert "- email: not connected" in sent[0].content
    assert "- chat: connected, can be searched now" in sent[0].content


async def test_nothing_connected_means_no_tools_and_the_model_is_told_why() -> None:
    llm = ScriptedLlm(turns=[text_turn("Nothing is connected right now.")])
    chat, id, _ = await service(
        llm, [FakeConnector("email")], now(email="not_connected")
    )
    await ask(chat, id, "search my mail")
    sent, tools = llm.tool_calls_seen[0]
    assert tools == [] and "- email: not connected" in sent[0].content


async def test_when_the_status_cannot_be_read_the_conversation_still_works() -> None:
    async def broken(_: Principal) -> list[SourceNow]:
        raise RuntimeError("database is down")

    llm = ScriptedLlm(turns=[text_turn("Answer [E:e1].")])
    chat, id, _ = await service(llm, [FakeConnector("email")], broken)
    events = await ask(chat, id, "hello?")
    assert events[-1][0] == "done"
    sent, tools = llm.tool_calls_seen[0]
    assert "Source availability now (read" not in sent[0].content and tools  # as before


# ---- listing and choosing ---------------------------------------------------------------


async def test_the_person_can_ask_what_is_in_a_source_then_search_a_part_of_it() -> (
    None
):
    found = rec(
        "s1", "slack", occurred_at=NOW, excerpt="Escalation raised in the channel"
    )
    slack_src = FakeConnector(
        "slack",
        options=SLACK_CHANNELS,
        search=lambda q: result("slack", "searched", [found]),
    )
    llm = ScriptedLlm(
        turns=[
            tool_turn(("list_scopes", {"source": "slack"})),
            text_turn("Channels: #general and #escalations. Which one?"),
            tool_turn(
                (
                    "search_records",
                    {
                        "source": "slack",
                        "query": "escalation",
                        "scope": ["#escalations"],
                    },
                )
            ),
            text_turn("It was raised there [E:s1]."),
        ]
    )
    svc, id, _ = await service(llm, [slack_src], now(slack="connected"))

    first = await ask(svc, id, "list all channels and I will tell you where to search")
    tool = next(d for n, d in first if n == "tool")
    assert tool["tool"] == "list_scopes" and tool["source"] == "slack"
    # the listing reached the model as data, with ids it can pass back
    _, history = llm.tool_calls_seen[1][0], llm.tool_calls_seen[1][0]
    listing = next(m.content for m in history if m.role == "tool")
    assert "C2 | #escalations" in listing and '<options source="slack">' in listing

    second = await ask(svc, id, "search #escalations for escalation")
    assert slack_src.filters[-1].channels == ["C2"]
    message = second[-1][1]["message"]
    assert message["citations"] == ["s1"]
    assert slack_src.listed == 1  # listed once; the search reused it


async def test_listing_where_to_look_is_not_counted_as_a_search_that_found_nothing() -> (
    None
):
    slack_src = FakeConnector("slack", options=SLACK_CHANNELS)
    llm = ScriptedLlm(
        turns=[
            tool_turn(("list_scopes", {"source": "slack"})),
            tool_turn(("list_scopes", {"source": "slack", "contains": "esc"})),
            tool_turn(("search_records", {"source": "slack", "query": "x"})),
            text_turn("Done."),
        ]
    )
    svc, id, _ = await service(llm, [slack_src], now(slack="connected"))
    events = await ask(svc, id, "what is in slack?")
    # two listing rounds did not use up the stale-round allowance before the search ran
    assert len(slack_src.queries) == 1 and events[-1][0] == "done"


# ---- status from the integrations ---------------------------------------------------------


def status(
    provider: str, sources: list[str], state: str, account: str | None = None
) -> IntegrationStatus:
    return IntegrationStatus(
        provider=provider,
        label=provider,
        sources=sources,
        state=state,  # type: ignore[arg-type]
        account=account,
    )


def test_integration_states_become_per_source_availability() -> None:
    rows = from_integrations(
        [
            status("google", ["gmail"], "connected", "me@x.com"),
            status("atlassian", ["jira", "confluence"], "reauth_required"),
            status("slack", ["slack"], "not_connected"),
            status("notion", ["notion"], "not_configured"),
        ],
        ["gmail", "jira", "confluence", "slack", "notion", "teams"],
    )
    got = {r.source: (r.state, r.account) for r in rows}
    assert got["gmail"] == ("connected", "me@x.com")
    assert got["jira"][0] == got["confluence"][0] == "reconnect"
    assert got["slack"][0] == "not_connected" and got["notion"][0] == "not_configured"
    assert got["teams"][0] == "not_configured"  # a source no provider unlocks


async def test_a_demo_visitor_is_connected_to_the_sources_the_stored_data_covers() -> (
    None
):
    class Corpus:
        async def index(self) -> Any:
            return type("I", (), {"sources": ["gmail", "slack"]})()

    read = build(None, Corpus(), ["gmail", "slack", "jira"])  # type: ignore[arg-type]
    rows = {r.source: r for r in await read(Principal(user_id="d", kind="demo"))}
    assert rows["gmail"].state == rows["slack"].state == "connected"
    assert (
        rows["gmail"].account == "Demo data" and rows["jira"].state == "not_connected"
    )
    # without sign-in services, a real user has nothing it can claim
    none = await build(None, None, ["gmail"])(Principal(user_id="u"))
    assert none[0].state == "not_configured"
