"""The conversation about one investigation: grounding, streaming, tools, persistence."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from investigator.agents.chat import ChatDeps, build_chat_graph
from investigator.agents.chat.context import MAX_RECORDS, render_context
from investigator.agents.chat.grounding import ground
from investigator.agents.investigation.schemas import (
    CaseContext,
    Finding,
    SupportDraft,
    SupportItemDraft,
    TimelineEvent,
)
from investigator.agents.investigation.state import InvestigationState
from investigator.api.app import AppState, create_app
from investigator.chat import ChatService, ChatUnavailableError, MemoryChatStore
from investigator.connectors import SearchQuery
from investigator.llm import LlmError
from investigator.tools import AccessContext
from tests.conftest import MemoryStore
from tests.fakes import FakeConnector, ScriptedLlm, rec, result, text_turn, tool_turn
from tests.scenario import supports_everything

NOW = datetime(2026, 10, 17, 9, tzinfo=UTC)
LOCAL = AccessContext(user_id="local", permitted_sources=frozenset({"email", "chat"}))


# ---- grounding ------------------------------------------------------------------------


def test_a_list_of_ids_needs_the_prefix_only_once() -> None:
    out = ground(
        "Both [E:slack:C1:1.5, notion:abc] agree.", {"slack:C1:1.5", "notion:abc"}
    )
    assert out.citations == ["slack:C1:1.5", "notion:abc"]
    assert "[E:slack:C1:1.5][E:notion:abc]" in out.text


def test_prompt_wrapper_tags_the_model_repeats_are_removed() -> None:
    out = ground("<user-input>\nList them\n</user-input>\nTwo channels [E:e1].", {"e1"})
    assert "<user-input>" not in out.text and "</user-input>" not in out.text
    assert out.text.endswith("Two channels [E:e1].") and out.citations == ["e1"]


def test_real_citations_stay_invented_ones_are_removed_and_weak_answers_flagged() -> (
    None
):
    out = ground("It was late [E:e1]. Also [E:zzz] and [E:e1] again.", {"e1"})
    assert out.citations == ["e1"]
    assert "zzz" not in out.text and out.text.count("[E:e1]") == 2
    assert any(
        "1 citation named a record that does not exist" in w for w in out.warnings
    )
    assert not any("cites no evidence" in w for w in out.warnings)

    bare = ground("Probably the supplier.", {"e1"})
    assert bare.citations == [] and any("cites no evidence" in w for w in bare.warnings)

    blame = ground("Sam is at fault for the delay [E:e1].", {"e1"})
    assert any("attributes fault" in w for w in blame.warnings)

    spaced = ground("One [E:a] two [E:zz] three", {"a"})
    assert "  " not in spaced.text


def test_several_ids_in_one_bracket_are_checked_one_by_one() -> None:
    out = ground("Both said so [E:a, E:b, E:fake].", {"a", "b"})
    assert out.citations == ["a", "b"]
    assert out.text == "Both said so [E:a][E:b]."
    assert any("1 citation named a record" in w for w in out.warnings)
    assert ground("Prose [x, y] and [E:a].", {"a"}).text == "Prose [x, y] and [E:a]."


def test_saying_fault_cannot_be_assigned_is_not_assigning_it() -> None:
    careful = ground(
        "Fault cannot be assigned to anyone from these records [E:a].", {"a"}
    )
    assert not any("attributes fault" in w for w in careful.warnings)
    flat = ground("The vendor is to blame for the delay [E:a].", {"a"})
    assert any("attributes fault" in w for w in flat.warnings)
    mixed = ground("There is no proof. Sam is at fault [E:a].", {"a"})
    assert any("attributes fault" in w for w in mixed.warnings)


def test_short_refusals_need_no_citation_but_claims_do() -> None:
    assert ground("I cannot send emails; a person has to.", {"a"}).warnings == []
    assert ground("The wire amount is $50,000.", {"a"}).warnings != []
    assert ground("The wire amount is unknown.", {"a"}).warnings == []
    assert (
        ground("Probably the supplier.", {"a"}).warnings != []
    )  # a bare guess is flagged
    long_claim = "The team agreed to deliver late " * 12
    assert any("cites no evidence" in w for w in ground(long_claim, {"a"}).warnings)


def test_ids_with_colons_and_dots_are_cited_whole() -> None:
    known = {"slack:C0:1792087485.185959", "jira:HPF-19"}
    out = ground("See [E:slack:C0:1792087485.185959] and [E:jira:HPF-19].", known)
    assert out.citations == ["slack:C0:1792087485.185959", "jira:HPF-19"]


# ---- the record the model is given ----------------------------------------------------


def state_with(**kw: Any) -> InvestigationState:
    return InvestigationState(
        question="Why was the form late?",
        evidence=[
            rec("e1", "email", occurred_at=NOW, excerpt="Please update the form"),
            rec("c1", "chat", occurred_at=NOW, excerpt="We expect it Friday"),
        ],
        findings=[
            Finding(
                id="f1",
                title="Request",
                claim="Client asked for the update",
                status="verified",
                supporting_evidence_ids=["e1"],
                reasoning_type="direct",
            )
        ],
        timeline=[
            TimelineEvent(
                id="t1",
                title="Delivery expected",
                event_type="commitment",
                summary="Team expects Friday",
                evidence_ids=["c1"],
                occurred_at=NOW,
                timestamp_precision="exact",
            )
        ],
        summary="Request made.",
        **kw,
    )


async def stored(state: InvestigationState, **save: Any) -> tuple[MemoryStore, UUID]:
    store = MemoryStore()
    inv = await store.create(state.question, state.context)
    await store.save_result(
        inv.id, state, status=save.pop("status", "needs_review"), **save
    )
    return store, inv.id


async def test_context_lists_findings_with_their_evidence_and_the_records() -> None:
    store, id = await stored(state_with())
    inv = await store.get(id)
    assert inv is not None
    text = render_context(inv)
    assert "[verified; direct] Client asked for the update | supports: e1" in text
    assert "Delivery expected: Team expects Friday (c1)" in text
    assert '<record id="e1"' in text and "Please update the form" in text
    assert (
        "Findings are" not in text
    )  # instructions live in the system prompt, not here


async def test_cited_records_come_first_and_the_budget_is_stated() -> None:
    many = [rec(f"r{i}", "email", occurred_at=NOW) for i in range(MAX_RECORDS + 10)]
    cited = rec("late", "email", occurred_at=NOW)
    state = state_with()
    state = state.model_copy(
        update={
            "evidence": [*many, cited],
            "findings": [
                Finding(
                    id="f",
                    title="t",
                    claim="c",
                    status="verified",
                    supporting_evidence_ids=["late"],
                    reasoning_type="direct",
                )
            ],
        }
    )
    store, id = await stored(state)
    inv = await store.get(id)
    assert inv is not None
    text = render_context(inv)
    assert '<record id="late"' in text  # kept although it was last in time
    assert "11 more records exist" in text


# ---- the graph ------------------------------------------------------------------------


async def service_for(
    llm: ScriptedLlm,
    state: InvestigationState | None = None,
    connectors: list[FakeConnector] | None = None,
    status: str = "needs_review",
    context: CaseContext | None = None,
) -> tuple[ChatService, UUID, MemoryChatStore, MemoryStore]:
    store = MemoryStore()
    llm.structured.setdefault(SupportDraft, supports_everything)
    st = state or state_with()
    if context:
        st = st.model_copy(update={"context": context})
    inv = await store.create(st.question, st.context)
    await store.save_result(inv.id, st, status=status)  # type: ignore[arg-type]
    chats = MemoryChatStore()
    graph = build_chat_graph(ChatDeps(llm=llm, connectors=connectors or []))  # type: ignore[arg-type]
    return ChatService(graph, chats, store, LOCAL), inv.id, chats, store


async def run(
    service: ChatService, id: UUID, text: str
) -> list[tuple[str, dict[str, Any]]]:
    return [e async for e in service.stream(id, text)]


async def test_an_answer_streams_in_pieces_then_arrives_checked_and_stored() -> None:
    llm = ScriptedLlm(
        turns=[text_turn("The client asked for it [E:e1] and Sam agreed [E:nope].")]
    )
    service, id, chats, _ = await service_for(llm)
    events = await run(service, id, "What did the client ask?")

    names = [n for n, _ in events]
    assert names[0] == "user_message" and names[-1] == "done"
    deltas = [d["text"] for n, d in events if n == "delta"]
    assert len(deltas) > 3 and "".join(deltas).startswith("The client asked")
    assert ("turn_end", {"tool_calls": False}) in events
    assert names.index("checking") < names.index(
        "done"
    )  # citations are checked before the answer is final

    message = events[-1][1]["message"]
    assert message["role"] == "assistant"
    assert "[E:nope]" not in message["content"] and "[E:e1]" in message["content"]
    assert message["citations"] == ["e1"]
    assert any("does not exist" in w for w in message["warnings"])

    saved = await chats.list(id)
    assert [m.role for m in saved] == ["user", "assistant"]
    assert saved[1].content == message["content"]

    # what the model saw: the record as grounding, then the question
    sent, _tools = llm.tool_calls_seen[0]
    assert sent[0].role == "system" and "INVESTIGATION RECORD" in sent[0].content
    assert '<record id="e1"' in sent[0].content
    assert sent[-1].role == "user" and sent[-1].content == (
        "<user-input>\nWhat did the client ask?\n</user-input>"
    )


async def test_earlier_turns_are_sent_as_history() -> None:
    llm = ScriptedLlm(turns=[text_turn("First [E:e1]."), text_turn("Second [E:c1].")])
    service, id, _, _ = await service_for(llm)
    await run(service, id, "one?")
    await run(service, id, "two?")
    sent, _ = llm.tool_calls_seen[1]
    assert [m.role for m in sent[1:]] == ["user", "assistant", "user"]
    assert "one?" in sent[1].content and sent[1].content.startswith("<user-input>")
    assert "First" in sent[2].content and sent[2].content.startswith("<derived-notes>")


async def test_the_model_can_search_again_and_the_new_record_is_citable() -> None:
    found = rec("e9", "email", occurred_at=NOW, excerpt="Late note from the client")
    email = FakeConnector(
        "email", search=lambda q: result("email", "searched", [found])
    )
    llm = ScriptedLlm(
        turns=[
            tool_turn(("search_records", {"source": "email", "query": "late note"})),
            text_turn("The client sent a late note [E:e9]."),
        ]
    )
    service, id, chats, _ = await service_for(llm, connectors=[email])
    events = await run(service, id, "Any late notes?")

    tool = next(d for n, d in events if n == "tool")
    assert tool["tool"] == "search_records" and tool["source"] == "email"
    assert tool["records"] == 1 and tool["new_records"] == 1 and "excerpt" not in tool
    turn_ends = [d for n, d in events if n == "turn_end"]
    assert [t["tool_calls"] for t in turn_ends] == [True, False]

    message = events[-1][1]["message"]
    assert message["citations"] == ["e9"]
    assert [e["id"] for e in message["new_evidence"]] == [
        "e9"
    ]  # not in the investigation
    assert (await chats.list(id))[1].tools[0]["source"] == "email"


async def test_searches_stay_inside_the_case() -> None:
    email = FakeConnector("email")
    llm = ScriptedLlm(
        turns=[
            tool_turn(
                (
                    "search_records",
                    {"source": "email", "query": "x", "date_from": "2000-01-01"},
                )
            ),
            text_turn("Nothing."),
        ]
    )
    case = CaseContext(date_from=date(2026, 10, 1), date_to=date(2026, 10, 31))
    service, id, _, _ = await service_for(llm, connectors=[email], context=case)
    await run(service, id, "anything earlier?")
    (query,) = email.queries
    assert isinstance(query, SearchQuery) and query.date_from == date(2026, 10, 1)


async def test_a_model_failure_ends_in_an_error_and_stores_no_answer() -> None:
    service, id, chats, _ = await service_for(ScriptedLlm(fail_tools=True))
    events = await run(service, id, "hello?")
    assert events[-1][0] == "error" and "boom" in events[-1][1]["message"]
    assert [m.role for m in await chats.list(id)] == ["user"]  # the question is kept


async def test_an_empty_answer_is_an_error_not_a_blank_message() -> None:
    service, id, chats, _ = await service_for(ScriptedLlm(turns=[text_turn("")]))
    events = await run(service, id, "hello?")
    assert events[-1][0] == "error"
    assert [m.role for m in await chats.list(id)] == ["user"]


async def test_a_turn_is_refused_while_the_run_is_going_or_another_turn_is_open() -> (
    None
):
    from investigator.chat import ChatUnavailableError

    service, id, _, store = await service_for(ScriptedLlm(), status="investigating")
    with pytest.raises(ChatUnavailableError) as running:
        await service.check(id)
    assert running.value.status == 409

    with pytest.raises(ChatUnavailableError) as missing:
        await service.check(UUID(int=1))
    assert missing.value.status == 404

    await store.set_status(id, "needs_review")
    service._active.add(id)
    with pytest.raises(ChatUnavailableError) as busy:
        await service.check(id)
    assert busy.value.status == 409
    events = await run(service, id, "again?")
    assert events == [("error", {"message": "The assistant is still answering."})]


async def test_the_lock_is_released_when_a_turn_ends_or_fails() -> None:
    service, id, _, _ = await service_for(ScriptedLlm(fail_tools=True))
    await run(service, id, "x")
    assert id not in service._active


# ---- HTTP -----------------------------------------------------------------------------


def parse(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        out.append((fields["event"], json.loads(fields["data"])))
    return out


async def api_for(llm: ScriptedLlm, **kw: Any) -> tuple[TestClient, UUID]:
    service, id, _, store = await service_for(llm, **kw)
    client = TestClient(
        create_app(AppState(store=store, graph=None, access=LOCAL, chat=service))
    )
    return client, id


async def test_http_streams_and_the_history_endpoint_returns_the_stored_turn() -> None:
    client, id = await api_for(ScriptedLlm(turns=[text_turn("It was Friday [E:c1].")]))
    resp = client.post(f"/investigations/{id}/chat", json={"message": "When?"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse(resp.text)
    assert events[0][0] == "user_message" and events[-1][0] == "done"

    messages = client.get(f"/investigations/{id}/chat").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["citations"] == ["c1"]

    assert client.delete(f"/investigations/{id}/chat").status_code == 204
    assert client.get(f"/investigations/{id}/chat").json() == {"messages": []}


async def test_http_errors_before_the_stream_starts() -> None:
    client, id = await api_for(ScriptedLlm(), status="investigating")
    url = f"/investigations/{id}/chat"
    assert client.post(url, json={"message": "hi"}).status_code == 409
    assert client.post(url, json={"message": ""}).status_code == 422
    assert client.post(url, json={"message": "x" * 4001}).status_code == 422
    assert client.post(url, json={"message": "   "}).status_code == 422
    missing = "/investigations/00000000-0000-0000-0000-000000000001/chat"
    assert client.post(missing, json={"message": "hi"}).status_code == 404
    assert client.get(missing).status_code == 404


async def test_http_without_a_model_says_the_assistant_is_unavailable() -> None:
    client = TestClient(
        create_app(AppState(store=MemoryStore(), graph=None, access=LOCAL))
    )
    url = "/investigations/00000000-0000-0000-0000-000000000001/chat"
    assert client.get(url).status_code == 503
    assert client.post(url, json={"message": "hi"}).status_code == 503


async def test_a_citation_the_record_does_not_back_is_removed_from_the_answer() -> None:
    def judge(messages: Any) -> SupportDraft:
        text = str(messages[-1].content)
        if (
            "wire" in text.lower()
        ):  # the sentence about the wire cites an unrelated email
            return SupportDraft(
                checks=[SupportItemDraft(evidence_id="e1", verdict="unsupported")]
            )
        return supports_everything(messages)

    llm = ScriptedLlm(
        turns=[
            text_turn(
                "The client asked for the update [E:e1]. The wire amount was 50k [E:e1]."
            )
        ],
        structured={SupportDraft: judge},
    )
    service, id, chats, _ = await service_for(llm)
    events = await run(service, id, "details?")
    assert "checking" in [n for n, _ in events]
    message = events[-1][1]["message"]
    assert message["content"].count("[E:e1]") == 1
    assert message["content"].endswith("50k.")  # the sentence stays, uncited
    assert any("did not support" in w for w in message["warnings"])
    assert message["citations"] == ["e1"]


async def test_when_the_check_cannot_run_the_models_citations_are_kept() -> None:
    llm = ScriptedLlm(
        turns=[text_turn("Asked [E:e1].")], structured={SupportDraft: LlmError("down")}
    )
    service, id, _, _ = await service_for(llm)
    message = (await run(service, id, "q"))[-1][1]["message"]
    assert message["citations"] == ["e1"] and "[E:e1]" in message["content"]


async def test_a_wrong_citation_leaves_the_answer_flagged_as_uncited() -> None:
    llm = ScriptedLlm(
        turns=[
            text_turn("The deadline was Friday the 16th of October at noon [E:c1].")
        ],
        structured={
            SupportDraft: SupportDraft(
                checks=[SupportItemDraft(evidence_id="c1", verdict="unsupported")]
            )
        },
    )
    service, id, _, _ = await service_for(llm)
    message = (await run(service, id, "q"))[-1][1]["message"]
    assert message["citations"] == [] and "[E:c1]" not in message["content"]
    assert any("cites no evidence" in w for w in message["warnings"])


# ---- many conversations per investigation ---------------------------------------------


async def test_each_conversation_keeps_its_own_history_and_is_named_after_its_first_question() -> (
    None
):
    llm = ScriptedLlm(
        turns=[text_turn("A [E:e1]."), text_turn("B [E:c1]."), text_turn("C [E:e1].")]
    )
    service, id, chats, _ = await service_for(llm)
    one = await service.create(id)
    two = await service.create(id)
    assert one.title == "New chat"
    async for _ in service.stream(
        id, "What did the client ask?", conversation_id=one.id
    ):
        pass
    async for _ in service.stream(
        id, "Who owns the follow-up?", conversation_id=two.id
    ):
        pass
    async for _ in service.stream(id, "And the deadline?", conversation_id=one.id):
        pass
    assert [
        m.content for m in await service.history(id, one.id) if m.role == "user"
    ] == [
        "What did the client ask?",
        "And the deadline?",
    ]
    assert [
        m.content for m in await service.history(id, two.id) if m.role == "user"
    ] == ["Who owns the follow-up?"]
    # the assistant saw only the earlier turns of its own conversation
    seen = llm.tool_calls_seen
    assert "Who owns" not in " ".join(m.content for m in seen[2][0])
    assert "What did the client ask" in " ".join(m.content for m in seen[2][0])
    titles = {c.id: c.title for c in await service.conversations(id)}
    assert (
        titles[one.id] == "What did the client ask?"
        and titles[two.id] == "Who owns the follow-up?"
    )
    # the one used last comes first
    assert (await service.conversations(id))[0].id == one.id
    assert (await service.conversations(id))[0].message_count == 4


async def test_conversations_can_be_renamed_and_deleted_and_belong_to_one_investigation() -> (
    None
):
    service, id, _, store = await service_for(
        ScriptedLlm(turns=[text_turn("x [E:e1].")])
    )
    c = await service.create(id)
    assert (
        await service.rename(id, c.id, "Deadline questions")
    ).title == "Deadline questions"
    other = await store.create("another", CaseContext())
    with pytest.raises(ChatUnavailableError) as err:
        await service.conversation(other.id, c.id)
    assert err.value.status == 404
    async for _ in service.stream(id, "hi", conversation_id=c.id):
        pass
    await service.delete(id, c.id)
    assert await service.conversations(id) == []
    with pytest.raises(ChatUnavailableError):
        await service.check(id, c.id)


async def test_two_conversations_can_answer_at_the_same_time_but_not_the_same_one_twice() -> (
    None
):
    service, id, _, _ = await service_for(ScriptedLlm())
    a, b = await service.create(id), await service.create(id)
    service._active.add(a.id)
    with pytest.raises(ChatUnavailableError) as err:
        await service.check(id, a.id)
    assert err.value.status == 409
    await service.check(id, b.id)  # the other one is free


async def test_http_conversation_endpoints() -> None:
    client, id = await api_for(
        ScriptedLlm(
            turns=[text_turn("It was Friday [E:c1]."), text_turn("Later [E:e1].")]
        )
    )
    base = f"/investigations/{id}/conversations"
    assert client.get(base).json() == {"conversations": []}
    made = client.post(base)
    assert made.status_code == 201 and made.json()["title"] == "New chat"
    cid = made.json()["id"]
    resp = client.post(f"{base}/{cid}/chat", json={"message": "When was it promised?"})
    assert parse(resp.text)[-1][0] == "done"
    listed = client.get(base).json()["conversations"]
    assert (
        listed[0]["title"] == "When was it promised?"
        and listed[0]["message_count"] == 2
    )
    msgs = client.get(f"{base}/{cid}/messages").json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"] and msgs[0][
        "conversation_id"
    ] == cid
    assert (
        client.patch(f"{base}/{cid}", json={"title": "  Promises  "}).json()["title"]
        == "Promises"
    )
    assert client.patch(f"{base}/{cid}", json={"title": "   "}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000009"
    assert client.get(f"{base}/{missing}/messages").status_code == 404
    assert (
        client.post(f"{base}/{missing}/chat", json={"message": "x"}).status_code == 404
    )
    assert client.delete(f"{base}/{cid}").status_code == 204
    assert client.get(base).json() == {"conversations": []}


async def test_the_old_single_chat_endpoints_still_use_the_latest_conversation() -> (
    None
):
    client, id = await api_for(
        ScriptedLlm(turns=[text_turn("a [E:e1]."), text_turn("b [E:e1].")])
    )
    client.post(f"/investigations/{id}/chat", json={"message": "first"})
    client.post(f"/investigations/{id}/chat", json={"message": "second"})
    msgs = client.get(f"/investigations/{id}/chat").json()["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["first", "second"]
    assert (
        len(client.get(f"/investigations/{id}/conversations").json()["conversations"])
        == 1
    )
