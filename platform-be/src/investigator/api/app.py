from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from investigator.agents.investigation import (
    ClarificationResume,
    DraftResume,
    ReviewResume,
)
from investigator.agents.investigation.schemas import CaseContext
from investigator.api.auth import router as auth_router
from investigator.api.chat import router as chat_router
from investigator.api.collab import router as collab_router
from investigator.api.directory import router as directory_router
from investigator.api.dispatch import actor_of, dispatch, ip_of
from investigator.api.events import router as events_router
from investigator.api.integrations import router as integrations_router
from investigator.api.session import (
    principal_of,
    require_session,
    visible_investigation,
)
from investigator.auth import AuthService, directory_owner, owner_for_new, viewer_ids
from investigator.chat import ChatService
from investigator.connectors import SourceConnector
from investigator.demo import DemoCorpus
from investigator.directory import Directory, DirectoryStore
from investigator.guardrails import GuardRuntime
from investigator.guardrails.api import router as guard_router
from investigator.integrations import OAuthService
from investigator.investigations import (
    Investigation,
    InvestigationStore,
)
from investigator.investigations.annotations import AnnotationStore
from investigator.investigations.events import EventStore
from investigator.jobs import JobQueue, JobWorker
from investigator.jobs.handler import RunHandler
from investigator.runtime import open_runtime
from investigator.settings import get_settings
from investigator.tools import AccessContext

# One resume payload per human checkpoint.
RESUME_MODELS: dict[str, type[BaseModel]] = {
    "clarification": ClarificationResume,
    "review": ReviewResume,
    "draft_approval": DraftResume,
}


TICKET_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]+-\d+")


@dataclass
class AppState:
    store: InvestigationStore
    # None when the LLM gateway is not configured: investigations cannot run.
    graph: Any | None
    access: AccessContext
    # None in tests that do not exercise integrations.
    oauth: OAuthService | None = None
    # None in tests that do not exercise progress events.
    events: EventStore | None = None
    # None when the LLM gateway is not configured.
    chat: ChatService | None = None
    directory: DirectoryStore | None = None
    connectors: list[SourceConnector] = field(default_factory=list)
    # None runs investigations inside the request's process (tests, quick local use).
    queue: JobQueue | None = None
    annotations: AnnotationStore | None = None
    # None in tests that do not exercise the guardrails.
    guard: GuardRuntime | None = None
    # None: sign-in is off and every request is the one local user.
    auth: AuthService | None = None
    demo_max_investigations: int = 5
    # The stored demo data, when the demo is on.
    demo: DemoCorpus | None = None
    admin_token: str = ""


