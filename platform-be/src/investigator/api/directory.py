"""Customers, projects and people: how cases are narrowed and authors identified."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ValidationError

from investigator.api.session import principal_of
from investigator.auth import directory_owner
from investigator.auth.access import can_edit_directory
from investigator.directory import (
    CustomerInput,
    Directory,
    PersonInput,
    ProjectInput,
    build,
)
from investigator.tools import AccessContext

router = APIRouter(prefix="/directory", tags=["directory"])

INPUTS: dict[str, type[BaseModel]] = {
    "customers": CustomerInput,
    "projects": ProjectInput,
    "people": PersonInput,
}
KIND = {"customers": "customer", "projects": "project", "people": "person"}


def _store(request: Request) -> Any:
    store = request.app.state.app.directory
    if store is None:
        raise HTTPException(503, "The directory is not available.")
    return store


def _owner(request: Request, *, write: bool = False) -> str | None:
    """Whose directory this request works in. The demo's is shared and read-only."""
    p = principal_of(request)
    if write and not can_edit_directory(p):
        raise HTTPException(
            403, "The demo directory is read-only. Sign in to keep your own."
        )
    return directory_owner(p)


def _parse(collection: str, raw: Any) -> BaseModel:
    try:
        return INPUTS[collection].model_validate(raw)
    except ValidationError as exc:
        raise HTTPException(
            422,
            exc.errors(include_url=False, include_context=False, include_input=False),
        ) from exc


def _check_links(directory: Directory, kind: str, data: BaseModel) -> None:
    customer_id = getattr(data, "customer_id", None)
    if (
        kind in ("project", "person")
        and customer_id
        and directory.customer(customer_id) is None
    ):
        raise HTTPException(422, f"Unknown customer: {customer_id}.")


@router.get("")
async def get_directory(request: Request) -> Directory:
    return await _store(request).load(_owner(request))  # type: ignore[no-any-return]


@router.post("/{collection}", status_code=201)
async def create(collection: str, request: Request) -> dict[str, Any]:
    if collection not in INPUTS:
        raise HTTPException(404, "Unknown collection.")
    data = _parse(collection, await request.json())
    store, kind, owner = _store(request), KIND[collection], _owner(request, write=True)
    _check_links(await store.load(owner), kind, data)
    entry = build(kind, data)  # type: ignore[arg-type]
    await store.put(kind, entry, owner)
    return entry.model_dump()


@router.put("/{collection}/{entry_id}")
async def update(collection: str, entry_id: str, request: Request) -> dict[str, Any]:
    if collection not in INPUTS:
        raise HTTPException(404, "Unknown collection.")
    data = _parse(collection, await request.json())
    store, kind, owner = _store(request), KIND[collection], _owner(request, write=True)
    directory: Directory = await store.load(owner)
    existing = {
        "customer": directory.customer(entry_id),
        "project": directory.project(entry_id),
        "person": next((p for p in directory.people if p.id == entry_id), None),
    }[kind]
    if existing is None:
        raise HTTPException(404, "Not found.")
    _check_links(directory, kind, data)
    entry = build(kind, data, entry_id)  # type: ignore[arg-type]
    await store.put(kind, entry, owner)
    return entry.model_dump()


@router.delete("/{collection}/{entry_id}", status_code=204)
async def delete(collection: str, entry_id: str, request: Request) -> None:
    if collection not in INPUTS:
        raise HTTPException(404, "Unknown collection.")
    store, kind, owner = _store(request), KIND[collection], _owner(request, write=True)
    if kind == "customer":
        directory: Directory = await store.load(owner)
        if any(p.customer_id == entry_id for p in directory.projects):
            raise HTTPException(
                409, "This customer still has projects. Remove or move them first."
            )
    if not await store.delete(kind, entry_id, owner):
        raise HTTPException(404, "Not found.")


@router.get("/suggestions/{source}")
async def suggestions(source: str, request: Request) -> dict[str, Any]:
    """What a project could be mapped to in a source (channels, projects, labels, spaces)."""
    state = request.app.state.app
    connector = next((c for c in state.connectors if c.name == source), None)
    if connector is None or not hasattr(connector, "suggestions"):
        raise HTTPException(404, "Unknown source.")
    p = principal_of(request)
    status, options = await connector.suggestions(
        AccessContext(user_id=p.user_id, demo=p.is_demo)
    )
    return {"source": source, "status": status, "options": options}
