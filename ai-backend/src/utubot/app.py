from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)

from . import __version__, appchannel
from .assess import Assessor
from .auth import CONFIG_TOKEN_ID, Auth, Forbidden, PairError, Principal, Unauthorized
from .captions import events
from .captions.asr import ASRBackend, make_asr
from .captions.jobs import JobQueue
from .captions.pipeline import CaptionPipeline, Downloader
from .captions.report import JobReports
from .config import Config, UserConfig, load_config
from .content import ContentService
from .db import Database
from .llm import LLMClient
from .modelcatalog import ModelCatalog
from .models import (
    AskRequest,
    AssessRequest,
    CaptionsRequest,
    DefaultRequest,
    FeedbackRequest,
    ImportRequest,
    PairCodeRequest,
    PairRequest,
    PolicyPatch,
    QueryMeta,
    SummaryAdhoc,
)
from .prompts import PANEL_ALIAS, Prompt, PromptError, PromptStore, validate_prompt_set
from .security import (
    PROXY_SECRET_HEADER,
    BodyLimitMiddleware,
    RateLimited,
    RateLimiter,
    client_ip,
    is_https,
    origin_allowed,
)
from .settings import SettingsError, SettingsService
from .status import StatusService, UpdatesStatus
from .transcribe import TranscribeRefused, Transcription
from .transcripts import Fetcher, TranscriptService
from .videoref import VIDEO_ID_RE
from .webauth import SESSION_TOKEN_ID, WebAuth, csrf_valid
from .webroutes import Deps, install_web_routes
from .youtube import Clock, YoutubeGate

log = logging.getLogger("utubot.app")
APK_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}\.apk$")
APK_MIME = "application/vnd.android.package-archive"
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
WEB_DIR = Path(__file__).parent / "web"
UI_DIR = WEB_DIR / "ui"
UI_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
RECENT_JOBS_LIMIT = 20
WEB_CLIENT = "Web UI"
TOKEN_CLIENT = "API token"
DEVICE_CLIENT = "device"
JOBS_LIMIT_DEFAULT = 50
JOBS_LIMIT_MAX = 200


@dataclass
class Services:
    cfg: Config
    db: Database
    auth: Auth
    llm: LLMClient
    transcripts: TranscriptService
    assessor: Assessor
    prompts: PromptStore
    content: ContentService
    jobs: JobQueue
    reports: JobReports
    gate: YoutubeGate
    transcription: Transcription
    limiter: RateLimiter
    webauth: WebAuth
    catalog: ModelCatalog
    settings: SettingsService
    status: StatusService
    updates: UpdatesStatus


def build_services(
    cfg: Config,
    *,
    llm_transport: httpx.AsyncBaseTransport | None = None,
    fetcher: Fetcher | None = None,
    asr: ASRBackend | None = None,
    downloader: Downloader | None = None,
    prompt_transport: httpx.AsyncBaseTransport | None = None,
    clock: Clock | None = None,
    github_transport: httpx.AsyncBaseTransport | None = None,
) -> Services:
    db = Database(cfg.db_path)
    llm = LLMClient(cfg, transport=llm_transport, db=db)
    gate = YoutubeGate(cfg.youtube, db, clock)
    transcripts = TranscriptService(cfg, db, fetcher, gate)
    prompts = PromptStore(cfg, db, prompt_transport)
    pipeline = CaptionPipeline(
        cfg, db, asr or make_asr(cfg.captions), llm, downloader=downloader, gate=gate
    )
    jobs = JobQueue(cfg, db, pipeline, transcripts)
    reports = JobReports(cfg, db, jobs, transcripts)
    transcription = Transcription(cfg, transcripts, jobs)
    auth = Auth(cfg, db)
    catalog = ModelCatalog(cfg, db, llm)
    return Services(
        cfg=cfg,
        db=db,
        auth=auth,
        llm=llm,
        transcripts=transcripts,
        assessor=Assessor(cfg, db, llm, transcripts),
        prompts=prompts,
        content=ContentService(cfg, db, llm, transcripts, prompts, transcription, catalog),
        jobs=jobs,
        reports=reports,
        gate=gate,
        transcription=transcription,
        limiter=RateLimiter(cfg.security.rate_window_s),
        webauth=WebAuth(cfg, db, auth),
        catalog=catalog,
        settings=SettingsService(cfg, auth, prompts, catalog),
        status=StatusService(cfg, db, gate, llm.usage, transcription.engines),
        updates=UpdatesStatus(cfg, github_transport),
    )


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


