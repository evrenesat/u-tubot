from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from . import appchannel, buildinfo, changelog
from .artifacts import KIND_NAMES, ArtifactCache
from .assess import Assessor
from .auth import CONFIG_TOKEN_ID, Auth, Forbidden, PairError, Principal, Unauthorized
from .captions import events
from .captions.asr import ASRBackend, make_asr
from .captions.jobs import JobQueue
from .captions.pipeline import CaptionPipeline, Downloader
from .captions.report import JobReports
from .classes import bind_class
from .client_captions import ClientCaptions, ClientCaptionsRefused, store_upload
from .config import (
    LANG_CODE_RE,
    TRANSLATE_OFF_VALUES,
    Config,
    UserConfig,
    load_config,
)
from .content import ContentService
from .cuts import CutRefused, CutService
from .db import MAX_CHANNEL_ID_CHARS, Database
from .feature import feature_run
from .inbox import (
    KIND_CAPTIONS,
    KIND_RESEARCH,
    KIND_SUMMARY,
    InboxService,
    thumbnail_for,
)
from .ledger import LedgerService
from .llm import LLMClient
from .media_archive import ENTRY_LIMIT, MediaArchive
from .modelcatalog import ModelCatalog
from .models import (
    AskRequest,
    AssessRequest,
    CaptionsRequest,
    CutChannelMode,
    CutChoiceRequest,
    CutCreateRequest,
    CutPresetSave,
    CutPromptBody,
    DefaultRequest,
    FeedbackRequest,
    ImportRequest,
    InboxIds,
    LedgerReport,
    PairCodeRequest,
    PairRequest,
    PolicyPatch,
    ProviderBody,
    QueryMeta,
    SummaryAdhoc,
)
from .processed import ProcessedService
from .prompts import PANEL_ALIAS, TASK_CUTS, Prompt, PromptError, PromptStore, validate_prompt_set
from .security import (
    PROXY_SECRET_HEADER,
    TAILSCALE_LOGIN_HEADER,
    BodyLimitMiddleware,
    RateLimited,
    RateLimiter,
    client_ip,
    is_https,
    is_loopback,
    origin_allowed,
)
from .settings import SettingsError, SettingsService
from .speech import SpeechError, SpeechService
from .status import StatusService, UpdatesStatus
from .transcribe import TranscribeRefused, Transcription
from .transcripts import Fetcher, TranscriptService
from .usage import METRIC_YOUTUBE_FORBIDDEN, Usage
from .userproviders import UserBudgetError, UserProvider, UserProviders, bind_call
from .videoref import VIDEO_ID_RE
from .voice import VoiceService, install_voice_routes
from .webauth import (
    SESSION_TOKEN_ID,
    VIA_TAILSCALE,
    VIA_WEB_LOGIN,
    WebAuth,
    WebLoginError,
    csrf_valid,
    hash_session,
)
from .webroutes import Deps, install_web_routes
from .youtube import Clock, YoutubeGate
from .youtube_fixtures import OfflineYoutubeFetcher

log = logging.getLogger("utubot.app")
# The shape of what the TV keeps on disk (verdicts, summaries): raise it only when that shape changes, never per deploy
CACHE_SCHEMA = 1
APK_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}\.apk$")
APK_MIME = "application/vnd.android.package-archive"
LANG_RE = LANG_CODE_RE
TRANSLATE_OFF = TRANSLATE_OFF_VALUES


def _saved_preset_doc(p: Prompt) -> dict[str, Any]:
    doc: dict[str, Any] = {"id": p.id, "label": p.label}
    if p.length_min:
        doc["length_min"] = p.length_min
    if p.length_frac:
        doc["length_frac"] = p.length_frac
    return doc


def resolve_translate_to(requested: str | None, default: str) -> str | None:
    """The translation target of a captions job.

    An unset target follows the user's `captions_translate_to`, else `[captions] translate_to` ("en");
    "off"/"none" (or an empty value) keeps the source language instead of translating.
    """
    value = (default if requested is None else requested).strip().lower()
    return None if value in TRANSLATE_OFF else value


