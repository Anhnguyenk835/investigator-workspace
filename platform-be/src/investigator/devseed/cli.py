"""Commands for the seeder.

plan      build the beat sheet, have a model write the words, save it (no external writes
          except calls to the LLM gateway)
post      write the saved plan into Gmail, Slack, Jira and Confluence
register  put the customers, projects and people into the platform's directory
status    what is in the saved plan and the last run
cleanup   remove what a run created
export-demo   store the plan as the demo corpus (records, directory, truth) in Postgres
notion-plan  write the Notion pages (a model writes them from the story facts) to a file
notion-post  create those pages in the connected Notion workspace
notion-cleanup  archive what notion-post created
run-samples   run the investigator once per story question over the demo corpus
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from investigator.devseed import plan as planmod
from investigator.devseed.beats import Story
from investigator.devseed.compose import compose
from investigator.devseed.post import PURPOSE_MARK, Poster

STATE = "seed-state.json"


def _env(path: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _google() -> tuple[str, Any]:
    """The platform's connected Google account and a function that returns a fresh token."""
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from investigator.integrations import (
        ClientCredentials,
        OAuthService,
        PostgresCredentialStore,
        TokenCipher,
    )
    from investigator.settings import get_settings

    s = get_settings()

    async def with_oauth(fn: Any) -> Any:
        async with (
            AsyncConnectionPool(
                s.database_url,
                kwargs={"autocommit": True, "row_factory": dict_row},
                open=False,
            ) as pool,
            httpx.AsyncClient() as http,
        ):
            oauth = OAuthService(
                store=PostgresCredentialStore(pool),
                cipher=TokenCipher(s.token_encryption_key),
                http=http,
                clients={
                    "google": ClientCredentials(
                        s.google_client_id, s.google_client_secret
                    )
                },
                api_public_url=s.api_public_url,
            )
            return await fn(oauth)

    account = asyncio.run(with_oauth(lambda o: o.account("local", "google")))["label"]

    def token() -> str:
        return str(asyncio.run(with_oauth(lambda o: o.access_token("local", "google"))))

    return account, token


# ---- plan ---------------------------------------------------------------------------


def cmd_plan(a: argparse.Namespace) -> int:
    c, stories = planmod.build(a.seed)
    problems = planmod.check(c, stories)
    if problems:
        print("\n".join(problems))
        return 1
    run = f"{datetime.now(UTC):%Y%m%d}-{a.seed}"
    if not a.no_llm:
        from investigator.llm import get_llm_client

        print(f"writing {sum(len(s.beats) for s in stories)} messages with the model…")
        stats = asyncio.run(compose(get_llm_client(), stories, c.w, workers=a.workers))
        print(stats)
    planmod.dump(Path(a.out), run, a.seed, c, stories)
    Path(a.out).with_suffix(".truth.json").write_text(
        json.dumps(planmod.manifest(stories), ensure_ascii=False, indent=1)
    )
    print(f"saved {a.out} (+ .truth.json)")
    return 0


# ---- post ---------------------------------------------------------------------------


def _live_sequence(story: Story) -> list[Any]:
    live = [b for b in story.beats if b.day is None]
    return [b for b in live if b.source == "jira" and b.action == "create"] + [
        b for b in live if not (b.source == "jira" and b.action == "create")
    ]


