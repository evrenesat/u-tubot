"""HTTP routes behind the phone web UI: sign-in, settings, models, status, jobs and user admin."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from .auth import PairError
from .captions.jobs import JobRefused
from .config import UserConfig
from .models import (
    LoginRequest,
    NewUser,
    PasswordChange,
    PasswordSet,
    ResolveRequest,
    UserPatch,
)
from .videoref import parse_video_ref
from .webauth import SESSION_TOKEN_ID, LoginError, csrf_token

UPDATE_CHECKS_PER_WINDOW = 6
PASSWORD_ATTEMPTS_PER_WINDOW = 5
LANG_MAX_CHARS = 16


@dataclass
class Deps:
    svc: Any
    current_user: Callable
    admin_user: Callable
    ip_of: Callable[[Request], str]
    session_cookie: Callable[[Request], str | None]
    set_session_cookie: Callable[[Response, Request, str], None]
    clear_session_cookie: Callable[[Response, Request], None]
    check_same_origin: Callable[[Request], None]
    check_csrf: Callable[[Request, str], None]
    client_of: Callable[[Request], str]
    mark_origin: Callable[[Request, UserConfig], str]
    note_delivery: Callable[..., None]


def install_web_routes(app: FastAPI, d: Deps) -> None:
    svc = d.svc
    cfg = svc.cfg
    current_user, admin_user = d.current_user, d.admin_user

    def known_user(name: str) -> UserConfig:
        user = svc.auth.user_config(name)
        if user is None:
            raise HTTPException(404, "unknown user")
        return user

    async def fresh_session(request: Request, user: UserConfig) -> JSONResponse:
        """Answer a password change: every session was ended, so a browser gets a new one at once.

        The old cookie must not be refreshed after this (the edge middleware would write it back).
        """
        token = None
        if d.session_cookie(request):
            token = await asyncio.to_thread(
                svc.webauth.create_session,
                user.name,
                d.ip_of(request),
                request.headers.get("user-agent", ""),
                "password",
            )
        request.state.session_refresh = None
        resp = JSONResponse({"ok": True, "csrf": csrf_token(token) if token else None})
        if token:
            d.set_session_cookie(resp, request, token)
        return resp

    # ---- sign-in --------------------------------------------------------------------------

    @app.post("/v1/auth/login")
    async def login(body: LoginRequest, request: Request):
        d.check_same_origin(request)
        ip = d.ip_of(request)
        svc.limiter.check(f"login:{ip}", cfg.security.login_attempts_per_ip_per_min)
        agent = request.headers.get("user-agent", "")
        try:
            if body.token:
                token, user = await asyncio.to_thread(
                    svc.webauth.login_token, body.token, ip, agent
                )
            elif body.username and body.password is not None:
                token, user = await asyncio.to_thread(
                    svc.webauth.login_password, body.username, body.password, ip, agent
                )
            else:
                raise HTTPException(400, "give a username and password, or a token")
        except LoginError as exc:
            resp = JSONResponse({"error": str(exc)}, status_code=exc.status)
            if exc.retry_after:
                resp.headers["Retry-After"] = str(exc.retry_after)
            return resp
        resp = JSONResponse(
            {
                "user": user.name,
                "admin": user.admin,
                "csrf": csrf_token(token),
                "expires_in_s": cfg.security.session_ttl_s,
            }
        )
        d.set_session_cookie(resp, request, token)
        return resp

    @app.post("/v1/auth/logout")
    async def logout(request: Request):
        cookie = d.session_cookie(request)
        if cookie:
            d.check_csrf(request, cookie)
            svc.webauth.end_session(cookie)
        resp = JSONResponse({"ok": True})
        d.clear_session_cookie(resp, request)
        return resp

    @app.get("/v1/auth/session")
    async def session(request: Request, user: UserConfig = Depends(current_user)):
        cookie = d.session_cookie(request)
        bearer = request.headers.get("authorization", "")
        via_cookie = bool(cookie) and not bearer.lower().startswith("bearer ")
        return {
            "user": user.name,
            "admin": user.admin,
            "via": "cookie" if via_cookie else "token",
            "csrf": csrf_token(cookie) if via_cookie and cookie else None,
            "has_password": svc.webauth.has_password(user.name),
        }

    @app.put("/v1/me/password")
    async def change_password(
        body: PasswordChange, request: Request, user: UserConfig = Depends(current_user)
    ):
        svc.limiter.check(f"pw:{user.name}", PASSWORD_ATTEMPTS_PER_WINDOW)
        if svc.webauth.has_password(user.name):
            ok = await asyncio.to_thread(
                svc.webauth.check_password, user.name, body.current_password or ""
            )
            if not ok:
                raise HTTPException(403, "current password is wrong")
        try:
            await asyncio.to_thread(svc.webauth.set_password, user.name, body.new_password)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return await fresh_session(request, user)

    # ---- settings -------------------------------------------------------------------------

    @app.get("/v1/me/settings")
    async def my_settings(user: UserConfig = Depends(current_user)):
        return svc.settings.document(user.name)

    def from_browser(request: Request) -> bool:
        principal = getattr(request.state, "principal", None)
        return principal is not None and principal.token_id == SESSION_TOKEN_ID

    @app.put("/v1/me/settings")
    async def put_my_settings(
        body: dict[str, Any], request: Request, user: UserConfig = Depends(current_user)
    ):
        return await svc.settings.update(
            user.name, body, is_admin=user.admin, require_version=from_browser(request)
        )

    @app.get("/v1/users/{name}/settings")
    async def user_settings(name: str, admin: UserConfig = Depends(admin_user)):
        known_user(name)
        return svc.settings.document(name)

    @app.put("/v1/users/{name}/settings")
    async def put_user_settings(
        name: str, body: dict[str, Any], request: Request, admin: UserConfig = Depends(admin_user)
    ):
        known_user(name)
        return await svc.settings.update(
            name, body, is_admin=True, require_version=from_browser(request)
        )

    # ---- models, status, updates ----------------------------------------------------------

    @app.get("/v1/models")
    async def models(user: UserConfig = Depends(current_user)):
        return await svc.catalog.refresh(force=False, admin=user.admin)

    @app.post("/v1/models/refresh")
    async def models_refresh(user: UserConfig = Depends(current_user)):
        return await svc.catalog.refresh(force=True, admin=user.admin)

    @app.get("/v1/status")
    async def status(user: UserConfig = Depends(current_user)):
        return svc.status.home(user.name)

    @app.get("/v1/updates")
    async def updates(user: UserConfig = Depends(current_user)):
        return await svc.updates.snapshot()

    @app.post("/v1/updates/refresh")
    async def updates_refresh(user: UserConfig = Depends(current_user)):
        svc.limiter.check(f"upd:{user.name}", UPDATE_CHECKS_PER_WINDOW)
        return await svc.updates.snapshot(force=True)

    # ---- TV devices of the signed-in user -------------------------------------------------

    @app.get("/v1/me/devices")
    async def my_devices(user: UserConfig = Depends(current_user)):
        return {"devices": svc.auth.list_devices(user.name)}

    @app.delete("/v1/me/devices/{device_id}")
    async def revoke_my_device(device_id: str, user: UserConfig = Depends(current_user)):
        if not svc.auth.revoke(device_id, user=user.name):
            raise HTTPException(404, "unknown device")
        return {"ok": True}

    @app.post("/v1/me/pair")
    async def pair_my_tv(user: UserConfig = Depends(current_user)):
        try:
            code, ttl = svc.auth.create_pair_code(user.name)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"user": user.name, "code": code, "expires_in_s": ttl}

    # ---- jobs and video references --------------------------------------------------------

    def visible_job(job_id: str, user: UserConfig) -> dict[str, Any]:
        """The job for its owner or an admin; anybody else is told it does not exist."""
        job = svc.jobs.get(job_id)
        if not svc.reports.visible(job, user.name, user.admin):
            raise HTTPException(404, "unknown job")
        return job

    @app.get("/v1/jobs/{job_id}")
    async def job_detail(job_id: str, user: UserConfig = Depends(current_user)):
        return svc.reports.report(visible_job(job_id, user), user.name)

    @app.get("/v1/jobs/{job_id}/transcript.txt")
    async def job_transcript_text(
        job_id: str,
        request: Request,
        lang: str | None = Query(None, max_length=LANG_MAX_CHARS),
        user: UserConfig = Depends(current_user),
    ):
        job = visible_job(job_id, user)
        text = svc.reports.transcript_text(job, lang)
        if text is None:
            raise HTTPException(404, "this job has no transcript text")
        d.note_delivery(
            svc.jobs.events.deliver, job["id"], "transcript_txt", d.client_of(request), user.name
        )
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="transcript-{job["video_id"]}.txt"'
            },
        )

    @app.post("/v1/jobs/{job_id}/cancel")
    async def job_cancel(job_id: str, request: Request, user: UserConfig = Depends(current_user)):
        d.mark_origin(request, user)
        try:
            svc.jobs.cancel(user.name, job_id)
        except JobRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return {"ok": True}

    @app.post("/v1/jobs/{job_id}/retry")
    async def job_retry(job_id: str, request: Request, user: UserConfig = Depends(current_user)):
        d.mark_origin(request, user)
        try:
            svc.jobs.retry(user.name, job_id)
        except JobRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc
        return {"ok": True}

    @app.post("/v1/videos/resolve")
    async def resolve_video(body: ResolveRequest, user: UserConfig = Depends(current_user)):
        video_id = parse_video_ref(body.text)
        if video_id is None:
            raise HTTPException(400, "not a YouTube video id or link")
        return {"video_id": video_id}

    # ---- user administration --------------------------------------------------------------

    @app.get("/v1/users")
    async def users(admin: UserConfig = Depends(admin_user)):
        return {"users": [svc.webauth.describe_user(n) for n in svc.auth.user_names()]}

    @app.post("/v1/users")
    async def create_user(body: NewUser, admin: UserConfig = Depends(admin_user)):
        try:
            await asyncio.to_thread(svc.webauth.create_user, body.name, body.admin, body.password)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return svc.webauth.describe_user(body.name)

    @app.put("/v1/users/{name}")
    async def patch_user(name: str, body: UserPatch, admin: UserConfig = Depends(admin_user)):
        known_user(name)
        if name == admin.name and not body.admin:
            raise HTTPException(409, "you cannot remove your own admin flag")
        try:
            svc.webauth.set_admin(name, body.admin)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return svc.webauth.describe_user(name)

    @app.put("/v1/users/{name}/password")
    async def set_user_password(
        name: str, body: PasswordSet, request: Request, admin: UserConfig = Depends(admin_user)
    ):
        known_user(name)
        try:
            await asyncio.to_thread(svc.webauth.set_password, name, body.password)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        if name == admin.name and d.session_cookie(request):
            return await fresh_session(request, admin)
        return svc.webauth.describe_user(name)