class CreateInvestigation(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # Short title shown in lists. Optional: older clients omit it.
    name: str | None = Field(default=None, max_length=120)
    # Optional case scope set by the person starting the investigation.
    customer_id: str | None = None
    project_id: str | None = None
    ticket_ids: list[str] = Field(default_factory=list, max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    sources: list[str] | None = Field(default=None, max_length=20)

    @field_validator("ticket_ids")
    @classmethod
    def _ticket_shape(cls, ids: list[str]) -> list[str]:
        for ticket in ids:
            if not TICKET_ID.fullmatch(ticket):
                raise ValueError(f"{ticket!r} is not a ticket id such as IMPL-482")
        return ids

    @model_validator(mode="after")
    def _dates_in_order(self) -> CreateInvestigation:
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class ResumeInvestigation(BaseModel):
    value: dict[str, Any]


async def _sweep_demo(state: AppState, every: float = 600.0) -> None:
    """Delete what demo visitors left behind once they have been idle for a day."""
    while True:
        await asyncio.sleep(every)
        try:
            await sweep_demo(state)
        except Exception:
            logging.getLogger(__name__).exception("demo cleanup failed")


async def sweep_demo(state: AppState) -> int:
    """One pass of the cleanup. Returns how many demo visitors were removed."""
    if state.auth is None:
        return 0
    ids = await state.auth.idle_demo_users()
    for uid in ids:
        await state.store.delete_owned(str(uid))
        if state.chat is not None:
            await state.chat.forget(str(uid))
    await state.auth.store.delete_users(ids)
    return len(ids)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    async with open_runtime(settings) as rt:
        tasks: list[asyncio.Task[None]] = []
        if rt.graph is not None and settings.embedded_workers > 0:
            handler = RunHandler(rt.graph, rt.store, rt.access, rt.events, rt.directory)
            tasks = [
                asyncio.create_task(
                    JobWorker(
                        rt.queue, handler, lease_s=settings.job_lease_seconds
                    ).run_forever()
                )
                for _ in range(settings.embedded_workers)
            ]
        app.state.app = AppState(
            store=rt.store,
            graph=rt.graph,
            access=rt.access,
            oauth=rt.oauth,
            events=rt.events,
            chat=rt.chat,
            directory=rt.directory,
            connectors=rt.connectors,
            queue=rt.queue,
            annotations=rt.annotations,
            guard=rt.guard,
            auth=rt.auth,
            demo_max_investigations=settings.demo_max_investigations,
            demo=rt.demo if settings.demo_enabled else None,
            admin_token=rt.admin_token,
        )
        if rt.auth is not None and settings.demo_enabled:
            tasks.append(asyncio.create_task(_sweep_demo(app.state.app)))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def _check_case_ids(body: CreateInvestigation, directory: Directory | None) -> None:
    """A customer or project the case names must be one the directory knows."""
    if directory is None or directory.is_empty():
        return  # nothing to check against yet
    if not (body.customer_id or body.project_id):
        return
    project = directory.project(body.project_id) if body.project_id else None
    if body.project_id and project is None:
        raise HTTPException(422, f"Unknown project: {body.project_id}.")
    if body.customer_id and directory.customer(body.customer_id) is None:
        raise HTTPException(422, f"Unknown customer: {body.customer_id}.")
    if (
        project
        and body.customer_id
        and project.customer_id not in (None, body.customer_id)
    ):
        raise HTTPException(422, "That project belongs to a different customer.")


def _state(request: Request) -> AppState:
    state: AppState = request.app.state.app
    return state


def create_app(state: AppState | None = None) -> FastAPI:
    """Pass `state` to skip real Postgres and gateway wiring (tests)."""
    app = FastAPI(
        title="Investigator API",
        lifespan=None if state else _lifespan,
        dependencies=[Depends(require_session)],
    )
    if state:
        app.state.app = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(integrations_router)
    app.include_router(events_router)
    app.include_router(chat_router)
    app.include_router(directory_router)
    app.include_router(collab_router)
    app.include_router(guard_router)

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        return {"ok": True, "llm_configured": _state(request).graph is not None}

    @app.post("/investigations", status_code=202, response_model=Investigation)
    async def create(
        body: CreateInvestigation, background: BackgroundTasks, request: Request
    ) -> Investigation:
        app_state = _state(request)
        if app_state.graph is None:
            raise HTTPException(
                503, "LLM gateway is not configured. Set LITELLM_API_KEY and restart."
            )
        who = principal_of(request)
        if who.is_demo and (
            await app_state.store.count_by_owner(who.user_id)
            >= app_state.demo_max_investigations
        ):
            raise HTTPException(
                429,
                f"The demo allows {app_state.demo_max_investigations} investigations. "
                "Sign in with Google to start more.",
            )
        directory = (
            await app_state.directory.load(directory_owner(who))
            if app_state.directory
            else None
        )
        _check_case_ids(body, directory)
        unknown = sorted(set(body.sources or []) - app_state.access.permitted_sources)
        if unknown:
            raise HTTPException(
                422,
                f"Unknown source: {', '.join(unknown)}. "
                f"Available: {', '.join(sorted(app_state.access.permitted_sources)) or 'none'}.",
            )
        context = CaseContext(**body.model_dump(exclude={"question", "name"}))
        record = await app_state.store.create(
            body.question.strip(),
            context,
            owner_for_new(who),
            name=(body.name or "").strip() or None,
        )
        await dispatch(
            app_state,
            background,
            kind="start",
            investigation_id=record.id,
            run_no=record.run_no,
            payload={
                "question": record.question,
                "context": context.model_dump(mode="json"),
            },
            actor=actor_of(request),
            ip=ip_of(request),
            principal=who,
        )
        return record

    @app.post(
        "/investigations/{investigation_id}/resume",
        status_code=202,
        response_model=Investigation,
    )
    async def resume(
        investigation_id: UUID,
        body: ResumeInvestigation,
        background: BackgroundTasks,
        request: Request,
    ) -> Investigation:
        """Answer the question a paused investigation is waiting on."""
        app_state = _state(request)
        record = await visible_investigation(request, investigation_id, write=True)
        if app_state.graph is None:
            raise HTTPException(
                503, "LLM gateway is not configured. Set LITELLM_API_KEY and restart."
            )
        if record.awaiting is None:
            raise HTTPException(409, "This investigation is not waiting for input.")
        try:
            answer = RESUME_MODELS[record.awaiting].model_validate(body.value)
        except ValidationError as exc:
            raise HTTPException(
                422, exc.errors(include_url=False, include_context=False)
            ) from exc
        # Flip the status first so a second click cannot resume the same pause twice.
        await app_state.store.set_status(investigation_id, "investigating")
        await dispatch(
            app_state,
            background,
            kind="resume",
            investigation_id=investigation_id,
            run_no=record.run_no,
            payload={"resume": answer.model_dump(mode="json")},
            actor=actor_of(request),
            ip=ip_of(request),
            principal=principal_of(request),
        )
        return record.model_copy(
            update={"status": "investigating", "awaiting": None, "pending": None}
        )

    @app.get("/investigations", response_model=list[Investigation])
    async def list_investigations(
        request: Request, limit: int = 50
    ) -> list[Investigation]:
        return await _state(request).store.list(
            min(max(limit, 1), 200), viewer_ids(principal_of(request))
        )

    @app.get("/investigations/{investigation_id}", response_model=Investigation)
    async def get_investigation(
        investigation_id: UUID, request: Request
    ) -> Investigation:
        return await visible_investigation(request, investigation_id)

    return app
