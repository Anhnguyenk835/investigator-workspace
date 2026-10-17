"""M6: personal details never reach the model, and come back for the people reading."""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from investigator.guardrails import (
    GuardedLlm,
    GuardPolicy,
    GuardRuntime,
    MemoryAuditSink,
    bind,
)
from investigator.guardrails.pii.aliases import MemoryAliasBook
from investigator.guardrails.pii.names import NameMatcher, directory_names, names_in
from investigator.guardrails.pii.tokenize import (
    ReverseMap,
    StreamRestorer,
    tokenize_text,
)
from investigator.llm import AssistantTurn, ChatMessage, Message, TextDelta, ToolCall
from tests.fakes import RecordingLlm, ScriptedLlm, text_turn, tool_turn

BOOK = MemoryAliasBook()


async def tok(
    text: str, names: set[str] | None = None, scope: str = "s"
) -> tuple[str, ReverseMap]:
    rev = ReverseMap()
    out = await tokenize_text(
        text, scope, MemoryAliasBook(), rev, NameMatcher(names) if names else None
    )
    return out, rev


# ---- tokenize and restore ----------------------------------------------------------

SAMPLES = [
    "Write to maria.chen@acme-fund.com or call +84 90 123 4567 about GB82 WEST 1234 5698 7654 32.",
    "Account no: 12345678 and Mã số thuế: 0312345678.",
    "From: Maria Chen <maria.chen@acme-fund.com>\nTo: Sam Doe <sam@us.test>\n\nHi Sam, the form is late. Regards,\nMaria Chen",
    "Nguyễn Văn Đức said nguyen van duc will call 0901234567. Duc agrees.",
    'Cited [E:gmail:18f2a] in <record id="gmail:18f2a" thread="gmail:t9" time="2026-10-12T09:00:00+00:00">x</record>.',
    "See https://acme.atlassian.net/browse/HPF-19?email=maria.chen@acme-fund.com for details.",
    "No identifiers here at all, just words and the date 2026-10-17 and ticket HPF-19.",
    "",
]
NAMES = {"Maria Chen", "Sam Doe", "Nguyễn Văn Đức"}


@pytest.mark.parametrize("text", SAMPLES)
async def test_restore_undoes_tokenize(text: str) -> None:
    out, rev = await tok(text, NAMES)
    assert rev.restore(out) == text


async def test_the_model_text_has_no_identifiers_left() -> None:
    out, _ = await tok(SAMPLES[0] + " " + SAMPLES[1], NAMES)
    for leaked in ("maria.chen", "90 123 4567", "GB82", "12345678", "0312345678"):
        assert leaked not in out
    assert re.findall(r"<[A-Z]+_\d+>", out)


async def test_the_same_value_is_always_the_same_placeholder() -> None:
    out, rev = await tok("a@x.co then A@X.CO and b@x.co, then a@x.co", None)
    nums = re.findall(r"<EMAIL_(\d+)>", out)
    assert nums == ["1", "1", "2", "1"]
    assert (
        rev.restore("<EMAIL_1> / <EMAIL_2>") == "a@x.co / b@x.co"
    )  # first-seen spelling


async def test_a_person_is_one_placeholder_whatever_the_spelling() -> None:
    out, rev = await tok(
        "Nguyễn Văn Đức wrote. Later nguyen van duc replied.", {"Nguyễn Văn Đức"}
    )
    assert re.findall(r"<PERSON_(\d+)\w?>", out) == [
        "1",
        "1",
    ]  # one person, two spellings
    assert "<PERSON_1b>" in out
    assert rev.restore(out) == "Nguyễn Văn Đức wrote. Later nguyen van duc replied."


async def test_structure_is_left_alone() -> None:
    text = 'cite [E:jira:HPF-19] <record id="x:1" thread="x:t" side="customer"> at https://e.co/a'
    out, _ = await tok(text, None)
    assert out == text