def cmd_post(a: argparse.Namespace) -> int:
    run, seed, _now, world, stories = planmod.load(Path(a.plan))
    only = (
        set(a.only.split(",")) if a.only else {"email", "slack", "jira", "confluence"}
    )
    secrets = _env(a.secrets)
    poster = Poster(world, run, dry=a.dry)
    if not a.dry:
        account, token = _google()
        poster.connect(
            slack_token=secrets["SLACK_BOT_TOKEN"],
            jira_base=secrets["JIRA_BASE_URL"],
            jira_auth=(secrets["JIRA_EMAIL"], secrets["JIRA_API_TOKEN"]),
            google=(account, token),
        )
        poster.ensure_project("ENG", "Engineering")
        poster.ensure_space("SEEDKB", "Customer Success Knowledge Base")
    else:
        poster.space_id = "0"
    rng = random.Random(seed)
    try:
        # Mail with a past date first, oldest first, so threads reference earlier messages.
        history = [
            (datetime.fromisoformat(b.at), s, b)
            for s in stories
            for b in s.beats
            if b.day is not None and b.source in only
        ]
        history.sort(key=lambda t: t[0])
        for i, (when, s, b) in enumerate(history, 1):
            poster.post(s, b, when)
            if i % 50 == 0:
                print(f"  history mail {i}/{len(history)}")
        print(f"history: {poster.counts['email']} emails")
        # The live part of every story, interleaved the way a busy day interleaves them.
        queues = {s.id: _live_sequence(s) for s in stories}
        by_id = {s.id: s for s in stories}
        for qid in list(queues):
            queues[qid] = [b for b in queues[qid] if b.source in only]
        total = sum(len(q) for q in queues.values())
        done = 0
        while any(queues.values()):
            sid = rng.choices(
                [k for k, q in queues.items() if q],
                weights=[len(q) for q in queues.values() if q],
            )[0]
            b = queues[sid].pop(0)
            try:
                poster.post(by_id[sid], b)
            except Exception as exc:  # noqa: BLE001  keep going; report at the end
                poster.errors.append(f"{b.id} ({b.source}): {exc}")
                print(f"  ! {b.id}: {exc}")
            done += 1
            if done % 25 == 0:
                print(f"  live {done}/{total}  {poster.counts}")
            if not a.dry and b.source != "email":
                time.sleep(rng.uniform(0.6, 1.3))
    finally:
        poster.close()
    Path(STATE).write_text(
        json.dumps(
            {
                "run": run,
                "channels": poster.channels,
                "jira": poster.jira_keys,
                "counts": poster.counts,
                "errors": poster.errors,
            },
            indent=1,
        )
    )
    print("done", poster.counts, f"errors={len(poster.errors)}")
    return 1 if poster.errors else 0


# ---- register -----------------------------------------------------------------------


def cmd_register(a: argparse.Namespace) -> int:
    _run, _seed, _now, world, stories = planmod.load(Path(a.plan))
    state = json.loads(Path(STATE).read_text())
    channels: dict[str, str] = state["channels"]
    api = httpx.Client(base_url=a.api, timeout=30)
    have = api.get("/directory").json()
    cust_by_name = {c["name"]: c for c in have["customers"]}
    proj_names = {p["name"] for p in have["projects"]}
    people_names = {p["name"] for p in have["people"]}
    orgs_done: dict[str, str] = {}
    for s in stories:
        if not s.facts:
            continue
        org = world.orgs[s.customer]
        if org.name not in cust_by_name:
            r = api.post(
                "/directory/customers",
                json={
                    "name": org.name,
                    "aliases": [org.name.split()[0]],
                    "email_domains": [org.domain],
                },
            )
            r.raise_for_status()
            cust_by_name[org.name] = r.json()
        orgs_done[s.customer] = cust_by_name[org.name]["id"]
        name = f"{org.name} - {s.title}"
        if name not in proj_names:
            ids = [channels[c] for c in s.channels if c in channels]
            r = api.post(
                "/directory/projects",
                json={
                    "name": name,
                    "customer_id": orgs_done[s.customer],
                    "aliases": [s.id],
                    "jira_projects": [],
                    "jira_labels": s.labels,
                    "slack_channel_ids": ids,
                    "confluence_spaces": [],
                },
            )
            r.raise_for_status()
    for p in world.people.values():
        if p.name in people_names or p.side == "third_party" and p.role == "vendor":
            continue
        cust = next(
            (orgs_done.get(k) for k, o in world.orgs.items() if o.name == p.org), None
        )
        r = api.post(
            "/directory/people",
            json={
                "name": p.name,
                "aliases": list(p.aliases),
                "emails": [p.email],
                "side": p.side,
                "role": p.role,
                "customer_id": cust if p.side == "customer" else None,
            },
        )
        if r.status_code >= 400:
            print("person", p.name, r.status_code, r.text[:100])
    ids = sorted({*channels.values()})
    print("directory updated; add these to SLACK_CHANNEL_IDS in platform-be/.env:")
    print(",".join(ids))
    return 0


# ---- status / cleanup ---------------------------------------------------------------


def cmd_status(a: argparse.Namespace) -> int:
    run, seed, _now, world, stories = planmod.load(Path(a.plan))
    print(f"run {run} seed {seed}: {len(world.people)} people")
    for s in stories:
        kinds: dict[str, int] = {}
        for b in s.beats:
            kinds[b.source] = kinds.get(b.source, 0) + 1
        print(f"  {s.id:28} {sum(kinds.values()):4}  {kinds}")
    return 0


