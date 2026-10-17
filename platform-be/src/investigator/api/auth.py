"""Sign in with Google, the demo session, and who am I."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from investigator.api.dispatch import ip_of
from investigator.auth import COOKIE, AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _auth(request: Request) -> AuthService | None:
    auth: AuthService | None = getattr(request.app.state.app, "auth", None)
    return auth


def _web(request: Request) -> str:
    auth = _auth(request)
    return auth.web_url if auth else ""


def _set_cookie(
    response: Response, auth: AuthService, token: str, seconds: int
) -> None:
    response.set_cookie(
        COOKIE,
        token,
        max_age=seconds,
        httponly=True,
        samesite="lax",
        secure=auth.cookie_secure,
        path="/",
    )


def _me(request: Request, auth: AuthService | None) -> dict[str, Any]:
    p = getattr(request.state, "principal", None)
    providers = {
        "google": bool(auth and auth.google.configured),
        "demo": bool(auth and auth.demo_enabled),
    }
    if auth is None:
        return {"mode": "disabled", "user": None, "providers": providers}
    if p is None:
        return {"mode": "anonymous", "user": None, "providers": providers}
    return {
        "mode": "demo" if p.is_demo else "user",
        "user": {
            "id": p.user_id,
            "email": p.email,
            "name": p.name,
            "picture": p.picture,
        },
        "providers": providers,
    }


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    return _me(request, _auth(request))


@router.get("/google/start")
async def start(request: Request, next: str | None = None) -> RedirectResponse:
    auth = _auth(request)
    if auth is None:
        raise HTTPException(404, "Sign-in is not enabled.")
    try:
        return RedirectResponse(await auth.begin_login(next), status_code=302)
    except AuthError as exc:
        return RedirectResponse(
            f"{auth.web_url}/login?error={exc.code}", status_code=303
        )


@router.get("/google/callback")
async def callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    auth = _auth(request)
    if auth is None:
        raise HTTPException(404, "Sign-in is not enabled.")
    try:
        user, next_path = await auth.complete_login(state=state, code=code, error=error)
    except AuthError as exc:
        return RedirectResponse(
            f"{auth.web_url}/login?error={exc.code}", status_code=303
        )
    token, seconds = await auth.start_session(
        user, ip_of(request), request.headers.get("user-agent")
    )
    response = RedirectResponse(f"{auth.web_url}{next_path}", status_code=303)
    _set_cookie(response, auth, token, seconds)
    return response


@router.post("/demo")
async def demo(request: Request, response: Response) -> dict[str, Any]:
    auth = _auth(request)
    if auth is None:
        raise HTTPException(404, "Sign-in is not enabled.")
    try:
        user = await auth.start_demo(ip_of(request))
    except AuthError as exc:
        raise HTTPException(
            429 if exc.code == "too_many_demos" else 403, str(exc)
        ) from exc
    token, seconds = await auth.start_session(
        user, ip_of(request), request.headers.get("user-agent")
    )
    _set_cookie(response, auth, token, seconds)
    request.state.principal = await auth.principal(token)
    return _me(request, auth)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    auth = _auth(request)
    if auth is not None:
        await auth.end(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