async def test_an_email_inside_a_web_address_is_not_split_out() -> None:
    out, rev = await tok(SAMPLES[5], None)
    assert out == SAMPLES[5] and not rev.values


@pytest.mark.parametrize(
    ("written", "ok"),
    [
        ("<PERSON_1>", True),
        ("<person_1>", True),
        ("<PERSON 1>", True),
        ("< PERSON_1 >", True),
        ("PERSON_1", True),
        ("<PERSON_1>'s call", True),
    ],
)
async def test_restore_accepts_how_models_actually_write_placeholders(
    written: str, ok: bool
) -> None:
    rev = ReverseMap(values={("PERSON", 1, ""): "Maria"})
    assert ("Maria" in rev.restore(written)) is ok


def test_an_unknown_placeholder_is_left_and_counted() -> None:
    rev = ReverseMap(values={("PERSON", 1, ""): "Maria"})
    assert rev.restore("<PERSON_7> and PERSON_9") == "<PERSON_7> and PERSON_9"
    assert (
        rev.unknown == 1
    )  # only the bracketed form counts; a bare word may be ordinary text


def test_restoring_inside_structured_values() -> None:
    rev = ReverseMap(values={("EMAIL", 1, ""): "a@x.co"})
    assert rev.restore_json({"q": ["<EMAIL_1>", 3], "n": {"x": "<EMAIL_1>"}}) == {
        "q": ["a@x.co", 3],
        "n": {"x": "a@x.co"},
    }


@pytest.mark.parametrize(
    "text",
    [
        "Hello <PERSON_1> and <EMAIL_12>, call <PHONE_3>.",
        "bare PERSON_1 here, and <PERSON 2> there",
        "a < b and <not a placeholder> and <PERS",
        "ends with <",
        "ends with <PERSON_",
        "no placeholders",
    ],
)
def test_stream_restore_is_the_same_however_the_text_is_cut(text: str) -> None:
    rev = ReverseMap(
        values={
            (k, n, ""): f"{k.lower()}-{n}"
            for k in ("PERSON", "EMAIL", "PHONE")
            for n in range(1, 15)
        }
    )
    whole = ReverseMap(values=dict(rev.values)).restore(text)

    def run(pieces: list[str]) -> str:
        r = StreamRestorer(ReverseMap(values=dict(rev.values)))
        return "".join(r.feed(p) for p in pieces) + r.flush()

    assert run([text]) == whole
    assert run(list(text)) == whole
    for i in range(len(text) + 1):
        assert run([text[:i], text[i:]]) == whole, i


# ---- names -------------------------------------------------------------------------


def test_names_come_from_metadata_not_guesswork() -> None:
    text = (
        '<record id="a" author="Maria Chen" side="customer">x</record>\n'
        'From: "Sam Doe" <sam@us.test>\nbody\nBest regards,\nPriya Rao\n'
        'author="Support Team" author="bot"'
    )
    assert names_in(text) == {"Maria Chen", "Sam Doe", "Priya Rao"}


def test_a_first_name_alone_matches_only_when_it_is_unambiguous() -> None:
    m = NameMatcher({"Maria Chen", "Maria Lopez", "Sam Doe"})
    found = [
        s.value for s in m.find("Maria called. Sam agreed. Lopez too. Doe said sam.")
    ]
    assert found == [
        "Sam",
        "Lopez",
        "Doe",
    ]  # Maria is two people; lower-case "sam" is a word


def test_everyday_words_and_group_names_are_never_people() -> None:
    m = NameMatcher({"Will Turner", "Support Team", "Grace Hall"})
    assert m.find("Support will handle it, in grace of time.") == []
    assert [s.value for s in m.find("Will Turner and Grace Hall")] == [
        "Will Turner",
        "Grace Hall",
    ]