async def catalog_refresh_loop(svc: Services) -> None:
    """Refetch the providers' stale model lists in the background (`models.refresh_interval_s`).

    Keeps newly exposed models arriving on their own, without anybody opening the models page. A
    provider failure is recorded in the listing (`ok:false`); the next interval tries again.
    """
    while True:
        await asyncio.sleep(svc.cfg.models.refresh_interval_s)
        try:
            await svc.catalog.refresh(force=False)
        except Exception:  # noqa: BLE001 - the loop must survive any single failed sweep
            pass


def check_video_id(video_id: str) -> str:
    if not VIDEO_ID_RE.match(video_id):
        raise HTTPException(400, "invalid video id")
    return video_id


def create_app(
    cfg: Config | None = None, services: Services | None = None, **kwargs: Any
) -> FastAPI:
    cfg = cfg or load_config()
    svc = services or build_services(cfg, **kwargs)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        svc.jobs.start()
        refresh = asyncio.create_task(catalog_refresh_loop(svc))
        yield
        refresh.cancel()
        with suppress(asyncio.CancelledError):
            await refresh
        await svc.jobs.stop()
        await svc.assessor.drain()
        await svc.llm.aclose()
        svc.db.close()

    app = FastAPI(
        title="u·tubot",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.svc = svc

    @app.exception_handler(Unauthorized)
    async def _unauth(_r: Request, _e: Unauthorized):
        return error(401, "unauthorized")

    @app.exception_handler(Forbidden)
    async def _forbidden(_r: Request, _e: Forbidden):
        return error(403, "forbidden")

    @app.exception_handler(RateLimited)
    async def _limited(_r: Request, exc: RateLimited):
        resp = error(429, "rate limited")
        resp.headers["Retry-After"] = str(exc.retry_after)
        return resp

    @app.exception_handler(SettingsError)
    async def _settings(_r: Request, exc: SettingsError):
        return JSONResponse({"error": exc.message, **exc.extra}, status_code=exc.status)

    @app.exception_handler(HTTPException)
    async def _http(_r: Request, exc: HTTPException):
        return error(exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError):
        return error(
            400,
            "invalid request: "
            + "; ".join(f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()),
        )

    def bearer(request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            return header[7:].strip()
        return None

    def ip_of(request: Request) -> str:
        header = cfg.security.client_ip_header
        return client_ip(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            cfg.security.trusted_proxies,
            header_value=request.headers.get(header) if header else None,
            presented_secret=request.headers.get(PROXY_SECRET_HEADER),
            expected_secret=cfg.client_ip_secret() if header else None,
        )

    def session_cookie(request: Request) -> str | None:
        return request.cookies.get(cfg.security.session_cookie) or None

    def request_https(request: Request) -> bool:
        return is_https(
            request.url.scheme,
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-proto"),
            cfg.security.trusted_proxies,
        )

    def set_session_cookie(response: Response, request: Request, token: str) -> None:
        response.set_cookie(
            cfg.security.session_cookie,
            token,
            max_age=cfg.security.session_ttl_s,
            path="/",
            httponly=True,
            secure=request_https(request),
            samesite="lax",
        )

    def clear_session_cookie(response: Response, request: Request) -> None:
        response.delete_cookie(
            cfg.security.session_cookie,
            path="/",
            httponly=True,
            secure=request_https(request),
            samesite="lax",
        )

    def sets_session_cookie(response: Response) -> bool:
        """A handler that already issued or cleared the session cookie owns it (see password change)."""
        prefix = cfg.security.session_cookie + "="
        return any(v.startswith(prefix) for v in response.headers.getlist("set-cookie"))

    def check_same_origin(request: Request) -> None:
        """A browser `Origin` header, when sent, must name this server."""
        origin = request.headers.get("origin")
        if origin is None:
            return
        hosts = [request.headers.get("host", ""), urlsplit(cfg.server.public_base_url).netloc]
        if not origin_allowed(origin, hosts):
            raise HTTPException(403, "cross-origin request refused")

    def check_csrf(request: Request, cookie: str) -> None:
        if not csrf_valid(cookie, request.headers.get(CSRF_HEADER)):
            raise HTTPException(403, "csrf token missing or wrong")
        check_same_origin(request)

    def authenticate(request: Request, token: str | None) -> UserConfig:
        if token:
            principal = svc.auth.resolve(token)
            svc.limiter.check(
                f"tok:{principal.user.name}:{principal.token_id}",
                cfg.security.rate_per_token_per_min,
            )
            request.state.principal = principal
            return principal.user
        cookie = session_cookie(request)
        session = svc.webauth.resolve_session(cookie)
        if session is None or cookie is None:
            raise Unauthorized
        if request.method not in SAFE_METHODS:
            check_csrf(request, cookie)
        svc.limiter.check(
            f"ses:{session.user.name}:{session.id_hash[:12]}", cfg.security.rate_per_token_per_min
        )
        request.state.principal = Principal(session.user, SESSION_TOKEN_ID)
        if session.refreshed:
            request.state.session_refresh = cookie
        return session.user

    def current_user(request: Request) -> UserConfig:
        return authenticate(request, bearer(request))

    def current_user_or_query(request: Request, token: str | None = Query(None)) -> UserConfig:
        return authenticate(request, bearer(request) or token)

    def admin_user(request: Request) -> UserConfig:
        user = authenticate(request, bearer(request))
        if not user.admin:
            raise Forbidden
        return user

    def client_of(request: Request) -> str:
        """Who is calling, as the job log names it: a paired device by its name, the web UI, or a token."""
        principal = getattr(request.state, "principal", None)
        if principal is None:
            return "unknown"
        if principal.token_id == SESSION_TOKEN_ID:
            return WEB_CLIENT
        if principal.token_id == CONFIG_TOKEN_ID:
            return TOKEN_CLIENT
        row = svc.db.one("SELECT device FROM device_tokens WHERE id=?", [principal.token_id])
        return row["device"] if row else DEVICE_CLIENT

    def mark_origin(request: Request, user: UserConfig) -> str:
        """Tell the job log who is behind this request (read when the request queues a job)."""
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        client = client_of(request)
        events.set_origin(events.Origin(client, user.name, f"{request.method} {path}"))
        return client

    def note_delivery(record, *args, **kwargs) -> None:
        """Log that a client fetched a job's result; never lets the log break the response."""
        try:
            record(*args, **kwargs)
        except Exception:
            log.warning("could not record a delivery", exc_info=True)

    def note_transcript_use(request: Request, user: UserConfig, video_id: str, result, via: str):
        if isinstance(result, dict) and result.get("status") == "ready":
            note_delivery(
                svc.jobs.record_transcript_delivery,
                video_id,
                via,
                client_of(request),
                user.name,
            )
        return result

    @app.middleware("http")
    async def edge(request: Request, call_next):
        try:
            svc.limiter.check(f"ip:{ip_of(request)}", cfg.security.rate_per_ip_per_min)
            response = await call_next(request)
        except RateLimited as exc:
            response = error(429, "rate limited")
            response.headers["Retry-After"] = str(exc.retry_after)
        response.headers.update(SECURITY_HEADERS)
        if request.url.path.startswith("/v1/"):
            response.headers.setdefault("Cache-Control", "no-store")
        refresh = getattr(request.state, "session_refresh", None)
        if refresh and not sets_session_cookie(response):
            set_session_cookie(response, request, refresh)
        return response

    app.add_middleware(BodyLimitMiddleware, get_max_bytes=lambda: cfg.security.max_body_bytes)

    def qmeta(
        title: str | None = None, channel: str | None = None, duration_s: int | None = None
    ) -> QueryMeta:
        return QueryMeta(title=title, channel=channel, duration_s=duration_s)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(
            (WEB_DIR / "index.html").read_text(), headers={"Cache-Control": "no-cache"}
        )

    @app.get("/ui/{path:path}")
    async def ui_file(path: str):
        root = UI_DIR.resolve()
        try:
            target = (UI_DIR / path).resolve()
            found = root in target.parents and target.is_file()
        except (ValueError, OSError):
            found = False
        media = UI_TYPES.get(target.suffix) if found else None
        if media is None:
            raise HTTPException(404, "not found")
        return FileResponse(target, media_type=media, headers={"Cache-Control": "no-cache"})

    @app.get("/v1/health")
    async def health():
        return {"ok": True, "version": __version__}

    @app.get("/setup.json")
    async def setup():
        base = cfg.server.public_base_url.rstrip("/")
        out = {
            "utubot_setup": 1,
            "name": cfg.setup.name,
            "backend_url": base,
            "update_url": f"{base}/app/update.json",
            "pairing": cfg.setup.pairing,
            "defaults": cfg.setup.defaults.model_dump(),
        }
        if cfg.setup.prompt_set_urls:
            out["prompt_set_urls"] = cfg.setup.prompt_set_urls
        return out

    @app.get("/v1/me")
    async def me(user: UserConfig = Depends(current_user)):
        return {
            "user": user.name,
            "policy": user.policy.model_dump(),
            "admin": user.admin,
            "settings_version": svc.auth.settings_version(user.name)[0],
            "features": {
                "assess": True,
                "insight": True,
                "captions": True,
                "transcribe": True,
            },
        }

    @app.put("/v1/me/policy")
    async def me_policy(body: PolicyPatch, user: UserConfig = Depends(current_user)):
        if "models" in body.root and not user.admin:
            raise HTTPException(
                403, "models are set with PUT /v1/me/settings, which checks them against the list"
            )
        try:
            return svc.auth.set_policy(user.name, body.root).model_dump()
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.post("/v1/pair")
    async def pair(body: PairRequest, request: Request):
        ip = ip_of(request)
        svc.limiter.check(f"pair:{ip}", cfg.security.pair_attempts_per_ip_per_min)
        try:
            token, name = svc.auth.redeem(body.code, body.device, ip)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"token": token, "user": name}

    @app.post("/v1/admin/pair")
    async def admin_pair(body: PairCodeRequest, admin: UserConfig = Depends(admin_user)):
        try:
            code, ttl = svc.auth.create_pair_code(body.user)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"user": body.user, "code": code, "expires_in_s": ttl}

    @app.get("/v1/admin/users")
    async def admin_users(admin: UserConfig = Depends(admin_user)):
        out = []
        for name in svc.auth.user_names():
            u = svc.auth.user_config(name)
            out.append(
                {
                    "name": name,
                    "admin": u.admin,
                    "policy": u.policy.model_dump(),
                    "devices": svc.auth.list_devices(name),
                }
            )
        return {"users": out}

    @app.get("/v1/admin/status")
    async def admin_status(admin: UserConfig = Depends(admin_user)):
        return {
            "youtube": svc.gate.snapshot(),
            "asr": {"engines": svc.transcription.engines.status()},
        }

    @app.delete("/v1/admin/devices/{device_id}")
    async def admin_revoke(device_id: str, admin: UserConfig = Depends(admin_user)):
        if not svc.auth.revoke(device_id):
            raise HTTPException(404, "unknown device")
        return {"ok": True}

    @app.put("/v1/admin/users/{name}/policy")
    async def admin_policy(name: str, body: PolicyPatch, admin: UserConfig = Depends(admin_user)):
        try:
            return svc.auth.set_policy(name, body.root).model_dump()
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    @app.get("/app/update.json")
    async def app_update():
        path = cfg.app_dir / "update.json"
        if not path.is_file():
            raise HTTPException(404, "no update published")
        return FileResponse(path, media_type="application/json")

    @app.get("/app/info.json")
    async def app_info():
        return appchannel.public_info(cfg)

    @app.get("/app/latest/{abi}.apk")
    async def app_latest(abi: str):
        latest = appchannel.load_latest(cfg)
        entry = (latest or {}).get("files", {}).get(abi)
        if abi not in appchannel.ABIS or not entry or not APK_RE.match(entry["file"]):
            raise HTTPException(404, "not found")
        return RedirectResponse(cfg.server.download_url(entry["file"]), status_code=302)

    @app.get("/app/{filename}")
    async def app_file(filename: str):
        if not APK_RE.match(filename):
            raise HTTPException(404, "not found")
        path = cfg.app_dir / filename
        if not path.is_file():
            raise HTTPException(404, "not found")
        return FileResponse(path, media_type=APK_MIME)

    @app.post("/v1/assess")
    async def assess(body: AssessRequest, user: UserConfig = Depends(current_user)):
        limit = cfg.assess.max_videos_per_request
        if len(body.videos) > limit:
            raise HTTPException(400, f"at most {limit} videos per request")
        for v in body.videos:
            check_video_id(v.video_id)
        wait = cfg.assess.default_wait_ms if body.wait_ms is None else body.wait_ms
        results = await svc.assessor.assess(user.name, user.policy, body.videos, wait)
        return {"results": [r.model_dump() for r in results]}

    @app.get("/v1/videos/{video_id}/insight")
    async def insight(
        request: Request,
        video_id: str,
        wait_ms: int | None = None,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        result = await svc.content.insight(
            user.policy, video_id, meta.as_dict(), wait_ms, user=user.name
        )
        return note_transcript_use(request, user, video_id, result, "insight")

    @app.get("/v1/prompts")
    async def prompts_list(user: UserConfig = Depends(current_user)):
        return svc.prompts.describe(user.name)

    @app.get("/v1/prompts/sets/{set_id}")
    async def prompts_get(set_id: str, user: UserConfig = Depends(current_user)):
        found = svc.prompts.get_set(user.name, set_id)
        if not found:
            raise HTTPException(404, "unknown prompt set")
        return found[0].model_dump()

    @app.post("/v1/prompts/import")
    async def prompts_import(body: ImportRequest, user: UserConfig = Depends(current_user)):
        try:
            pset = await svc.prompts.import_url(user.name, body.url)
        except PromptError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**pset.model_dump(), "source_url": body.url}

    @app.post("/v1/prompts/validate")
    async def prompts_validate(body: dict[str, Any], user: UserConfig = Depends(current_user)):
        try:
            pset = validate_prompt_set(body)
        except PromptError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "id": pset.id, "name": pset.name, "prompts": len(pset.prompts)}

    @app.post("/v1/prompts/refresh")
    async def prompts_refresh(user: UserConfig = Depends(current_user)):
        return {"refreshed": await svc.prompts.refresh_all(user.name)}

    @app.put("/v1/prompts/sets/{set_id}")
    async def prompts_put(
        set_id: str, body: dict[str, Any], user: UserConfig = Depends(current_user)
    ):
        try:
            pset = validate_prompt_set(body)
            if pset.id != set_id:
                raise PromptError("set id in body does not match the URL")
            svc.prompts.save_set(user.name, pset, source_url=None)
        except PromptError as exc:
            raise HTTPException(400, str(exc)) from exc
        return pset.model_dump()

    @app.delete("/v1/prompts/sets/{set_id}")
    async def prompts_delete(set_id: str, user: UserConfig = Depends(current_user)):
        try:
            if not svc.prompts.delete_set(user.name, set_id):
                raise HTTPException(404, "unknown prompt set")
        except PromptError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True}

    @app.put("/v1/prompts/default")
    async def prompts_default(body: DefaultRequest, user: UserConfig = Depends(current_user)):
        try:
            svc.prompts.set_default(user.name, body.key)
        except PromptError as exc:
            raise HTTPException(404, str(exc)) from exc
        svc.auth.touch_settings(user.name)
        return {"default": body.key}

    @app.put("/v1/prompts/panel-default")
    async def prompts_panel_default(body: DefaultRequest, user: UserConfig = Depends(current_user)):
        try:
            svc.prompts.set_panel_default(user.name, body.key)
        except PromptError as exc:
            raise HTTPException(404, str(exc)) from exc
        svc.auth.touch_settings(user.name)
        return {"panel_default": body.key}

    @app.get("/v1/videos/{video_id}/summary")
    async def summary(
        request: Request,
        video_id: str,
        prompt: str | None = None,
        wait_ms: int | None = None,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        panel = prompt == PANEL_ALIAS
        if panel:
            key = svc.prompts.panel_key(user.name)
        else:
            key = prompt or svc.prompts.default_key(user.name)
        resolved = svc.prompts.resolve(user.name, key)
        if resolved is None:
            raise HTTPException(404, f"unknown prompt {key}")
        resolved = svc.content.with_user_model(resolved, user.policy)
        result = await svc.content.summary(
            user.policy,
            video_id,
            resolved,
            key,
            meta.as_dict(),
            wait_ms,
            user=user.name,
            passive=panel,
        )
        if panel and result["status"] == "ready":
            svc.content.schedule_long(user.name, user.policy, video_id, meta.as_dict(), key)
        return note_transcript_use(
            request, user, video_id, result, "summary_panel" if panel else "summary"
        )

    @app.post("/v1/videos/{video_id}/summary")
    async def summary_adhoc(
        request: Request,
        video_id: str,
        body: SummaryAdhoc,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        try:
            adhoc = Prompt(
                id="adhoc",
                label="adhoc",
                system=body.system or "",
                template=body.prompt_text,
                max_tokens=body.max_tokens or 700,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        adhoc = svc.content.with_user_model(adhoc, user.policy)
        result = await svc.content.summary(
            user.policy,
            video_id,
            adhoc,
            "adhoc",
            meta.as_dict(),
            body.wait_ms,
            adhoc=True,
            user=user.name,
        )
        return note_transcript_use(request, user, video_id, result, "summary")

    @app.post("/v1/videos/{video_id}/ask")
    async def ask(
        request: Request,
        video_id: str,
        body: AskRequest,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        result = await svc.content.ask(
            user.policy, video_id, body.question, meta.as_dict(), body.wait_ms, user=user.name
        )
        return note_transcript_use(request, user, video_id, result, "answer")

    @app.post("/v1/videos/{video_id}/captions")
    async def captions_queue(
        request: Request,
        video_id: str,
        body: CaptionsRequest | None = None,
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        body = body or CaptionsRequest()
        for lang in (body.lang, body.translate_to):
            if lang and lang != "auto" and not LANG_RE.match(lang):
                raise HTTPException(400, "invalid language code")
        job = svc.jobs.enqueue(user.name, video_id, body.lang, body.translate_to)
        return {"status": job["status"], "job_id": job["id"], "eta_s": None}

    @app.get("/v1/videos/{video_id}/captions")
    async def captions_status(
        request: Request, video_id: str, user: UserConfig = Depends(current_user)
    ):
        check_video_id(video_id)
        status = svc.jobs.status(video_id)
        if status["tracks"]:
            note_delivery(
                svc.jobs.record_captions_delivery,
                video_id,
                [track["lang"] for track in status["tracks"]],
                "captions_status",
                client_of(request),
                user.name,
            )
        return status

    @app.post("/v1/videos/{video_id}/transcribe")
    async def transcribe(
        request: Request,
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        try:
            return svc.transcription.request(user.name, video_id, meta.as_dict())
        except TranscribeRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/v1/videos/{video_id}/transcript")
    async def transcript_status(
        request: Request,
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        out = svc.transcription.status(video_id, user.name, meta.as_dict())
        if out.get("transcript_status") == "ok" and out.get("source") == "asr":
            note_delivery(
                svc.jobs.record_transcript_delivery,
                video_id,
                "transcript_status",
                client_of(request),
                user.name,
            )
        return out

    @app.get("/v1/jobs")
    async def jobs_list(
        limit: int = Query(JOBS_LIMIT_DEFAULT, ge=1, le=JOBS_LIMIT_MAX),
        user: UserConfig = Depends(current_user),
    ):
        return {"jobs": svc.jobs.listing(user.name, limit)}

    @app.get("/v1/captions/jobs")
    async def captions_jobs(user: UserConfig = Depends(current_user)):
        return {"jobs": svc.jobs.recent(user.name, RECENT_JOBS_LIMIT)}

    @app.get("/v1/videos/{video_id}/captions/{lang}.vtt")
    async def captions_vtt(
        request: Request,
        video_id: str,
        lang: str,
        user: UserConfig = Depends(current_user_or_query),
    ):
        check_video_id(video_id)
        row = svc.db.one("SELECT vtt FROM captions WHERE video_id=? AND lang=?", [video_id, lang])
        if not row:
            raise HTTPException(404, "no such track")
        note_delivery(
            svc.jobs.record_captions_delivery,
            video_id,
            [lang],
            "vtt",
            client_of(request),
            user.name,
            bytes=len(row["vtt"].encode()),
        )
        return PlainTextResponse(row["vtt"], media_type="text/vtt")

    @app.post("/v1/feedback")
    async def feedback(body: FeedbackRequest, user: UserConfig = Depends(current_user)):
        svc.db.execute(
            "INSERT INTO feedback(user,video_id,kind,correct,note,created_at) VALUES(?,?,?,?,?,?)",
            [user.name, body.video_id, body.kind, int(body.correct), body.note, time.time()],
        )
        return {"ok": True}

    install_web_routes(
        app,
        Deps(
            svc=svc,
            current_user=current_user,
            admin_user=admin_user,
            ip_of=ip_of,
            session_cookie=session_cookie,
            set_session_cookie=set_session_cookie,
            clear_session_cookie=clear_session_cookie,
            check_same_origin=check_same_origin,
            check_csrf=check_csrf,
            client_of=client_of,
            mark_origin=mark_origin,
            note_delivery=note_delivery,
        ),
    )
    return app


def app_factory() -> FastAPI:
    return create_app()
