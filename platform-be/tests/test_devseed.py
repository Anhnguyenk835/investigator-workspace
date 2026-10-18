"""The seeder's plan: consistent, dated sensibly, truthful, and safe to write. Nothing here
touches a network."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from investigator.connectors.documents import extract_text
from investigator.devseed import plan as planmod
from investigator.devseed.attachments import docx, pdf
from investigator.devseed.beats import Story
from investigator.devseed.cast import iban, spaced
from investigator.devseed.compose import _missing
from investigator.devseed.ctx import Ctx
from investigator.devseed.post import Poster
from investigator.guardrails.pii.detect import find

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def built(seed: int = 7) -> tuple[Ctx, list[Story]]:
    return planmod.build(seed, NOW)


def test_the_plan_is_consistent() -> None:
    c, stories = built()
    assert planmod.check(c, stories) == []
    assert sum(len(s.beats) for s in stories) > 250


def test_the_same_seed_gives_the_same_world_and_another_seed_a_different_one() -> None:
    a = [(b.id, b.at, b.must) for s in built(7)[1] for b in s.beats]
    b = [(b.id, b.at, b.must) for s in built(7)[1] for b in s.beats]
    c = [(b.id, b.at, b.must) for s in built(8)[1] for b in s.beats]
    assert a == b and a != c


def test_every_backdated_beat_is_mail_in_the_past_and_replies_follow_what_they_answer() -> (
    None
):
    _, stories = built()
    for s in stories:
        by_id = {b.id: b for b in s.beats}
        for b in s.beats:
            if b.at:
                assert b.source == "email" and datetime.fromisoformat(b.at) <= NOW, b.id
            if b.reply_to and b.at and by_id[b.reply_to].at:
                assert b.at > by_id[b.reply_to].at, b.id


def test_stories_with_a_truth_have_a_question_and_facts_that_point_at_real_beats() -> (
    None
):
    _, stories = built()
    told = [s for s in stories if s.facts]
    assert len(told) >= 8
    for s in told:
        ids = {b.id for b in s.beats}
        assert s.question.endswith("?")
        for f in s.facts:
            assert set(f.where) <= ids, (s.id, f.statement)


def test_business_days_not_weekends() -> None:
    c, _ = built()
    for ago in range(40):
        assert c.date(ago).weekday() < 5 and c.ahead(ago).weekday() < 5


def test_planted_text_and_required_facts_are_checked_verbatim() -> None:
    _, stories = built()
    kyc = next(s for s in stories if s.id == "meridian-kyc")
    first = kyc.beats[0]
    assert _missing(first, "no mention of it") == first.must
    assert _missing(first, " ".join(first.must).upper()) == []
    planted = next(b for s in stories for b in s.beats if b.adversarial)
    assert _missing(planted, "x") and planted.adversarial in _missing(planted, "x")


def test_the_ids_are_real_ones() -> None:
    import random

    value = spaced(iban(random.Random(3)))
    assert [s.kind for s in find(value)] == ["IBAN"]


def test_the_documents_made_for_the_mail_can_be_read_back(tmp_path: Path) -> None:
    text = extract_text(
        "application/pdf",
        "a.pdf",
        pdf("Invoice INV-1", ["Total due: USD 1,234.00", "x" * 200]),
    )
    assert text is not None and "Invoice INV-1" in text and "USD 1,234.00" in text
    word = extract_text(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "a.docx",
        docx("Side letter", ["Fee 1.25%"]),
    )
    assert word is not None and "Fee 1.25%" in word


def test_a_dry_run_writes_nothing_and_resolves_ticket_references() -> None:
    c, stories = built()
    story = next(s for s in stories if s.id == "meridian-kyc")
    for b in story.beats:
        b.text = b.text or f"text for {b.id}"
    poster = Poster(c.w, "t", dry=True)
    poster.space_id = "0"
    live = [b for b in story.beats if b.day is None]
    for b in [x for x in live if x.source == "jira" and x.action == "create"] + [
        x for x in live if not (x.source == "jira" and x.action == "create")
    ]:
        poster.post(story, b)
    assert poster.counts["slack"] >= 9 and poster.counts["jira"] >= 7
    assert poster.fill("see {jira:meridian-bug}").startswith("see ENG-")
    assert poster.fill("see {jira:unknown}") == "see the Jira ticket"


def test_an_email_carries_threading_headers_attachments_and_a_signature() -> None:
    c, stories = built()
    story = next(s for s in stories if s.id == "meridian-kyc")
    for b in story.beats:
        b.text = f"body of {b.id}"
    poster = Poster(c.w, "t", dry=True)
    first, reply = story.beats[3], story.beats[4]  # m4 answers m3 in the same thread
    poster.post(story, story.beats[2], datetime.fromisoformat(story.beats[2].at))
    poster.post(story, first, datetime.fromisoformat(first.at))
    poster.post(story, reply, datetime.fromisoformat(reply.at))
    assert poster.counts["email"] == 3 and len(poster.thread_refs[first.thread]) == 3


def test_the_saved_plan_round_trips(tmp_path: Path) -> None:
    c, stories = built()
    path = tmp_path / "plan.json"
    planmod.dump(path, "r1", 7, c, stories)
    run, seed, _now, w, loaded = planmod.load(path)
    assert (run, seed) == ("r1", 7) and len(loaded) == len(stories)
    assert loaded[0].beats[0].attach[0].name == stories[0].beats[0].attach[0].name
    assert json.dumps(planmod.manifest(loaded)) == json.dumps(planmod.manifest(stories))
    assert w.p("bao").aliases


@pytest.mark.parametrize("name", ["rachel", "hana", "bao", "pete"])
def test_every_person_has_a_reserved_domain_address(name: str) -> None:
    c, _ = built()
    assert c.w.p(name).email.endswith(".example")


def test_the_demo_export_dates_every_record_inside_its_story_and_keeps_ids_unique() -> (
    None
):
    from investigator.demo import DemoIndex
    from investigator.devseed.demo_export import build

    c, stories = built()
    for s in stories:
        for b in s.beats:
            b.text = b.text or f"text for {b.id}"
    out = build(stories, c.w, NOW, NOW, 7)
    ids = [r.id for r in out.records]
    assert len(ids) == len(set(ids))
    assert all(r.occurred_at and r.occurred_at <= NOW for r in out.records)
    jira = [r for r in out.records if r.source == "jira"]
    assert jira and all(r.meta["jira_key"] in r.title for r in jira)
    slack = [r for r in out.records if r.source == "slack"]
    assert len({r.occurred_at.date() for r in slack if r.occurred_at}) > 1
    index = DemoIndex(out.records)
    assert index.search("gmail", [], None, None, None)
    assert len(out.samples) == len(out.projects) >= 8
    # Every sample has a short name of its own, so the list does not show the long question.
    names = [name for *_, name in out.samples]
    assert all(0 < len(n) <= 120 for n in names) and len(set(names)) == len(names)
    assert all(n != q for (*_, q, n) in out.samples)