def test_accents_do_not_matter_when_looking_a_name_up() -> None:
    m = NameMatcher({"Nguyễn Văn Đức"})
    spans = m.find("Gửi Nguyen Van Duc và NGUYỄN VĂN ĐỨC.")
    assert [s.value for s in spans] == ["Nguyen Van Duc", "NGUYỄN VĂN ĐỨC"]


def test_directory_people_are_names_too() -> None:
    class P:
        def __init__(self, name: str, aliases: list[str]) -> None:
            self.name, self.aliases = name, aliases

    class D:
        people: ClassVar[list[P]] = [P("Maria Chen", ["M. Chen"]), P("Client", [])]

    assert directory_names(D()) == {"Maria Chen", "M. Chen"}


# ---- through the choke point -------------------------------------------------------

PROMPT = (
    '<record id="gmail:1" source="email" author="Maria Chen" side="customer (CFO)" '
    'time="2026-10-12T09:00:00+00:00">\nFrom: Maria Chen <maria.chen@acme-fund.com>\n'
    "Please call me on +84 90 123 4567. Our IBAN is GB82 WEST 1234 5698 7654 32.\n</record>"
)


def guard(pii: str = "enforce") -> tuple[GuardRuntime, MemoryAuditSink]:
    sink = MemoryAuditSink()
    return GuardRuntime.for_tests(GuardPolicy(pii=pii), sink), sink  # type: ignore[arg-type]


class EchoLlm(RecordingLlm):
    """Answers by echoing the first of each placeholder kind it was given, as a model would."""

    async def complete_with_tools(
        self, messages: Any, tools: Any, route: str = "fast", **_: Any
    ) -> AssistantTurn:
        self.tool_calls_seen.append((list(messages), tools))
        text = "\n".join(m.content for m in messages)
        person = re.search(r"<PERSON_\d+>", text)
        email = re.search(r"<EMAIL_\d+>", text)
        who = person.group() if person else "nobody"
        return tool_turn(
            (
                "search_records",
                {"source": "email", "query": email.group() if email else "x"},
            ),
            text=f"{who} wrote to {email.group() if email else '-'}.",
        )


async def test_the_model_is_shown_placeholders_and_the_caller_gets_real_values() -> (
    None
):
    rt, sink = guard()
    inner = EchoLlm()
    llm = GuardedLlm(inner, rt)
    with bind(run_id="inv-1", thread_id="t", names={"Maria Chen"}):
        turn = await llm.complete_with_tools(
            [ChatMessage(role="user", content=PROMPT)], []
        )
    seen = inner.seen()
    for secret in ("maria.chen", "Maria Chen", "90 123 4567", "GB82"):
        assert secret not in seen
    assert "<PERSON_1>" in seen and "<EMAIL_1>" in seen
    assert turn.message.content == "Maria Chen wrote to maria.chen@acme-fund.com."
    (call,) = turn.message.tool_calls or []
    assert json.loads(call.arguments)["query"] == "maria.chen@acme-fund.com"
    assert {e.rule for e in sink.events} >= {"email", "phone", "iban", "person"}
    assert all(e.enforced for e in sink.events)
    assert "maria.chen" not in sink.calls[0].model_dump_json()


async def test_the_model_learns_names_from_what_it_reads() -> None:
    rt, _ = guard()
    inner = EchoLlm()
    llm = GuardedLlm(inner, rt)
    with bind(
        run_id="inv-1", thread_id="t"
    ):  # no directory: names come from the record itself
        turn = await llm.complete_with_tools(
            [ChatMessage(role="user", content=PROMPT)], []
        )
    assert "Maria Chen" not in inner.seen() and turn.message.content.startswith(
        "Maria Chen"
    )