WEB_DIR = Path(__file__).parent / "web"
UI_DIR = WEB_DIR / "ui"
UI_TYPES = {
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".json": "application/json",
}
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "x-csrf-token"
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; manifest-src 'self';"
    " img-src 'self' data: https://i.ytimg.com; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; "
    "frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # The phone records the cut description only when the owner taps Speak; the page asks for
    # the microphone then, so this origin must be allowed to.
    "Permissions-Policy": "camera=(), microphone=(self), geolocation=()",
}
RECENT_JOBS_LIMIT = 20
WEB_CLIENT = "Web UI"
TOKEN_CLIENT = "API token"
DEVICE_CLIENT = "device"
JOBS_LIMIT_DEFAULT = 50
JOBS_LIMIT_MAX = 200
# The components the ledger records a failure under. A client-supplied component outside this set is
# folded to "client" so a wrong value cannot pollute the admin page's category breakdown.
LEDGER_COMPONENTS = frozenset(
    {"client", "job", "youtube", "llm", "transcript", "cut", "download", "sync", "assess"}
)


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
    cuts: CutService
    processed: ProcessedService
    inbox: InboxService
    voice: VoiceService
    speech: SpeechService
    gate: YoutubeGate
    transcription: Transcription
    archive: MediaArchive
    limiter: RateLimiter
    webauth: WebAuth
    catalog: ModelCatalog
    settings: SettingsService
    status: StatusService
    updates: UpdatesStatus
    artifacts: ArtifactCache
    ledger: LedgerService
    user_providers: UserProviders
    build: buildinfo.Build = field(default_factory=buildinfo.detect)
    build: buildinfo.Build = field(default_factory=buildinfo.detect)


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
    ledger = LedgerService(db, cfg.ledger.keep_days)
    llm = LLMClient(cfg, transport=llm_transport, db=db)
    gate = YoutubeGate(cfg.youtube, db, clock, ledger=ledger)
    if fetcher is None and cfg.youtube.offline:
        fetcher = OfflineYoutubeFetcher(cfg)
    transcripts = TranscriptService(cfg, db, fetcher, gate)
    prompts = PromptStore(cfg, db, prompt_transport)
    inbox = InboxService(db)
    archive = MediaArchive(cfg, db)
    pipeline = CaptionPipeline(
        cfg,
        db,
        asr or make_asr(cfg.captions),
        llm,
        downloader=downloader,
        gate=gate,
        archive=archive,
    )
    jobs = JobQueue(cfg, db, pipeline, transcripts, ledger=ledger)
    reports = JobReports(cfg, db, jobs, transcripts)
    transcription = Transcription(cfg, transcripts, jobs)
    auth = Auth(cfg, db)
    catalog = ModelCatalog(cfg, db, llm)
    user_providers = UserProviders(db)
    assessor = Assessor(cfg, db, llm, transcripts)
    content = ContentService(cfg, db, llm, transcripts, prompts, transcription)
    return Services(
        cfg=cfg,
        db=db,
        auth=auth,
        llm=llm,
        transcripts=transcripts,
        assessor=assessor,
        prompts=prompts,
        content=content,
        jobs=jobs,
        reports=reports,
        cuts=CutService(cfg, db, llm, transcripts, prompts, jobs, auth, archive, gate, inbox),
        processed=ProcessedService(db, transcripts, prompts),
        inbox=inbox,
        voice=VoiceService(cfg.voice, db, auth),
        speech=SpeechService(cfg, transport=llm_transport),
        gate=gate,
        transcription=transcription,
        archive=archive,
        limiter=RateLimiter(cfg.security.rate_window_s),
        webauth=WebAuth(cfg, db, auth, user_providers, llm.user_usage),
        catalog=catalog,
        settings=SettingsService(cfg, auth, prompts, catalog),
        status=StatusService(cfg, db, gate, llm.usage, transcription.engines),
        updates=UpdatesStatus(cfg, github_transport),
        artifacts=ArtifactCache(db, transcripts, content, assessor, archive),
        ledger=ledger,
        user_providers=user_providers,
    )
    )


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def etag_matches(if_none_match: str, etag: str) -> bool:
    """Whether a client's If-None-Match equals this strong ETag. The list may hold several ETags or
    the wildcard `*`; a weak validator (W/) never matches a strong one."""
    if if_none_match.strip() == "*":
        return True
    wanted = {entry.strip() for entry in if_none_match.split(",")}
    return etag in wanted or ("W/" + etag) in wanted


