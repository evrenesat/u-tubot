from __future__ import annotations

import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)

from . import __version__, appchannel
from .assess import Assessor
from .auth import Auth, Forbidden, PairError, Unauthorized
from .captions.asr import ASRBackend, make_asr
from .captions.jobs import JobQueue
from .captions.pipeline import CaptionPipeline, Downloader
from .config import Config, UserConfig, load_config
from .content import ContentService
from .db import Database
from .llm import LLMClient
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
from .security import BodyLimitMiddleware, RateLimited, RateLimiter, client_ip
from .transcribe import TranscribeRefused, Transcription
from .transcripts import Fetcher, TranscriptService
from .youtube import Clock, YoutubeGate

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
APK_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}\.apk$")
APK_MIME = "application/vnd.android.package-archive"
LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
WEB_DIR = Path(__file__).parent / "web"
RECENT_JOBS_LIMIT = 20
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
    gate: YoutubeGate
    transcription: Transcription
    limiter: RateLimiter


def build_services(
    cfg: Config,
    *,
    llm_transport: httpx.AsyncBaseTransport | None = None,
    fetcher: Fetcher | None = None,
    asr: ASRBackend | None = None,
    downloader: Downloader | None = None,
    prompt_transport: httpx.AsyncBaseTransport | None = None,
    clock: Clock | None = None,
) -> Services:
    db = Database(cfg.db_path)
    llm = LLMClient(cfg, transport=llm_transport)
    gate = YoutubeGate(cfg.youtube, db, clock)
    transcripts = TranscriptService(cfg, db, fetcher, gate)
    prompts = PromptStore(cfg, db, prompt_transport)
    pipeline = CaptionPipeline(
        cfg, db, asr or make_asr(cfg.captions), llm, downloader=downloader, gate=gate
    )
    jobs = JobQueue(cfg, db, pipeline, transcripts)
    transcription = Transcription(cfg, transcripts, jobs)
    return Services(
        cfg=cfg,
        db=db,
        auth=Auth(cfg, db),
        llm=llm,
        transcripts=transcripts,
        assessor=Assessor(cfg, db, llm, transcripts),
        prompts=prompts,
        content=ContentService(cfg, db, llm, transcripts, prompts, transcription),
        jobs=jobs,
        gate=gate,
        transcription=transcription,
        limiter=RateLimiter(cfg.security.rate_window_s),
    )


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


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
        yield
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
        return client_ip(
            request.client.host if request.client else None,
            request.headers.get("x-forwarded-for"),
            cfg.security.trusted_proxies,
        )

    def authenticate(request: Request, token: str | None) -> UserConfig:
        principal = svc.auth.resolve(token)
        svc.limiter.check(
            f"tok:{principal.user.name}:{principal.token_id}", cfg.security.rate_per_token_per_min
        )
        request.state.principal = principal
        return principal.user

    def current_user(request: Request) -> UserConfig:
        return authenticate(request, bearer(request))

    def current_user_or_query(request: Request, token: str | None = Query(None)) -> UserConfig:
        return authenticate(request, bearer(request) or token)

    def admin_user(request: Request) -> UserConfig:
        user = authenticate(request, bearer(request))
        if not user.admin:
            raise Forbidden
        return user

    @app.middleware("http")
    async def ip_rate_limit(request: Request, call_next):
        try:
            svc.limiter.check(f"ip:{ip_of(request)}", cfg.security.rate_per_ip_per_min)
        except RateLimited as exc:
            resp = error(429, "rate limited")
            resp.headers["Retry-After"] = str(exc.retry_after)
            return resp
        return await call_next(request)

    app.add_middleware(BodyLimitMiddleware, get_max_bytes=lambda: cfg.security.max_body_bytes)

    def qmeta(
        title: str | None = None, channel: str | None = None, duration_s: int | None = None
    ) -> QueryMeta:
        return QueryMeta(title=title, channel=channel, duration_s=duration_s)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse((WEB_DIR / "index.html").read_text())

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
            "features": {
                "assess": True,
                "insight": True,
                "captions": True,
                "transcribe": True,
            },
        }

    @app.put("/v1/me/policy")
    async def me_policy(body: PolicyPatch, user: UserConfig = Depends(current_user)):
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
        video_id: str,
        wait_ms: int | None = None,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        return await svc.content.insight(user.policy, video_id, meta.as_dict(), wait_ms)

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
        return {"default": body.key}

    @app.put("/v1/prompts/panel-default")
    async def prompts_panel_default(body: DefaultRequest, user: UserConfig = Depends(current_user)):
        try:
            svc.prompts.set_panel_default(user.name, body.key)
        except PromptError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"panel_default": body.key}

    @app.get("/v1/videos/{video_id}/summary")
    async def summary(
        video_id: str,
        prompt: str | None = None,
        wait_ms: int | None = None,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        panel = prompt == PANEL_ALIAS
        if panel:
            key = svc.prompts.panel_key(user.name)
        else:
            key = prompt or svc.prompts.default_key(user.name)
        resolved = svc.prompts.resolve(user.name, key)
        if resolved is None:
            raise HTTPException(404, f"unknown prompt {key}")
        result = await svc.content.summary(
            user.policy, video_id, resolved, key, meta.as_dict(), wait_ms
        )
        if panel and result["status"] == "ready":
            svc.content.schedule_long(user.name, user.policy, video_id, meta.as_dict(), key)
        return result

    @app.post("/v1/videos/{video_id}/summary")
    async def summary_adhoc(
        video_id: str,
        body: SummaryAdhoc,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
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
        return await svc.content.summary(
            user.policy, video_id, adhoc, "adhoc", meta.as_dict(), body.wait_ms, adhoc=True
        )

    @app.post("/v1/videos/{video_id}/ask")
    async def ask(
        video_id: str,
        body: AskRequest,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        return await svc.content.ask(
            user.policy, video_id, body.question, meta.as_dict(), body.wait_ms
        )

    @app.post("/v1/videos/{video_id}/captions")
    async def captions_queue(
        video_id: str, body: CaptionsRequest | None = None, user: UserConfig = Depends(current_user)
    ):
        check_video_id(video_id)
        body = body or CaptionsRequest()
        for lang in (body.lang, body.translate_to):
            if lang and lang != "auto" and not LANG_RE.match(lang):
                raise HTTPException(400, "invalid language code")
        job = svc.jobs.enqueue(user.name, video_id, body.lang, body.translate_to)
        return {"status": job["status"], "job_id": job["id"], "eta_s": None}

    @app.get("/v1/videos/{video_id}/captions")
    async def captions_status(video_id: str, user: UserConfig = Depends(current_user)):
        check_video_id(video_id)
        return svc.jobs.status(video_id)

    @app.post("/v1/videos/{video_id}/transcribe")
    async def transcribe(
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        try:
            return svc.transcription.request(user.name, video_id, meta.as_dict())
        except TranscribeRefused as exc:
            raise HTTPException(exc.status, exc.message) from exc

    @app.get("/v1/videos/{video_id}/transcript")
    async def transcript_status(
        video_id: str,
        meta: QueryMeta = Depends(qmeta),
        user: UserConfig = Depends(current_user),
    ):
        check_video_id(video_id)
        return svc.transcription.status(video_id, meta.as_dict())

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
        video_id: str, lang: str, user: UserConfig = Depends(current_user_or_query)
    ):
        check_video_id(video_id)
        row = svc.db.one("SELECT vtt FROM captions WHERE video_id=? AND lang=?", [video_id, lang])
        if not row:
            raise HTTPException(404, "no such track")
        return PlainTextResponse(row["vtt"], media_type="text/vtt")

    @app.post("/v1/feedback")
    async def feedback(body: FeedbackRequest, user: UserConfig = Depends(current_user)):
        svc.db.execute(
            "INSERT INTO feedback(user,video_id,kind,correct,note,created_at) VALUES(?,?,?,?,?,?)",
            [user.name, body.video_id, body.kind, int(body.correct), body.note, time.time()],
        )
        return {"ok": True}

    return app


def app_factory() -> FastAPI:
    return create_app()
