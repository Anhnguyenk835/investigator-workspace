"""Everything the API and a worker process both need, built once from the settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from investigator.agents.chat import ChatDeps, build_chat_graph
from investigator.agents.investigation import Deps, build_graph
from investigator.auth import AuthService, GoogleOidc, PostgresAuthStore
from investigator.chat import ChatService, PostgresChatStore
from investigator.chat.availability import build as build_availability
from investigator.connectors import SourceConnector
from investigator.connectors.registry import load_connectors
from investigator.demo import DemoCorpus, PostgresDemoStore
from investigator.directory import PostgresDirectoryStore
from investigator.guardrails import (
    BufferedAuditSink,
    GuardedLlm,
    GuardPolicy,
    GuardRuntime,
    PostgresAuditSink,
)
from investigator.guardrails.breaker import PostgresFlagStore
from investigator.guardrails.budget import PostgresUsageStore
from investigator.guardrails.injection.classifier import classify
from investigator.guardrails.pii.aliases import PostgresAliasBook
from investigator.integrations import (
    ClientCredentials,
    OAuthService,
    PostgresCredentialStore,
    TokenCipher,
)
from investigator.investigations import PostgresInvestigationStore
from investigator.investigations.annotations import PostgresAnnotationStore
from investigator.investigations.checkpoint import checkpoint_serde
from investigator.investigations.events import PostgresEventStore
from investigator.jobs import PostgresJobQueue
from investigator.llm import LlmNotConfiguredError, get_llm_client
from investigator.settings import Settings
from investigator.tools import AccessContext

# No login yet: every request is this one local user. Each connector checks that
# user's own connection, so a source they have not connected reports `not_connected`.
LOCAL_USER = "local"


@dataclass
class Runtime:
    store: PostgresInvestigationStore
    access: AccessContext
    oauth: OAuthService
    events: PostgresEventStore
    directory: PostgresDirectoryStore
    queue: PostgresJobQueue
    annotations: PostgresAnnotationStore
    connectors: list[SourceConnector] = field(default_factory=list)
    # None when the LLM gateway is not configured: investigations cannot run.
    graph: Any | None = None
    chat: ChatService | None = None
    guard: GuardRuntime | None = None
    admin_token: str = ""
    auth: AuthService | None = None
    demo: DemoCorpus | None = None


@asynccontextmanager
async def open_runtime(settings: Settings) -> AsyncIterator[Runtime]:
    async with (
        AsyncConnectionPool(
            settings.database_url,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        ) as pool,
        httpx.AsyncClient(timeout=15.0) as http,
    ):
        store = PostgresInvestigationStore(pool)
        await store.setup()
        checkpointer = AsyncPostgresSaver(pool, serde=checkpoint_serde())  # type: ignore[arg-type]
        await checkpointer.setup()
        queue = PostgresJobQueue(pool)
        await queue.setup()
        await store.fail_orphans("This run was lost and could not be resumed.")
        events = PostgresEventStore(pool)
        await events.setup()
        credentials = PostgresCredentialStore(pool)
        await credentials.setup()
        directory = PostgresDirectoryStore(pool)
        await directory.setup()
        chats = PostgresChatStore(pool)
        await chats.setup()
        annotations = PostgresAnnotationStore(pool)
        await annotations.setup()
        auth: AuthService | None = None
        if settings.auth_enabled:
            auth_store = PostgresAuthStore(pool)
            await auth_store.setup()
            web = settings.web_public_url.rstrip("/")
            auth = AuthService(
                auth_store,
                GoogleOidc(
                    settings.google_client_id,
                    settings.google_client_secret,
                    settings.auth_redirect_uri or f"{web}/api/auth/google/callback",
                    http,
                ),
                allowed_domains=settings.auth_allowed_domains,
                allowed_emails=settings.auth_allowed_emails,
                session_days=settings.auth_session_days,
                demo_enabled=settings.demo_enabled,
                demo_hours=settings.demo_session_hours,
                demo_per_ip_hour=settings.demo_sessions_per_ip_hour,
                cookie_secure=settings.auth_cookie_secure or web.startswith("https://"),
                web_url=web,
                origins=frozenset(
                    {
                        web.lower(),
                        *(o.rstrip("/").lower() for o in settings.cors_origins),
                    }
                ),
            )
        audit_store = PostgresAuditSink(pool)
        await audit_store.setup()
        usage = PostgresUsageStore(pool)
        await usage.setup()
        flags = PostgresFlagStore(pool)
        await flags.setup()
        audit = BufferedAuditSink(audit_store)
        audit.start()
        aliases = None
        if settings.guard_alias_secret:  # shared numbering across processes
            aliases = PostgresAliasBook(pool, settings.guard_alias_secret.encode())
            await aliases.setup()
        guard = GuardRuntime(
            GuardPolicy.from_settings(settings), audit, usage, flags, aliases
        )
        oauth = OAuthService(
            store=credentials,
            cipher=TokenCipher(settings.token_encryption_key)
            if settings.token_encryption_key
            else None,
            http=http,
            clients={
                "google": ClientCredentials(
                    settings.google_client_id, settings.google_client_secret
                ),
                "slack": ClientCredentials(
                    settings.slack_client_id, settings.slack_client_secret
                ),
                "atlassian": ClientCredentials(
                    settings.atlassian_client_id, settings.atlassian_client_secret
                ),
                "notion": ClientCredentials(
                    settings.notion_client_id, settings.notion_client_secret
                ),
            },
            api_public_url=settings.api_public_url,
        )
        demo_store = PostgresDemoStore(pool)
        await demo_store.setup()
        demo_corpus = DemoCorpus(demo_store)
        connectors = load_connectors(
            oauth, http, settings, demo_corpus if settings.demo_enabled else None
        )
        access = AccessContext(
            user_id=LOCAL_USER, permitted_sources=frozenset(c.name for c in connectors)
        )
        runtime = Runtime(
            store=store,
            access=access,
            oauth=oauth,
            events=events,
            directory=directory,
            queue=queue,
            annotations=annotations,
            connectors=connectors,
            guard=guard,
            admin_token=settings.guard_admin_token,
            auth=auth,
            demo=demo_corpus,
        )
        try:
            try:
                llm = GuardedLlm(get_llm_client(), guard)
            except LlmNotConfiguredError:
                yield runtime
                return
            guard.classifier = lambda snippet: classify(llm, snippet)
            runtime.graph = build_graph(
                Deps(llm=llm, connectors=connectors, guard=guard), checkpointer
            )
            runtime.chat = ChatService(
                build_chat_graph(ChatDeps(llm=llm, connectors=connectors, guard=guard)),
                chats,
                store,
                access,
                directory,
                demo_max_turns=settings.demo_max_chat_turns,
                availability=build_availability(
                    oauth, demo_corpus, (c.name for c in connectors)
                ),
            )
            yield runtime
        finally:
            await audit.aclose()