CLIENT_CAPTIONS_PATH_RE = re.compile(r"^/v1/videos/[^/]+/captions/client$")


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
        try:
            changelog.rebuild(svc.db, svc.build.root)
            if changelog.record_deploy(svc.db, svc.build) and cfg.llm.changelog:
                await changelog.polish_latest_deploy(svc.db, svc.llm, cfg.llm.changelog)
        except Exception:  # a history that cannot be written must not stop the server
            logging.getLogger(__name__).exception("recording the deploy failed")
        svc.jobs.start()
        svc.cuts.start()
        yield
        await svc.cuts.stop()
        await svc.jobs.stop()
        await svc.assessor.drain()
        await svc.speech.aclose()
        await svc.llm.aclose()
        svc.db.close()

    app = FastAPI(
        title="u·tubot",
        version=svc.build.version,
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
    async def _forbidden(_r: Request, exc: Forbidden):
        return error(403, "forbidden")

    @app.exception_handler(UserBudgetError)
    async def _budget(_r: Request, exc: UserBudgetError):
        resp = error(exc.status, str(exc))
        resp.headers["Retry-After"] = str(exc.retry_after_s)
        return resp

    @app.exception_handler(RateLimited)
    async def _limited(_r: Request, exc: RateLimited):
        resp = error(429, "rate limited")
        resp.headers["Retry-After"] = str(exc.retry_after)
        return resp

    @app.exception_handler(CutRefused)
    async def _cut_refused(_r: Request, exc: CutRefused):
        return error(exc.status, exc.message)

    @app.exception_handler(SpeechError)
    async def _speech_error(_r: Request, exc: SpeechError):
        return error(exc.status, exc.message)

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

    def tailscale_identity(request: Request) -> UserConfig | None:
        """The mapped user when Tailscale Serve named one, from the loopback peer only."""
        if not is_loopback(request.client.host if request.client else None):
            return None
        # Requests relayed by the public VPS carry the proxy marker: never a tailnet identity there.
        if request.headers.get(PROXY_SECRET_HEADER):
            return None
        name = cfg.auth.tailscale_user(request.headers.get(TAILSCALE_LOGIN_HEADER))
        return svc.auth.find_user(name) if name else None

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
        if session is not None and cookie is not None:
            if request.method not in SAFE_METHODS:
                check_csrf(request, cookie)
            svc.limiter.check(
                f"ses:{session.user.name}:{session.id_hash[:12]}",
                cfg.security.rate_per_token_per_min,
            )
            request.state.principal = Principal(session.user, SESSION_TOKEN_ID)
            if session.refreshed:
                request.state.session_refresh = cookie
            return session.user
        user = tailscale_identity(request)
        if user is None or request.method not in SAFE_METHODS:
            raise Unauthorized
        token = svc.webauth.create_session(
            user.name,
            ip_of(request),
            request.headers.get("user-agent", ""),
            VIA_TAILSCALE,
        )
        request.state.session_refresh = token
        request.state.session_established = token
        svc.limiter.check(
            f"ses:{user.name}:{hash_session(token)[:12]}", cfg.security.rate_per_token_per_min
        )
        request.state.principal = Principal(user, SESSION_TOKEN_ID)
        return user

    async def authenticated(request: Request, token: str | None) -> UserConfig:
        """Authenticate off the event loop, then bind the class and the caller the route sees.

        The caller (user name and, when they have one, their own upstream) is bound so the LLM router
        and the per-user limits run the request's calls on that person, wherever they execute.
        """
        user = await run_in_threadpool(authenticate, request, token)
        bind_class(user.klass)
        limit = cfg.usage.user_requests_per_min
        if limit > 0:
            svc.limiter.check(f"usr:{user.name}", limit)
        live = svc.user_providers.get_live(user.name)
        bind_call(user.name, UserProvider(*live) if live else None)
        return user

    async def current_user(request: Request) -> UserConfig:
        return await authenticated(request, bearer(request))

    async def current_user_or_query(
        request: Request, token: str | None = Query(None)
    ) -> UserConfig:
        return await authenticated(request, bearer(request) or token)

    async def admin_user(request: Request) -> UserConfig:
        user = await current_user(request)
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

    def attach_run_cost(result: Any, run: Any) -> None:
        """Put the model cost and wall time of one feature call on its response, when tracked."""
        if isinstance(result, dict) and run:
            result["cost_usd"] = round(run.get("cost", 0.0), 5)
            result["elapsed_s"] = run.get("elapsed_s")

    def record_result_failure(
        operation: str, video_id: str, result: Any, request: Request, user: UserConfig
    ) -> None:
        """Record a client-visible failure of an insight/summary/ask (a model or analysis error).

        A transient `delayed`/`needs_transcript` answer is not a failure. A transcript-layer failure
        (`transcript_status == "failed"`) is owned by the job that already recorded it, so it is skipped
        here to avoid counting the same problem twice.
        """
        if not isinstance(result, dict) or result.get("status") != "failed":
            return
        if result.get("transcript_status") == "failed":
            return
        message = result.get("error") or f"{operation} failed"
        try:
            svc.ledger.record(
                "content",
                operation,
                video_id=video_id,
                message=message,
                client=client_of(request),
            )
        except Exception:
            log.warning("could not record a failure in the ledger", exc_info=True)

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

    def max_bytes_for_path(path: str) -> int | None:
        if path == "/v1/speech":
            return cfg.speech.max_upload_bytes
        if CLIENT_CAPTIONS_PATH_RE.match(path):
            return cfg.transcripts.client_max_body_bytes
        return None

    app.add_middleware(
        BodyLimitMiddleware,
        get_max_bytes=lambda: cfg.security.max_body_bytes,
        get_max_bytes_for_path=max_bytes_for_path,
    )

    def qmeta(
        title: str | None = None,
        channel: str | None = None,
        channel_id: str | None = Query(None, max_length=MAX_CHANNEL_ID_CHARS),
        duration_s: int | None = None,
        is_live: bool | None = Query(None),
    ) -> QueryMeta:
        return QueryMeta(
            title=title,
            channel=channel,
            channel_id=channel_id,
            duration_s=duration_s,
            is_live=is_live,
        )

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(
            (WEB_DIR / "index.html").read_text(), headers={"Cache-Control": "no-cache"}
        )

    @app.get("/manifest.webmanifest")
    async def web_manifest():
        """The PWA manifest: installable, and the Android Share button's target (`/shared`)."""
        return Response(
            (WEB_DIR / "manifest.webmanifest").read_text(),
            media_type="application/manifest+json",
            headers={"Cache-Control": "no-cache"},
        )

    @app.get("/sw.js")
    async def service_worker():
        """The service worker that takes a shared YouTube link and opens the cut sheet."""
        return Response(
            (WEB_DIR / "sw.js").read_text(),
            media_type="text/javascript",
            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
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
        return {
            "ok": True,
            "version": svc.build.version,
            "commit": svc.build.commit[:7],
            "cache_schema": CACHE_SCHEMA,
        }

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
        if cfg.voice.enabled:
            out["realtime_url"] = base + "/" + cfg.voice.realtime_path.strip("/")
        if cfg.setup.prompt_set_urls:
            out["prompt_set_urls"] = cfg.setup.prompt_set_urls
        return out

    def voice_me(req: Request, who: UserConfig) -> dict[str, Any]:
        """The `device` and `voice` objects of /v1/me; nothing at all while voice is off."""
        if not cfg.voice.enabled:
            return {}
        device_id = svc.auth.device_id_of(getattr(req.state, "principal", None))
        device = svc.db.one("SELECT device FROM device_tokens WHERE id=?", [device_id])
        return {
            "device": {"id": device_id, "name": device["device"]} if device else None,
            "voice": svc.voice.me(who.name, device_id),
        }

    @app.get("/web-login/{token}")
    async def web_login_redeem(request: Request, token: str):
        """Open this to sign into the web UI in one step: the browser gets the session cookie and
        is sent to the control page. A one-time link from `POST /v1/web-login`; single use, short
        lived, so a copied link is useless after it expires or is opened once.
        """
        svc.limiter.check(
            f"weblogin-open:{ip_of(request)}", cfg.security.web_login_attempts_per_ip_per_min
        )
        try:
            info = await run_in_threadpool(svc.webauth.redeem_web_login, token)
        except WebLoginError as exc:
            log.warning("web sign-in link refused from %s", ip_of(request))
            raise HTTPException(400, "This sign-in link is invalid or expired") from exc
        log.info("web sign-in link used: user=%s device=%s", info.user.name, info.device)
        session_token = await run_in_threadpool(
            svc.webauth.create_session, info.user.name, ip_of(request), info.device, VIA_WEB_LOGIN
        )
        resp = RedirectResponse("/#/home", status_code=302)
        # The link carries the secret in its path: never cached, never leaked through a Referer.
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        set_session_cookie(resp, request, session_token)
        return resp

    @app.get("/v1/me")
    async def me(request: Request, user: UserConfig = Depends(current_user)):
        return {
            "user": user.name,
            "policy": user.policy.model_dump(),
            "admin": user.admin,
            "backend_version": svc.build.version,
            "prime": user.prime,
            "class": user.klass,
            "settings_version": svc.auth.settings_version(user.name)[0],
            "features": {
                "assess": True,
                "insight": True,
                "captions": True,
                "transcribe": True,
                "cuts": svc.cuts.configured,
                "cuts_watched": svc.cuts.watched_available[0],
                "speech": svc.speech.configured,
                "speech_max_s": cfg.speech.max_record_s,
                "voice": cfg.voice.enabled,
            },
            **voice_me(request, user),
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

    @app.get("/v1/me/provider")
    async def me_provider(user: UserConfig = Depends(current_user)):
        """The caller's own upstream, shown without the key: a host and a short key fingerprint, or
        `{"configured": false}` when they have none."""
        return svc.user_providers.describe(user.name) or {"configured": False}

    @app.put("/v1/me/provider")
    async def me_provider_set(body: ProviderBody, user: UserConfig = Depends(current_user)):
        """Store the caller's own upstream. Their next model calls run on it instead of the owner's
        modelgate budget, still under their per-user daily budget and request cap; clearing it returns
        them to the server default."""
        try:
            doc = svc.user_providers.set(user.name, body.base_url, body.api_key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {**doc, "configured": True}

    @app.delete("/v1/me/provider")
    async def me_provider_clear(user: UserConfig = Depends(current_user)):
        if svc.user_providers.remove(user.name):
            return {"ok": True}
        raise HTTPException(404, "no own upstream stored")

    @app.post("/v1/pair")
    async def pair(body: PairRequest, request: Request):
        ip = ip_of(request)
        svc.limiter.check(f"pair:{ip}", cfg.security.pair_attempts_per_ip_per_min)
        try:
            token, name = svc.auth.redeem(body.code, body.device, ip)
        except PairError as exc:
            raise HTTPException(exc.status, str(exc)) from exc
        return {"token": token, "user": name}

    @app.post("/v1/web-login")
    async def web_login(request: Request, user: UserConfig = Depends(current_user)):
        """Ask the backend for a short-lived, single-use sign-in link for this client's browser.

        The caller is any authenticated user (a paired TV has its device token); the link opens on
        the same device and signs the browser in without a password. The device name is recorded on
        the session the link makes, and the request is rate limited per address.
        """
        principal = getattr(request.state, "principal", None)
        if principal is not None and principal.token_id == SESSION_TOKEN_ID:
            raise Forbidden  # only a paired device or token mints a link, never a browser session
        ip = ip_of(request)
        svc.limiter.check(f"weblogin:{ip}", cfg.security.web_login_attempts_per_ip_per_min)
        log.info("web sign-in link issued: user=%s device=%s", user.name, client_of(request))
        token, ttl = svc.webauth.create_web_login(user.name, client_of(request))
        return {"token": token, "expires_in_s": ttl}

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
                    "prime": u.prime,
                    "class": u.klass,
                    "policy": u.policy.model_dump(),
                    "devices": svc.auth.list_devices(name),
                    "usage": svc.llm.user_usage.for_user(name),
                    "provider": svc.user_providers.describe(name) or {"configured": False},
                }
            )
        return {"users": out}

    @app.get("/v1/admin/status")
    async def admin_status(admin: UserConfig = Depends(admin_user)):
        return {
            "youtube": svc.gate.snapshot(),
            "asr": {"engines": svc.transcription.engines.status()},
            "archive": svc.archive.status(),
        }

    @app.get("/v1/admin/archive")
    async def admin_archive(
        video_id: str | None = None,
        limit: int = Query(ENTRY_LIMIT, ge=1, le=ENTRY_LIMIT),
        admin: UserConfig = Depends(admin_user),
    ):
        """The media archive: usage against the quota and the stored entries, newest first."""
        doc = svc.archive.status()
        doc["entries"] = svc.archive.entries(check_video_id(video_id) if video_id else None, limit)
        return doc

    @app.get("/v1/admin/videos/{video_id}/artifacts")
    async def admin_artifacts(video_id: str, admin: UserConfig = Depends(admin_user)):
        """What the backend keeps for one video: per kind rows, bytes and newest write."""
        return svc.artifacts.inventory(check_video_id(video_id))

    @app.delete("/v1/admin/videos/{video_id}/artifacts")
    async def admin_artifacts_purge(
        video_id: str,
        kind: list[str] | None = Query(None),
        admin: UserConfig = Depends(admin_user),
    ):
        """Remove cached artifacts of a video (all kinds but the media archive, or the named ones)."""
        try:
            removed = svc.artifacts.purge(check_video_id(video_id), kind)
        except ValueError as exc:
            raise HTTPException(400, f"kind must be one of: {', '.join(KIND_NAMES)}") from exc
        return {"ok": True, "removed": removed}

    @app.delete("/v1/admin/archive/{video_id}")
    async def admin_archive_remove(video_id: str, admin: UserConfig = Depends(admin_user)):
        """The one admin cleanup: removes a video's archived files and watched caches."""
        video_id = check_video_id(video_id)
        removed, freed = svc.archive.remove(video_id)
        if not removed:
            raise HTTPException(404, "no archived media for this video")
        stages_removed = svc.jobs.pipeline.cache.remove(video_id)
        watched = svc.cuts.clear_watched_cache(video_id)
        return {
            "ok": True,
            "removed": removed,
            "bytes_freed": freed,
            "stage_cache_rows_removed": stages_removed,
            "watched_cache_rows_removed": watched,
        }

    @app.get("/v1/admin/videos/{video_id}/tdt")
    async def admin_tdt(video_id: str, admin: UserConfig = Depends(admin_user)):
        """The newest stored TDT for debugging a watched build (admin only)."""
        doc = svc.cuts.stored_tdt(check_video_id(video_id))
        if doc is None:
            raise HTTPException(404, "no stored watched TDT for this video")
        return doc

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

    @app.get("/v1/admin/features")
    async def admin_features(admin: UserConfig = Depends(admin_user)):
        """Every feature's alias in force, its fallback, the last 7 days of calls/tokens/cost and
        median/p90 time, and the alias list the switch is validated against (`GET /v1/models`)."""
        listing = await svc.catalog.refresh(force=False, admin=True)
        values = [m["value"] for p in listing["providers"] for m in p["models"]]
        return svc.llm.features.page(values)

    @app.put("/v1/admin/features/{feature}")
    async def admin_feature_alias(
        feature: str, body: dict[str, Any], admin: UserConfig = Depends(admin_user)
    ):
        """Point one feature at a modelgate alias. The alias is validated against the model list;
        an unknown one is refused. Applied at once, logged, effective on the next call."""
        store = svc.llm.features
        if feature not in store.feature_names():
            raise HTTPException(400, f"unknown feature {feature!r}")
        listing = await svc.catalog.refresh(force=False, admin=True)
        values = [m["value"] for p in listing["providers"] for m in p["models"]]
        alias = (body.get("alias") or "").strip()
        if not alias:
            raise HTTPException(400, "give an alias")
        if alias not in store.alias_list(values):
            raise HTTPException(400, f"unknown alias {alias!r}: not in the model list")
        return store.set_alias(feature, alias, admin.name)

    @app.delete("/v1/admin/features/{feature}")
    async def admin_feature_reset(feature: str, admin: UserConfig = Depends(admin_user)):
        """Drop the admin override so the feature follows config.toml again."""
        store = svc.llm.features
        if feature not in store.feature_names():
            raise HTTPException(400, f"unknown feature {feature!r}")
        result = store.reset(feature, admin.name)
        if result is None:
            raise HTTPException(404, "no override to reset")
        return result

    @app.get("/v1/admin/ledger")
    async def admin_ledger(
        period_days: int = Query(14, ge=1, le=365),
        limit: int = Query(80, ge=1, le=400),
        admin: UserConfig = Depends(admin_user),
    ):
        """The error ledger: counts per category per day and the newest failures with job links."""
        page = svc.ledger.page(period_days, limit)
        page["youtube_forbidden"] = Usage(svc.db).daily(
            METRIC_YOUTUBE_FORBIDDEN, page["period_days"]
        )
        return page

    @app.post("/v1/admin/ledger/{failure_id}/categorize")
    async def admin_ledger_categorize(
        failure_id: int,
        body: dict[str, Any],
        admin: UserConfig = Depends(admin_user),
    ):
        """Triage: sort one flagged/unknown failure into a real category."""
        category = (body.get("category") or "").strip()
        if not category:
            raise HTTPException(400, "give a category")
        try:
            changed = svc.ledger.reclassify(failure_id, category, admin.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "changed": changed}

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
        with feature_run() as run:
            result = await svc.content.insight(
                user.policy, video_id, meta.as_dict(), wait_ms, user=user.name
            )
        attach_run_cost(result, run)
        if result.get("status") == "ready":
            # A ready research answer is an inbox result.
            meta_dict = meta.as_dict()
            svc.inbox.add(
                user.name,
                video_id,
                KIND_RESEARCH,
                user.policy.language,
                title=meta_dict.get("title"),
                length_s=meta_dict.get("duration_s"),
                thumbnail=thumbnail_for(meta_dict, video_id),
            )
        record_result_failure("insight", video_id, result, request, user)
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
        if resolved.task == TASK_CUTS:
            raise HTTPException(400, "a director's cut preset is not a summary prompt")
        resolved = svc.content.with_user_model(resolved, user.policy)
        with feature_run() as run:
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
        attach_run_cost(result, run)
        if panel and result["status"] == "ready":
            svc.content.schedule_long(user.name, user.policy, video_id, meta.as_dict(), key)
        if not panel and result["status"] == "ready":
            # A requested summary is an inbox result: the viewer can come back to it later.
            meta_dict = meta.as_dict()
            svc.inbox.add(
                user.name,
                video_id,
                KIND_SUMMARY,
                key,
                prompt_key=key,
                title=meta_dict.get("title"),
                length_s=meta_dict.get("duration_s"),
                label=resolved.label,
                thumbnail=thumbnail_for(meta_dict, video_id),
            )
        record_result_failure("summary", video_id, result, request, user)
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
        with feature_run() as run:
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
        attach_run_cost(result, run)
        record_result_failure("summary", video_id, result, request, user)
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
        with feature_run() as run:
            result = await svc.content.ask(
                user.policy, video_id, body.question, meta.as_dict(), body.wait_ms, user=user.name
            )
        attach_run_cost(result, run)
        record_result_failure("ask", video_id, result, request, user)
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
        if body.lang and body.lang != "auto" and not LANG_RE.match(body.lang):
            raise HTTPException(400, "invalid language code")
        default_target = user.policy.captions_translate_to or svc.cfg.captions.translate_to
        translate_to = resolve_translate_to(body.translate_to, default_target)
        if translate_to and not LANG_RE.match(translate_to):
            raise HTTPException(400, "invalid language code")
        job = svc.jobs.enqueue(user.name, video_id, body.lang, translate_to, force=body.force)
        return {"status": job["status"], "job_id": job["id"], "eta_s": None}

    @app.post("/v1/videos/{video_id}/captions/client")
    async def captions_client(
        request: Request,
        video_id: str,
        body: ClientCaptions,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        """Caption tracks the client already holds, stored like a fetch (`origin = client`) so the
        server need not ask YouTube. The reply says whether the upload was kept and why not."""
        check_video_id(video_id)
        if meta.title or meta.channel or meta.duration_s is not None or meta.is_live is not None:
            svc.transcripts.store_meta(video_id, meta.as_dict())
        try:
            return store_upload(svc.transcripts, video_id, body)
        except ClientCaptionsRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc

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
            if status.get("status") == "ready":
                # Done HQ captions are an inbox result.
                meta = svc.transcripts.cached_meta(video_id) or {}
                for track in status["tracks"]:
                    svc.inbox.add(
                        user.name,
                        video_id,
                        KIND_CAPTIONS,
                        track["lang"],
                        title=meta.get("title"),
                        length_s=meta.get("duration_s"),
                        label=track.get("label"),
                        thumbnail=thumbnail_for(meta, video_id),
                    )
        return status

    @app.post("/v1/videos/{video_id}/transcribe")
    async def transcribe(
        request: Request,
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        force: bool = False,
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        mark_origin(request, user)
        try:
            return svc.transcription.request(user.name, video_id, meta.as_dict(), force=force)
        except TranscribeRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.post("/v1/videos/{video_id}/retry")
    async def retry(video_id: str, user: UserConfig = Depends(current_user)):
        """The Retry action: forget every remembered failure of the video, keep stored successes.

        The client asks again right after (summary, insight, verdict); nothing is generated here.
        """
        cleared = svc.artifacts.retry(check_video_id(video_id))
        return {"ok": True, "cleared": cleared}

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

    @app.get("/v1/processed")
    async def processed(
        limit: int = Query(JOBS_LIMIT_DEFAULT, ge=1, le=JOBS_LIMIT_MAX),
        user: UserConfig = Depends(current_user),
    ):
        """The caller's recently processed videos, newest first: captions jobs and cuts per video."""
        return {"videos": svc.processed.recent(user.name, limit)}

    @app.get("/v1/inbox")
    async def inbox(
        limit: int = Query(JOBS_LIMIT_DEFAULT, ge=1, le=JOBS_LIMIT_MAX),
        user: UserConfig = Depends(current_user),
    ):
        """The caller's AI results, newest first, each with its unread flag and how many are unread."""
        items, unread = svc.inbox.list(user.name, limit)
        return {"items": items, "unread": unread}

    @app.post("/v1/inbox/read")
    async def inbox_read(body: InboxIds, user: UserConfig = Depends(current_user)):
        """Mark the given results read (the viewer opened the inbox or picked one)."""
        svc.inbox.mark_read(user.name, body.ids)
        return {"ok": True}

    @app.post("/v1/inbox/read-all")
    async def inbox_read_all(user: UserConfig = Depends(current_user)):
        """Mark every result read: the viewer opened the inbox."""
        svc.inbox.mark_read_all(user.name)
        return {"ok": True}

    @app.post("/v1/inbox/dismiss")
    async def inbox_dismiss(body: InboxIds, user: UserConfig = Depends(current_user)):
        """Remove the given results from the inbox."""
        svc.inbox.dismiss(user.name, body.ids)
        return {"ok": True}

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

    # ---- director's cuts ------------------------------------------------------------------------

    @app.get("/v1/videos/{video_id}/cuts")
    async def cuts_presets(
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        if_none_match: str | None = Header(None),
        user: UserConfig = Depends(current_user),
    ):
        """The cut presets and their state for this video: what the picker on the TV shows.

        The optional video facts (the TV knows the channel id) are stored; the channel's stored
        default decides the picker's mode when the owner has one. The list is immutable per cut key,
        so it carries a strong ETag and a long cache lifetime; a client that serves the menu from it
        and re-validates with If-None-Match gets 304 when nothing changed (offline-first, issue 146).
        """
        check_video_id(video_id)
        if meta.as_dict():
            svc.transcripts.store_meta(video_id, meta.as_dict())
        state = svc.cuts.presets_state(user.name, video_id, meta.channel_id)
        etag = state["etag"]

        if if_none_match is not None and etag_matches(if_none_match, etag):
            return Response(status_code=304, headers={"ETag": etag})

        return JSONResponse(
            state, headers={"Cache-Control": f"max-age={cfg.cuts.cache_max_age_s}", "ETag": etag}
        )

    @app.get("/v1/cut-channels")
    async def cut_channels(user: UserConfig = Depends(current_user)):
        """The owner's per-channel cut defaults: what the phone's channel list shows."""
        return {"channels": svc.cuts.channel_modes(user.name)}

    @app.put("/v1/cut-channels/{channel_id}")
    async def cut_channel_set(
        channel_id: str,
        body: CutChannelMode,
        user: UserConfig = Depends(current_user),
    ):
        """Set the owner's default cut mode for a channel; `mode: null` clears it again."""
        if body.mode is None:
            svc.cuts.clear_channel_mode(user.name, channel_id)
            return {"channel_id": channel_id, "channel_name": body.channel_name, "mode": None}
        return svc.cuts.set_channel_mode(user.name, channel_id, body.mode, body.channel_name)

    @app.delete("/v1/cut-channels/{channel_id}")
    async def cut_channel_clear(channel_id: str, user: UserConfig = Depends(current_user)):
        """Forget a channel's default, so the owner's or the server's default decides again."""
        svc.cuts.clear_channel_mode(user.name, channel_id)
        return {"ok": True}

    @app.post("/v1/videos/{video_id}/cuts")
    async def cuts_create(
        request: Request,
        video_id: str,
        body: CutCreateRequest,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        """Queue a cut: `{preset}`, `{prompt}` or `{await_prompt: true}` (the TV's "Describe on
        phone…"). The video facts the caller knows are stored so the phone queue shows them."""
        check_video_id(video_id)
        mark_origin(request, user)
        if meta.as_dict():
            svc.transcripts.store_meta(video_id, meta.as_dict())
        row = svc.cuts.create(
            user.name,
            video_id,
            source=client_of(request),
            preset=body.preset,
            prompt=body.prompt,
            await_prompt=body.await_prompt,
            mode=body.mode,
            force=body.force,
            channel_id=meta.channel_id,
        )
        return {"request_id": row["id"], "state": row["state"]}

    @app.put("/v1/videos/{video_id}/cut-choice")
    async def cut_choice(
        video_id: str,
        body: CutChoiceRequest,
        user: UserConfig = Depends(current_user),
    ):
        """Remember the cut the viewer chose for this video (a preset, a request, or off)."""
        check_video_id(video_id)
        svc.cuts.choose(
            user.name,
            video_id,
            preset=body.preset,
            request=body.request,
            off=body.off,
        )
        return {"ok": True}

    @app.get("/v1/cuts/{request_id}")
    async def cuts_get(
        request_id: str,
        wait_ms: int | None = None,
        user: UserConfig = Depends(current_user),
    ):
        """One cut request's state, long-polled with `wait_ms`; the cut rides along once ready."""
        return await svc.cuts.get_wait(request_id, user.name, wait_ms)

    @app.get("/v1/cut-requests")
    async def cuts_queue(user: UserConfig = Depends(current_user)):
        """The caller's cut queue, newest first (waiting and building first on the phone)."""
        return {"requests": svc.cuts.queue(user.name)}

    @app.put("/v1/cut-requests/{request_id}")
    async def cuts_fill(
        request_id: str,
        body: CutPromptBody,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        """Fill a waiting request with the typed (or spoken) description; the build starts."""
        if meta.as_dict():
            row = svc.cuts.get(request_id, user.name)
            if row is not None:
                svc.transcripts.store_meta(row["video_id"], meta.as_dict())
        return svc.cuts.fill(request_id, user.name, body.prompt, body.mode, meta.channel_id)

    @app.delete("/v1/cut-requests/{request_id}")
    async def cuts_dismiss(request_id: str, user: UserConfig = Depends(current_user)):
        """Take a request off the phone queue (a building one is stopped)."""
        svc.cuts.dismiss(request_id, user.name)
        return {"ok": True}

    @app.get("/v1/cut-presets")
    async def cut_presets(user: UserConfig = Depends(current_user)):
        """The owner's own cut presets: saved on the phone, listed with their built-ins."""
        return {"presets": [_saved_preset_doc(p) for p in svc.prompts.own_cut_presets(user.name)]}

    @app.post("/v1/cut-presets")
    async def cut_preset_save(body: CutPresetSave, user: UserConfig = Depends(current_user)):
        """Save a description as the owner's preset, so the cut sheet offers it as a chip."""
        try:
            prompt = svc.prompts.save_cut_preset(
                user.name, body.label, body.prompt, body.length_min, body.length_frac
            )
        except PromptError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"preset": _saved_preset_doc(prompt)}

    @app.delete("/v1/cut-presets/{preset_id}")
    async def cut_preset_delete(preset_id: str, user: UserConfig = Depends(current_user)):
        if not svc.prompts.delete_cut_preset(user.name, preset_id):
            raise HTTPException(404, "no saved cut preset with that id")
        return {"ok": True}

    @app.get("/cuts/{request_id}")
    async def cuts_short_url(request_id: str):
        """The QR target of a TV-created request: straight into the phone's cut sheet."""
        return RedirectResponse(f"/#/cuts/{request_id}", status_code=302)

    @app.post("/v1/speech")
    async def speech(request: Request, user: UserConfig = Depends(current_user)):
        """One recording's text: the phone posts audio here, modelgate transcribes it, and
        nothing is stored. Its own upload cap (the body-limit override) is `[speech]
        max_upload_bytes`; the per-user rate limit keeps a phone from retrying in a loop."""
        svc.limiter.check(f"speech:{user.name}", cfg.speech.per_user_per_min)
        try:
            form = await request.form(max_files=1, max_fields=4)
        except Exception as exc:
            raise HTTPException(400, "invalid or too large upload") from exc
        # A large file part spools to a temp file; closing the form unlinks it, so the recording
        # never lingers past the request even while the garbage collector has not run.
        try:
            upload = form.get("audio") or form.get("file")
            if not isinstance(upload, UploadFile):
                raise HTTPException(400, "no recording in the request")
            audio = await upload.read()
            language = form.get("language")
        finally:
            await form.close()
        text = await svc.speech.transcribe(
            audio,
            filename=upload.filename or "recording",
            content_type=upload.content_type or "application/octet-stream",
            language=language if isinstance(language, str) else None,
        )
        return {"text": text}

    @app.post("/v1/feedback")
    async def feedback(body: FeedbackRequest, user: UserConfig = Depends(current_user)):
        svc.db.execute(
            "INSERT INTO feedback(user,video_id,kind,correct,note,created_at) VALUES(?,?,?,?,?,?)",
            [user.name, body.video_id, body.kind, int(body.correct), body.note, time.time()],
        )
        return {"ok": True}

    @app.post("/v1/ledger")
    async def ledger_report(
        body: LedgerReport, request: Request, user: UserConfig = Depends(current_user)
    ):
        """A client (TV, extension) reports one of its own failures to the error ledger.

        The backend categorises it from the message unless the caller supplies a known category hint;
        an unknown category is flagged for triage on the admin page.
        """
        if body.video_id:
            check_video_id(body.video_id)
        component = body.component or "client"
        if component not in LEDGER_COMPONENTS:
            component = "client"
        svc.ledger.record(
            component,
            body.operation,
            video_id=body.video_id,
            message=body.message,
            category=body.category,
            detail=body.detail,
            client=client_of(request),
        )
        return {"ok": True}

    deps = Deps(
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
    )
    install_web_routes(app, deps)
    install_voice_routes(app, deps)
    return app


def app_factory() -> FastAPI:
    return create_app()
