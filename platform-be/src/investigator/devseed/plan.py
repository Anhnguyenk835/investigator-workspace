"""Builds the whole world's beat sheet, dates the backdated beats, and saves/loads it."""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from investigator.devseed.beats import Attach, Beat, Fact, Story
from investigator.devseed.cast import Org, Person, World, build_world
from investigator.devseed.ctx import Ctx
from investigator.devseed.noise import noise
from investigator.devseed.stories_a import blueridge, crestline, meridian
from investigator.devseed.stories_b import lotus, summit, tidewater
from investigator.devseed.stories_c import granite, silverleaf

STORIES = [
    meridian,
    crestline,
    blueridge,
    tidewater,
    lotus,
    summit,
    granite,
    silverleaf,
]


def _utc_hour(p: Person, local_hour: float) -> float:
    sign = 1 if p.tz.startswith("+") else -1
    offset = sign * (int(p.tz[1:3]) + int(p.tz[3:5]) / 60)
    return local_hour - offset


def date_beats(c: Ctx, stories: list[Story]) -> None:
    """Give each backdated beat a send time inside its actor's working day."""
    for s in stories:
        for b in s.beats:
            if b.day is None:
                continue
            if b.source != "email":
                raise ValueError(f"{b.id}: only email can be backdated")
            p = c.w.p(b.actor)
            local = c.rng.uniform(8.5, 17.0)
            when = c.when(b.day, 0.0) + timedelta(hours=_utc_hour(p, local))
            b.at = when.astimezone(UTC).isoformat()
        by_id = {b.id: b for b in s.beats}
        for b in s.beats:
            if b.reply_to and b.day is not None and by_id[b.reply_to].day is not None:
                parent = by_id[b.reply_to]
                if datetime.fromisoformat(b.at) <= datetime.fromisoformat(parent.at):
                    b.at = (
                        datetime.fromisoformat(parent.at)
                        + timedelta(hours=c.rng.uniform(0.3, 5))
                    ).isoformat()


def check(c: Ctx, stories: list[Story]) -> list[str]:
    """Problems in the plan before anything is written."""
    bad: list[str] = []
    now = c.now
    seen: set[str] = set()
    for s in stories:
        ids = {b.id for b in s.beats}
        for b in s.beats:
            if b.id in seen:
                bad.append(f"duplicate beat id {b.id}")
            seen.add(b.id)
            if b.reply_to and b.reply_to not in ids:
                bad.append(f"{b.id}: reply_to {b.reply_to} is not in the story")
            if b.at and datetime.fromisoformat(b.at) > now:
                bad.append(f"{b.id}: dated in the future")
            if b.source == "email" and not b.to:
                bad.append(f"{b.id}: email without recipients")
            for k in [b.actor, *b.to, *b.cc]:
                if k not in c.w.people:
                    bad.append(f"{b.id}: unknown person {k}")
        live_started = False
        for b in s.beats:
            if b.day is None:
                live_started = True
            elif live_started:
                bad.append(f"{b.id}: a backdated beat comes after a live one")
    return bad


def build(seed: int, now: datetime | None = None) -> tuple[Ctx, list[Story]]:
    now = now or datetime.now(UTC)
    rng = random.Random(seed)
    w = build_world(rng)
    c = Ctx(now=now, rng=rng, w=w)
    stories = [fn(c) for fn in STORIES]
    stories += noise(c)
    date_beats(c, stories)
    return c, stories


# ---- saving -------------------------------------------------------------------------


def dump(path: Path, run: str, seed: int, c: Ctx, stories: list[Story]) -> None:
    doc = {
        "run": run,
        "seed": seed,
        "now": c.now.isoformat(),
        "people": [asdict(p) for p in c.w.people.values()],
        "orgs": [asdict(o) for o in c.w.orgs.values()],
        "stories": [asdict(s) for s in stories],
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))


def _beat(d: dict[str, Any]) -> Beat:
    d = dict(d)
    d["attach"] = [Attach(**a) for a in d.get("attach", [])]
    return Beat(**d)


def load(path: Path) -> tuple[str, int, datetime, World, list[Story]]:
    doc = json.loads(path.read_text())
    w = World()
    for p in doc["people"]:
        p["aliases"] = tuple(p.get("aliases", ()))
        w.people[p["key"]] = Person(**p)
    for o in doc["orgs"]:
        w.orgs[o["key"]] = Org(**o)
    stories = []
    for s in doc["stories"]:
        s = dict(s)
        s["beats"] = [_beat(b) for b in s["beats"]]
        s["facts"] = [Fact(**f) for f in s["facts"]]
        stories.append(Story(**s))
    return doc["run"], doc["seed"], datetime.fromisoformat(doc["now"]), w, stories


def manifest(stories: list[Story]) -> list[dict[str, Any]]:
    """The ground truth, for scoring investigations of these stories later."""
    return [
        {
            "id": s.id,
            "customer": s.customer,
            "title": s.title,
            "question": s.question,
            "facts": [asdict(f) for f in s.facts],
        }
        for s in stories
        if s.facts
    ]