async def test_history_with_tool_calls_is_tokenized_too() -> None:
    rt, _ = guard()
    inner = RecordingLlm(turns=[text_turn("ok")])
    llm = GuardedLlm(inner, rt)
    history = [
        ChatMessage(role="user", content="find mail from maria.chen@acme-fund.com"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[
                ToolCall(
                    id="1",
                    name="search_records",
                    arguments=json.dumps({"query": "maria.chen@acme-fund.com"}),
                )
            ],
        ),
        ChatMessage(role="tool", content="OK", tool_call_id="1", name="search_records"),
    ]
    with bind(run_id="inv-1", thread_id="t"):
        await llm.complete_with_tools(history, [])
    sent = inner.tool_calls_seen[0][0]
    assert (
        "maria.chen" not in sent[0].content
        and "maria.chen" not in (sent[1].tool_calls or [])[0].arguments
    )
    assert re.search(r"<EMAIL_1>", (sent[1].tool_calls or [])[0].arguments)


class Note(BaseModel):
    who: str = ""
    items: list[str] = []


async def test_structured_answers_are_restored_field_by_field() -> None:
    rt, _ = guard()
    inner = RecordingLlm(
        structured={Note: Note(who="<PERSON_1>", items=["<EMAIL_1>", "n/a"])}
    )
    llm = GuardedLlm(inner, rt)
    with bind(run_id="inv-1", thread_id="t", names={"Maria Chen"}):
        got, _ = await llm.complete_structured(
            [Message(role="user", content=PROMPT)], Note
        )
    assert got.who == "Maria Chen" and got.items == ["maria.chen@acme-fund.com", "n/a"]
    assert "maria.chen" not in inner.seen()


async def test_a_streamed_answer_is_restored_even_when_a_placeholder_is_split() -> None:
    rt, _ = guard()

    class Split(ScriptedLlm):
        async def stream_with_tools(
            self, messages: Any, tools: Any, route: str = "fast", **_: Any
        ) -> Any:
            for piece in ["Hello <PER", "SON_", "1>, mail <EMAIL_1", "> now"]:
                yield TextDelta(text=piece)
            yield text_turn("Hello <PERSON_1>, mail <EMAIL_1> now")

    llm = GuardedLlm(Split(), rt)
    got: list[str] = []
    final = None
    with bind(run_id="inv-1", thread_id="t", names={"Maria Chen"}):
        async for item in llm.stream_with_tools(
            [ChatMessage(role="user", content=PROMPT)], []
        ):
            if isinstance(item, TextDelta):
                got.append(item.text)
            else:
                final = item
    streamed = "".join(got)
    assert streamed == "Hello Maria Chen, mail maria.chen@acme-fund.com now"
    assert final is not None and final.message.content == streamed
    assert not any("<" in g and "PER" in g for g in got)


async def test_monitor_mode_counts_but_sends_the_original() -> None:
    rt, sink = guard("monitor")
    inner = RecordingLlm(turns=[text_turn("ok")])
    with bind(run_id="inv-1", thread_id="t"):
        await GuardedLlm(inner, rt).complete_with_tools(
            [ChatMessage(role="user", content=PROMPT)], []
        )
    assert "maria.chen@acme-fund.com" in inner.seen()
    assert sink.events and not any(e.enforced for e in sink.events)


async def test_a_tokenizer_failure_sends_nothing() -> None:
    class BrokenBook:
        async def ordinal(self, scope: str, kind: str, norm: str) -> int:
            raise RuntimeError("boom")

    rt, _ = guard()
    rt.aliases = BrokenBook()
    inner = RecordingLlm(turns=[text_turn("ok")])
    from investigator.guardrails import GuardBlocked

    with bind(run_id="inv-1", thread_id="t"), pytest.raises(GuardBlocked) as err:
        await GuardedLlm(inner, rt).complete_with_tools(
            [ChatMessage(role="user", content=PROMPT)], []
        )
    assert err.value.rule == "tokenizer_error" and inner.tool_calls_seen == []


async def test_a_placeholder_the_prompt_never_had_is_reported() -> None:
    rt, sink = guard()
    inner = RecordingLlm(turns=[text_turn("It was <PERSON_9>.")])
    with bind(run_id="inv-1", thread_id="t"):
        turn = await GuardedLlm(inner, rt).complete_with_tools(
            [ChatMessage(role="user", content="hi")], []
        )
    assert turn.message.content == "It was <PERSON_9>."
    assert any(e.rule == "unknown_placeholder" for e in sink.events)