def cmd_cleanup(a: argparse.Namespace) -> int:
    secrets = _env(a.secrets)
    slack = httpx.Client(
        base_url="https://slack.com/api/",
        headers={"Authorization": f"Bearer {secrets['SLACK_BOT_TOKEN']}"},
        timeout=30,
    )
    jira = httpx.Client(
        base_url=secrets["JIRA_BASE_URL"].rstrip("/"),
        auth=(secrets["JIRA_EMAIL"], secrets["JIRA_API_TOKEN"]),
        timeout=60,
    )
    n_ch = n_issue = 0
    cursor = ""
    while True:
        page = slack.post(
            "conversations.list",
            data={
                "types": "public_channel",
                "limit": "200",
                "exclude_archived": "true",
                "cursor": cursor,
            },
        ).json()
        for ch in page.get("channels", []):
            if PURPOSE_MARK in (ch.get("purpose") or {}).get("value", ""):
                slack.post("conversations.archive", data={"channel": ch["id"]})
                n_ch += 1
        cursor = (page.get("response_metadata") or {}).get("next_cursor", "")
        if not cursor:
            break
    while True:
        res = jira.post(
            "/rest/api/3/search/jql",
            json={
                "jql": 'labels = "investigator-seed"',
                "maxResults": 100,
                "fields": ["key"],
            },
        ).json()
        issues = res.get("issues", [])
        if not issues:
            break
        for it in issues:
            jira.delete(
                f"/rest/api/3/issue/{it['key']}", params={"deleteSubtasks": "true"}
            )
            n_issue += 1
    jira.delete("/wiki/rest/api/space/SEEDKB")
    account, token = _google()
    import imaplib

    auth = f"user={account}\x01auth=Bearer {token()}\x01\x01"
    m = imaplib.IMAP4_SSL("imap.gmail.com")
    m.authenticate("XOAUTH2", lambda _: auth.encode())
    m.select('"casefile-mock"')
    _t, d = m.search(None, "HEADER", "X-Investigator-Seed", "")
    ids = d[0].split()
    for i in ids:
        m.store(i, "+FLAGS", "\\Deleted")
    m.expunge()
    m.logout()
    print(
        f"archived {n_ch} channels, deleted {n_issue} issues, removed {len(ids)} emails, deleted the SEEDKB space"
    )
    return 0


# ---- demo ---------------------------------------------------------------------------


def _pool() -> Any:
    from psycopg.rows import dict_row
    from psycopg_pool import AsyncConnectionPool

    from investigator.settings import get_settings

    return AsyncConnectionPool(
        get_settings().database_url,
        kwargs={"autocommit": True, "row_factory": dict_row},
        open=False,
    )


def cmd_export_demo(a: argparse.Namespace) -> int:
    from investigator.auth.access import SAMPLE_ID
    from investigator.demo import PostgresDemoStore
    from investigator.devseed.demo_export import build
    from investigator.directory import PostgresDirectoryStore

    _run, seed, plan_now, world, stories = planmod.load(Path(a.plan))
    now = datetime.now(UTC)
    out = build(stories, world, plan_now, now, seed)
    by_source: dict[str, int] = {}
    for r in out.records:
        by_source[r.source] = by_source.get(r.source, 0) + 1
    print(f"{len(out.records)} records {by_source}")
    print(
        f"{len(out.customers)} customers, {len(out.projects)} projects, {len(out.people)} people"
    )
    if a.dry:
        return 0

    async def go() -> None:
        async with _pool() as pool:
            demo = PostgresDemoStore(pool)
            await demo.setup()
            directory = PostgresDirectoryStore(pool)
            await directory.setup()
            version = f"{now:%Y%m%d%H%M%S}-{seed}"
            await demo.replace(version, out.records, out.truth)
            have = await directory.load(SAMPLE_ID)
            for kind, rows in (
                ("customer", have.customers),
                ("project", have.projects),
                ("person", have.people),
            ):
                for row in rows:
                    await directory.delete(kind, row.id, SAMPLE_ID)
            for kind, entries in (
                ("customer", out.customers),
                ("project", out.projects),
                ("person", out.people),
            ):
                for entry in entries:
                    await directory.put(kind, entry, SAMPLE_ID)
            Path(a.samples).write_text(
                json.dumps(
                    [
                        {
                            "story": sid,
                            "customer_id": cid,
                            "project_id": pid,
                            "question": q,
                        }
                        for sid, cid, pid, q in out.samples
                    ],
                    ensure_ascii=False,
                    indent=1,
                )
            )
            print(f"stored dataset {version}; sample questions in {a.samples}")

    asyncio.run(go())
    return 0


