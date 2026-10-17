"""Working on an investigation together: owner, re-run, notes and reviews, export."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from investigator.api.dispatch import actor_of, dispatch, ip_of
from investigator.api.session import principal_of, visible_investigation
from investigator.auth import directory_owner
from investigator.investigations import Investigation
from investigator.investigations.annotations import Annotation, AnnotationKind
from investigator.investigations.export import build_report, to_html, to_markdown

router = APIRouter(tags=["collaboration"])

RUNNING = {"queued", "investigating"}


class SetOwner(BaseModel):
    owner: str | None = Field(default=None, max_length=80)


class NewAnnotation(BaseModel):
    target_id: str = Field(min_length=1, max_length=100)
    kind: AnnotationKind
    text: str = Field(default="", max_length=4000)


async def _record(
    request: Request, investigation_id: UUID, *, write: bool = False
) -> Investigation:
    return await visible_investigation(request, investigation_id, write=write)


def _annotations(request: Request) -> Any:
    store = request.app.state.app.annotations
    if store is None:
        raise HTTPException(503, "Notes are not available.")
    return store


def claim_ids(inv: Investigation) -> set[str]:
    """Everything a person can annotate: each claim has a stable id."""
    groups = (
        inv.findings,
        inv.commitments,
        inv.timeline,
        inv.conflicts,
        inv.gaps,
        inv.actions,
        inv.blockers,
    )
    return {x.id for g in groups for x in g}


@router.patch("/investigations/{investigation_id}", response_model=Investigation)
async def set_owner(
    investigation_id: UUID, body: SetOwner, request: Request
) -> Investigation:
    """Say who is looking after it. A name, not an account: there is no login yet."""
    await _record(request, investigation_id, write=True)
    owner = " ".join((body.owner or "").split()) or None
    await request.app.state.app.store.set_owner(investigation_id, owner)
    return await _record(request, investigation_id)


@router.post(
    "/investigations/{investigation_id}/rerun",
    status_code=202,
    response_model=Investigation,
)
async def rerun(
    investigation_id: UUID, background: BackgroundTasks, request: Request
) -> Investigation:
    """Run it again with the same question and scope. Notes and reviews are kept: they are
    attached to a claim by an id made from its wording, so they show beside the claim when the
    new run states it the same way and are listed apart when it does not."""
    state = request.app.state.app
    record = await _record(request, investigation_id, write=True)
    if state.graph is None:
        raise HTTPException(
            503, "LLM gateway is not configured. Set LITELLM_API_KEY and restart."
        )
    if record.status in RUNNING:
        raise HTTPException(409, "It is already running.")
    run_no = await state.store.next_run(investigation_id)
    await dispatch(
        state,
        background,
        kind="rerun",
        investigation_id=investigation_id,
        run_no=run_no,
        payload={
            "question": record.question,
            "context": record.context.model_dump(mode="json"),
        },
        actor=actor_of(request),
        ip=ip_of(request),
        principal=principal_of(request),
    )
    return await _record(request, investigation_id)


@router.get(
    "/investigations/{investigation_id}/annotations", response_model=list[Annotation]
)
async def list_annotations(
    investigation_id: UUID, request: Request
) -> list[Annotation]:
    await _record(request, investigation_id)
    return await _annotations(request).list(investigation_id)  # type: ignore[no-any-return]


@router.post(
    "/investigations/{investigation_id}/annotations",
    status_code=201,
    response_model=Annotation,
)
async def add_annotation(
    investigation_id: UUID, body: NewAnnotation, request: Request
) -> Annotation:
    record = await _record(request, investigation_id, write=True)
    if body.target_id not in claim_ids(record):
        raise HTTPException(422, "That claim is not part of this investigation.")
    text = body.text.strip()
    if body.kind == "note" and not text:
        raise HTTPException(422, "A note needs some text.")
    author = actor_of(request) or "Someone"
    added: Annotation = await _annotations(request).add(
        investigation_id, body.target_id, body.kind, text, author
    )
    return added


@router.delete(
    "/investigations/{investigation_id}/annotations/{annotation_id}", status_code=204
)
async def delete_annotation(
    investigation_id: UUID, annotation_id: UUID, request: Request
) -> None:
    await _record(request, investigation_id, write=True)
    removed = await _annotations(request).delete(
        investigation_id, annotation_id, actor_of(request) or "Someone"
    )
    if not removed:
        raise HTTPException(404, "Not found, or it was written by someone else.")


@router.get("/investigations/{investigation_id}/export")
async def export(
    investigation_id: UUID, request: Request, format: str = "md"
) -> Response:
    """The investigation as a document: `md` (Markdown), `html` (print it to get a PDF) or `json`."""
    record = await _record(request, investigation_id)
    state = request.app.state.app
    annotations = (
        await state.annotations.list(investigation_id) if state.annotations else []
    )
    directory = (
        await state.directory.load(directory_owner(principal_of(request)))
        if state.directory
        else None
    )
    stem = f"investigation-{str(investigation_id)[:8]}"
    if format == "json":
        return JSONResponse(
            {
                "investigation": record.model_dump(mode="json"),
                "annotations": [a.model_dump(mode="json") for a in annotations],
            },
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'},
        )
    report = build_report(record, annotations, directory)
    if format == "md":
        return Response(
            to_markdown(report),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )
    if format == "html":
        return Response(
            to_html(report),
            media_type="text/html; charset=utf-8",
            headers={"Content-Disposition": f'inline; filename="{stem}.html"'},
        )
    raise HTTPException(422, "format must be md, html or json.")