async def test_numbering_is_shared_by_calls_in_one_investigation_and_not_across() -> (
    None
):
    rt, _ = guard()
    seen: list[str] = []

    class Spy(ScriptedLlm):
        async def complete_with_tools(
            self, messages: Any, tools: Any, route: str = "fast", **_: Any
        ) -> AssistantTurn:
            seen.append(" ".join(m.content for m in messages))
            return text_turn("ok")

    llm = GuardedLlm(Spy(), rt)
    with bind(run_id="inv-A", thread_id="t1"):
        await llm.complete_with_tools(
            [ChatMessage(role="user", content="a@x.co b@x.co")], []
        )
    with bind(run_id="inv-A", thread_id="t2"):  # a re-run, or a chat turn
        await llm.complete_with_tools([ChatMessage(role="user", content="b@x.co")], [])
    with bind(run_id="inv-B", thread_id="t3"):
        await llm.complete_with_tools([ChatMessage(role="user", content="b@x.co")], [])
    assert seen == ["<EMAIL_1> <EMAIL_2>", "<EMAIL_2>", "<EMAIL_1>"]


async def test_the_alias_book_never_holds_a_value() -> None:
    book = MemoryAliasBook(secret=b"k")
    await book.ordinal("s", "EMAIL", "a@x.co")
    assert "a@x.co" not in repr(book.__dict__)


# ---- a whole investigation ---------------------------------------------------------


async def test_a_whole_run_never_shows_the_model_a_person_yet_ends_with_real_names() -> (
    None
):
    from investigator.agents.investigation.schemas import (
        TimelineDraft,
        TimelineEventDraft,
    )
    from tests.fakes import FakeConnector, rec, result
    from tests.scenario import advance, make_graph, structured

    body = (
        "Maria Chen maria.chen@acme-fund.com asked to update the form. "
        "Call +84 90 123 4567."
    )

    def timeline(messages: Any) -> TimelineDraft:
        text = "\n".join(m.content for m in messages)
        who = re.search(r"<PERSON_\d+\w?>", text)
        assert who, "the model should have been given a placeholder, not the name"
        return TimelineDraft(
            events=[
                TimelineEventDraft(
                    title="Request received",
                    event_type="customer_request",
                    actor=who.group(),
                    summary=f"{who.group()} asks for the update.",
                    evidence_ids=["e1"],
                )
            ]
        )

    conns = [
        FakeConnector(
            "email",
            search=lambda q: result(
                "email",
                "searched",
                [
                    rec(
                        "e1",
                        "email",
                        excerpt=body,
                        author="Maria Chen",
                        project_id="p1",
                    )
                ],
            ),
        ),
        FakeConnector("chat", search=lambda q: result("chat", "no_matches")),
    ]
    rt, sink = guard()
    inner = RecordingLlm(structured=structured({TimelineDraft: timeline}))
    graph = make_graph(GuardedLlm(inner, rt), conns, guard=rt)  # type: ignore[arg-type]
    state, pending = await advance(
        graph, {"question": "Why was the form late?"}, "t-pii", "email", "chat"
    )

    assert pending is not None
    seen = inner.seen()
    for leaked in ("Maria Chen", "maria.chen@acme-fund.com", "90 123 4567"):
        assert leaked not in seen, leaked
    (event,) = state.timeline
    assert (
        event.actor == "Maria Chen"
        and event.summary == "Maria Chen asks for the update."
    )
    assert state.evidence[0].excerpt == body
    assert not re.search(r"<(?:PERSON|EMAIL|PHONE)_\d+\w?>", state.model_dump_json())
    assert {"email", "phone", "person"} <= {
        e.rule for e in sink.events if e.guard == "pii"
    }