def cmd_run_samples(a: argparse.Namespace) -> int:
    from investigator.agents.investigation.schemas import CaseContext
    from investigator.auth.access import SAMPLE_ID
    from investigator.investigations.runner import run_investigation, thread_id_for
    from investigator.runtime import open_runtime
    from investigator.settings import get_settings
    from investigator.tools import AccessContext

    samples = json.loads(Path(a.samples).read_text())
    if a.only:
        wanted = set(a.only.split(","))
        samples = [x for x in samples if x["story"] in wanted]

    async def go() -> int:
        async with open_runtime(get_settings()) as rt:
            if rt.graph is None:
                print("The LLM gateway is not configured; nothing to run.")
                return 1
            if rt.demo is not None:
                await rt.demo.refresh()
            removed = await rt.store.delete_owned(SAMPLE_ID)
            print(f"removed {removed} earlier sample investigations")
            directory = await rt.directory.load(SAMPLE_ID)
            access = AccessContext(
                user_id=SAMPLE_ID,
                demo=True,
                permitted_sources=rt.access.permitted_sources,
            )
            gate = asyncio.Semaphore(a.workers)
            failed = 0

            async def one(x: dict[str, str]) -> None:
                nonlocal failed
                async with gate:
                    ctx = CaseContext(
                        customer_id=x["customer_id"], project_id=x["project_id"]
                    )
                    rec = await rt.store.create(x["question"], ctx, SAMPLE_ID)
                    await run_investigation(
                        rt.graph,
                        rt.store,
                        rec.id,
                        {
                            "question": rec.question,
                            "context": ctx.model_dump(mode="json"),
                        },
                        access,
                        events=rt.events,
                        directory=directory,
                        thread_id=thread_id_for(rec.id, rec.run_no),
                        actor="Sample run",
                        verified=True,
                        demo=True,
                    )
                    done = await rt.store.get(rec.id)
                    status = done.status if done else "missing"
                    if status not in ("needs_review", "resolved"):
                        failed += 1
                    print(f"  {x['story']:28} {status}")

            await asyncio.gather(*(one(x) for x in samples))
            return 1 if failed else 0

    return asyncio.run(go())


# ---- notion -------------------------------------------------------------------------

NOTION_PLAN = "seed-notion.json"
NOTION_STATE = "seed-notion-state.json"


def cmd_notion_plan(a: argparse.Namespace) -> int:
    from investigator.devseed.notion_seed import write_pages
    from investigator.llm import get_llm_client

    _run, _seed, _now, world, stories = planmod.load(Path(a.plan))
    print("writing Notion pages with the model…")
    groups = asyncio.run(
        write_pages(get_llm_client(), stories, world, workers=a.workers)
    )
    Path(a.out).write_text(
        json.dumps(
            {k: [p.model_dump() for p in v] for k, v in groups.items()},
            ensure_ascii=False,
            indent=1,
        )
    )
    total = sum(len(v) for v in groups.values())
    print(f"{total} pages for {len(groups)} groups saved to {a.out}")
    return 0


def _notion_token(user: str) -> str:
    """The Notion token of a signed-in person (by email) or of the local user."""
    import psycopg

    from investigator.integrations import (
        ClientCredentials,
        OAuthService,
        PostgresCredentialStore,
        TokenCipher,
    )
    from investigator.settings import get_settings

    s = get_settings()
    owner = "local"
    if user != "local":
        with psycopg.connect(s.database_url) as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(%s)", (user,)
            ).fetchone()
        if row is None:
            raise SystemExit(f"No account with the email {user}. Sign in once first.")
        owner = str(row[0])

    async def go() -> str:
        async with (
            _pool() as pool,
            httpx.AsyncClient() as http,
        ):
            oauth = OAuthService(
                store=PostgresCredentialStore(pool),
                cipher=TokenCipher(s.token_encryption_key),
                http=http,
                clients={
                    "notion": ClientCredentials(
                        s.notion_client_id, s.notion_client_secret
                    )
                },
                api_public_url=s.api_public_url,
            )
            return str(await oauth.access_token(owner, "notion"))

    return asyncio.run(go())


def cmd_notion_post(a: argparse.Namespace) -> int:
    from investigator.devseed.notion_seed import (
        ROOT_TITLE,
        NotionWriter,
        folder_of,
        page_id,
    )

    groups: dict[str, list[dict[str, str]]] = json.loads(Path(a.pages).read_text())
    total = sum(len(v) for v in groups.values())
    token = a.token or ("" if a.dry else _notion_token(a.user))
    w = NotionWriter(token, dry=a.dry)
    try:
        parent = page_id(a.parent) if a.parent else ("dry" if a.dry else w.first_page())
        root = w.create(
            parent,
            ROOT_TITLE,
            "Customer success workspace: customer cases, runbooks, policies and meeting notes.",
        )
        customers = w.create(
            root,
            "Customers",
            "One folder per customer: call notes, hand-offs, reviews and plans.",
        )
        handbook = w.create(
            root,
            "Team handbook",
            "How the team works: runbooks, policies and meetings.",
        )
        folders: dict[str, str] = {}
        n = 0
        for group, pages in sorted(groups.items()):
            for p in pages:
                name = group or folder_of(p["title"])
                if name not in folders:
                    folders[name] = w.create(
                        customers if group else handbook,
                        name,
                        f"Everything about {name}.",
                    )
                w.create(folders[name], p["title"], p["markdown"])
                n += 1
                if n % 10 == 0:
                    print(f"  {n}/{total}")
        Path(NOTION_STATE).write_text(
            json.dumps({"root": root, "pages": len(w.created)})
        )
        print(f"created {len(w.created)} pages under '{ROOT_TITLE}' ({root})")
    finally:
        w.close()
    return 0


def cmd_notion_cleanup(a: argparse.Namespace) -> int:
    from investigator.devseed.notion_seed import NotionWriter

    root = json.loads(Path(NOTION_STATE).read_text())["root"]
    w = NotionWriter(a.token or _notion_token(a.user))
    try:
        w.archive(root)
    finally:
        w.close()
    print(f"archived {root} and everything under it")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="investigator.devseed")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", default="seed-plan.json")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--workers", type=int, default=6)
    p.set_defaults(fn=cmd_plan)
    for name, fn in (
        ("post", cmd_post),
        ("register", cmd_register),
        ("status", cmd_status),
        ("cleanup", cmd_cleanup),
    ):
        q = sub.add_parser(name)
        q.add_argument("--plan", default="seed-plan.json")
        q.add_argument(
            "--secrets",
            default="/Users/tuananhnguyen/Documents/Project/investigator/.env",
            help="a .env holding SLACK_BOT_TOKEN, JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN",
        )
        if name == "post":
            q.add_argument("--dry", action="store_true")
            q.add_argument("--only", default="")
        if name == "register":
            q.add_argument("--api", default="http://127.0.0.1:8010")
        q.set_defaults(fn=fn)
    q = sub.add_parser("export-demo")
    q.add_argument("--plan", default="seed-plan.json")
    q.add_argument("--samples", default="seed-samples.json")
    q.add_argument("--dry", action="store_true")
    q.set_defaults(fn=cmd_export_demo)
    q = sub.add_parser("notion-plan")
    q.add_argument("--plan", default="seed-plan.json")
    q.add_argument("--out", default=NOTION_PLAN)
    q.add_argument("--workers", type=int, default=4)
    q.set_defaults(fn=cmd_notion_plan)
    for name, fn in (
        ("notion-post", cmd_notion_post),
        ("notion-cleanup", cmd_notion_cleanup),
    ):
        q = sub.add_parser(name)
        q.add_argument(
            "--user",
            default="local",
            help="email of the signed-in account that connected Notion",
        )
        q.add_argument(
            "--token",
            default="",
            help="a Notion token to use instead of the stored connection",
        )
        if name == "notion-post":
            q.add_argument("--pages", default=NOTION_PLAN)
            q.add_argument(
                "--parent", default="", help="a page id or link to hang the seed under"
            )
            q.add_argument("--dry", action="store_true")
        q.set_defaults(fn=fn)
    q = sub.add_parser("run-samples")
    q.add_argument("--samples", default="seed-samples.json")
    q.add_argument("--only", default="")
    q.add_argument("--workers", type=int, default=2)
    q.set_defaults(fn=cmd_run_samples)
    ns = ap.parse_args(argv)
    return int(ns.fn(ns))
