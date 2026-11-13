from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CONFIG_ENV = "UTUBOT_CONFIG"
DEFAULT_CONFIG_PATH = "./config.toml"
DEFAULT_PROVIDER = "default"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8000/v1"
GLANCE_MAX_TOKENS = 160
GLANCE_REASONING_EFFORT = "none"


class LLMTask(BaseModel):
    model: str
    provider: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int = 1024
    reasoning_headroom_tokens: int | None = None
    temperature: float = 0.2
    fallback: list[str] = Field(default_factory=list)


class GlanceTask(LLMTask):
    """`[llm.glance]`: the fast task behind the short panel summary."""

    reasoning_effort: str | None = GLANCE_REASONING_EFFORT
    max_tokens: int = GLANCE_MAX_TOKENS


class ProviderConfig(BaseModel):
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key_env: str | None = None
    max_concurrent: int = 2
    reserved_interactive: int = 1
    json_mode: bool = False


class LLMConfig(BaseModel):
    providers: dict[str, ProviderConfig] = Field(
        default_factory=lambda: {DEFAULT_PROVIDER: ProviderConfig()}
    )
    default_provider: str = DEFAULT_PROVIDER
    timeout_s: float = 120.0
    retries_on_bad_json: int = 1
    json_retry_max_tokens: int = 6000
    reasoning_headroom_tokens: int = 2048
    retry_max_attempts: int = 4
    retry_base_s: float = 1.0
    retry_max_s: float = 15.0
    deadline_interactive_s: float = 45.0
    deadline_background_s: float = 120.0
    triage: LLMTask = LLMTask(model="fast", reasoning_effort="none", max_tokens=2500)
    summary: LLMTask = LLMTask(model="worker", max_tokens=900)
    glance: GlanceTask | None = None
    answer: LLMTask = LLMTask(model="worker", max_tokens=600)
    analysis: LLMTask = LLMTask(model="worker", max_tokens=900)
    captions: LLMTask = LLMTask(model="worker", max_tokens=2000)
    smart: LLMTask = LLMTask(model="smart", max_tokens=1500)

    def glance_task(self) -> LLMTask:
        """`[llm.glance]` when configured, else `[llm.summary]` with reasoning off."""
        if self.glance is not None:
            return self.glance
        return self.summary.model_copy(
            update={"reasoning_effort": GLANCE_REASONING_EFFORT, "max_tokens": GLANCE_MAX_TOKENS}
        )


class AssessConfig(BaseModel):
    batch_size: int = 25
    max_videos_per_request: int = 50
    wait_ms_cap: int = 3000
    default_wait_ms: int = 1200
    background_concurrency: int = 2
    coalesce_ms: int = 300
    tier2_daily_cap_per_user: int = 30
    tier2_clickbait_threshold: float = 0.6
    triage_cache_ttl_s: int = 7 * 86400
    title_max_chars: int = 200
    description_max_chars: int = 300


class YoutubeConfig(BaseModel):
    """Pacing and circuit breaker for every request that reaches YouTube."""

    max_concurrent: int = 1
    min_interval_s: float = 3.0
    jitter_s: float = 1.5
    cooldown_base_s: float = 300.0
    cooldown_max_s: float = 3600.0
    captions_cooldown_max_s: float = 1800.0
    captions_probe_retry_s: float = 10.0
    network_retry_s: float = 60.0
    max_background_queue: int = 5
    js_runtime: Literal["deno", "node", "bun", "quickjs"] = "deno"
    js_runtime_path: str = ""
    remote_components: list[str] = Field(default_factory=list)


class TranscriptConfig(BaseModel):
    cache_ttl_s: int = 30 * 86400
    no_captions_ttl_s: int = 3 * 86400
    video_failure_ttl_s: int = 3600
    empty_track_retry_s: int = 3600
    fetch_timeout_s: float = 60.0
    prefer_manual: bool = True
    default_language: str = "en"
    cookies_file: str | None = None
    skip_if_longer_than_s: int = 4 * 3600


class SummaryConfig(BaseModel):
    token_budget: int = 24000
    chunk_tokens: int = 8000
    chars_per_token: int = 4
    strategy: str = "map_reduce"
    default_wait_ms: int = 20000
    wait_ms_cap: int = 60000
    adhoc_ttl_s: int = 3600
    max_summary_chars: int = 1200
    failure_cooldown_s: int = 30
    condensed_max_tokens: int = 700
    max_import_bytes: int = 256 * 1024
    import_timeout_s: float = 15.0
    import_allow_hosts: list[str] = Field(default_factory=list)
    import_max_redirects: int = 5
    panel_prompt: str = "builtin/glance"
    auto_long: bool = False
    auto_long_max_concurrent: int = 2


ASR_KIND_OPENAI = "openai"
ASR_KIND_FASTER_WHISPER = "faster_whisper"
LEGACY_ENGINE_NAME = "default"
DEFAULT_OPENAI_ASR_MODEL = "whisper-1"
DEFAULT_FASTER_WHISPER_MODEL = "small"


class AsrEngineConfig(BaseModel):
    """One speech-to-text engine of the chain (`[[captions.asr_engines]]`)."""

    name: str
    kind: Literal["openai", "faster_whisper"] = ASR_KIND_OPENAI
    url: str = ""
    model: str = ""
    api_key_env: str | None = None
    key_optional: bool = False
    languages: list[str] = Field(default_factory=list)
    max_chunk_s: int = Field(default=600, ge=0)
    max_parallel: int = Field(default=1, ge=1)
    timeout_s: float = 900.0
    priority: int = 100
    background_only: bool = False
    speed_factor: float = 1.5
    overhead_s: float = 2.0
    compute_type: str | None = None
    threads: int | None = None

    @model_validator(mode="after")
    def _defaults(self) -> AsrEngineConfig:
        if not self.model:
            self.model = (
                DEFAULT_FASTER_WHISPER_MODEL
                if self.kind == ASR_KIND_FASTER_WHISPER
                else DEFAULT_OPENAI_ASR_MODEL
            )
        if self.kind == ASR_KIND_OPENAI and not self.url:
            raise ValueError(f"asr engine {self.name}: kind openai needs a url")
        self.languages = [lang.strip().lower() for lang in self.languages if lang.strip()]
        return self


class CaptionsConfig(BaseModel):
    asr_engines: list[AsrEngineConfig] = Field(default_factory=list)
    asr_unhealthy_s: float = 300.0
    asr_failure_window_s: float = 600.0
    asr_chunk_overlap_s: float = 2.0
    asr_backend: Literal["openai", "faster_whisper"] = ASR_KIND_OPENAI
    asr_url: str = "http://127.0.0.1:8000/v1/audio/transcriptions"
    asr_api_key_env: str = "UTUBOT_ASR_API_KEY"
    asr_model: str = "whisper-1"
    asr_timeout_s: float = 1800.0
    whisper_model: str = "small"
    whisper_compute_type: str = "int8"
    whisper_threads: int = 8
    diarization: str = "none"
    hf_token_env: str = "UTUBOT_HF_TOKEN"
    sample_rate: int = 16000
    max_duration_s: int = 3 * 3600
    keep_media: bool = False
    max_chars_per_line: int = 42
    max_lines: int = 2
    min_cue_s: float = 1.0
    max_cue_s: float = 7.0
    speaker_gap_s: float = 1.0
    sentence_gap_s: float = 0.6
    job_concurrency: int = 1
    job_poll_s: float = 2.0
    asr_speed_factor: float = 1.5
    asr_overhead_s: int = 30
    download_overhead_s: float = 5.0
    download_speed_factor: float = 300.0
    transcribe_max_active_per_user: int = 5
    job_max_attempts: int = 3
    media_orphan_age_s: int = 3600
    max_download_bytes: int = 400 * 1024 * 1024
    audio_format: str = "bestaudio/best"
    asr_chunk_s: int = 600
    translate_batch: int = 40
    job_events_max: int = 400
    delivery_coalesce_s: float = 300.0
    delivery_events_max: int = 50

    def engines(self) -> list[AsrEngineConfig]:
        """The engine chain: `asr_engines`, or the legacy `asr_backend`/`asr_*` keys as one engine."""
        if self.asr_engines:
            return list(self.asr_engines)
        faster = self.asr_backend == ASR_KIND_FASTER_WHISPER
        return [
            AsrEngineConfig(
                name=LEGACY_ENGINE_NAME,
                kind=ASR_KIND_FASTER_WHISPER if faster else ASR_KIND_OPENAI,
                url=self.asr_url,
                model=self.whisper_model if faster else self.asr_model,
                api_key_env=self.asr_api_key_env,
                key_optional=True,
                max_chunk_s=self.asr_chunk_s,
                timeout_s=self.asr_timeout_s,
                speed_factor=self.asr_speed_factor,
                overhead_s=float(self.asr_overhead_s),
                compute_type=self.whisper_compute_type,
                threads=self.whisper_threads,
            )
        ]


TASK_ANSWER = "answer"
TASK_TRIAGE = "triage"
TASK_ANALYSIS = "analysis"
MODEL_TASKS = ("glance", "summary", TASK_ANSWER, TASK_TRIAGE, TASK_ANALYSIS)
MAX_TOPICS = 50
MAX_TOPIC_CHARS = 80
MAX_MODEL_CHARS = 200
MAX_LANGUAGE_CHARS = 40
MAX_THRESHOLD = 1.01
MAX_TRANSCRIBE_MINUTES = 24 * 60
MAX_SUMMARY_DELAY_MS = 10_000
MAX_INFLATED_MIN_S = 24 * 3600
Threshold = Annotated[float, Field(ge=0.0, le=MAX_THRESHOLD)]


class UserPolicy(BaseModel):
    """Everything the server keeps per user: filtering rules, models, transcript and TV settings.

    Resolution, lowest to highest: these defaults, `[default_policy]`, the user's `[users.policy]`,
    then the runtime override row (`PUT /v1/me/settings`, `PUT /v1/me/policy`). A field left `None`
    follows its server-wide setting (`auto_long` -> `[summary]`, `mark_only`, `summary_panel`,
    `auto_captions` -> `[setup.defaults]`); a task without a `models` entry follows `[llm.<task>]`.
    """

    language: str = Field("en", min_length=1, max_length=MAX_LANGUAGE_CHARS)
    hide_topics: list[str] = Field(default_factory=list)
    mark_topics: list[str] = Field(default_factory=list)
    hide_clickbait_above: Threshold = 0.9
    mark_clickbait_above: Threshold = 0.6
    hide_low_quality_above: Threshold = 0.9
    mark_low_quality_above: Threshold = 0.65
    mark_inflated_ratio_below: Threshold = 0.35
    inflated_min_duration_s: int = Field(300, ge=0, le=MAX_INFLATED_MIN_S)
    answer_in_label: bool = False
    auto_long: bool | None = None
    mark_only: bool | None = None
    models: dict[str, str] = Field(default_factory=dict)
    auto_transcribe: Literal["off", "on_dwell", "on_open"] = "on_open"
    auto_transcribe_max_minutes: int = Field(30, ge=1, le=MAX_TRANSCRIBE_MINUTES)
    summary_delay_ms: int = Field(700, ge=0, le=MAX_SUMMARY_DELAY_MS)
    summary_panel: bool | None = None
    auto_captions: bool | None = None
    update_checks: bool = True

    @field_validator("hide_topics", "mark_topics")
    @classmethod
    def _topics(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for topic in v:
            clean = " ".join(str(topic).split())
            if not clean:
                continue
            if len(clean) > MAX_TOPIC_CHARS:
                raise ValueError(f"a topic is longer than {MAX_TOPIC_CHARS} characters")
            if clean not in out:
                out.append(clean)
        if len(out) > MAX_TOPICS:
            raise ValueError(f"at most {MAX_TOPICS} topics")
        return out

    @field_validator("models")
    @classmethod
    def _models(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for task, name in v.items():
            if task not in MODEL_TASKS:
                raise ValueError(f"unknown task {task!r}; use one of {', '.join(MODEL_TASKS)}")
            clean = str(name).strip()
            if not clean:
                continue
            if len(clean) > MAX_MODEL_CHARS or any(ch.isspace() or ord(ch) < 32 for ch in clean):
                raise ValueError(f"invalid model name for {task}")
            out[task] = clean
        return out


class UserConfig(BaseModel):
    name: str
    token_sha256: str = ""
    admin: bool = False
    policy: UserPolicy = Field(default_factory=UserPolicy)


DEFAULT_PUBLIC_BASE_URL = "http://127.0.0.1:8790"


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8790
    data_dir: str = "./data"
    users_file: str | None = None
    app_dir: str = "./app"
    public_base_url: str = DEFAULT_PUBLIC_BASE_URL

    def download_url(self, filename: str) -> str:
        base = self.public_base_url.strip().rstrip("/")
        if not base or base == DEFAULT_PUBLIC_BASE_URL:
            return f"/app/{filename}"
        return f"{base}/app/{filename}"


class SecurityConfig(BaseModel):
    trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1", "::1"])
    client_ip_header: str = ""
    client_ip_header_secret_env: str = "UTUBOT_PROXY_SECRET"
    rate_per_token_per_min: int = 240
    rate_per_ip_per_min: int = 600
    rate_window_s: int = 60
    pair_code_digits: int = 6
    pair_code_ttl_s: int = 900
    pair_attempts_per_ip_per_min: int = 5
    pair_lockout_failures: int = 5
    pair_lockout_s: int = 900
    pair_global_failures: int = 40
    pair_global_window_s: int = 3600
    max_body_bytes: int = 262144
    max_device_name_chars: int = 64
    max_devices_per_user: int = 20
    session_cookie: str = "utubot_session"
    session_ttl_s: int = 30 * 86400
    session_refresh_s: int = 3600
    max_sessions_per_user: int = 20
    password_min_chars: int = 10
    password_max_chars: int = 256
    scrypt_n: int = 2**17
    scrypt_max_concurrent: int = 2
    scrypt_r: int = 8
    scrypt_p: int = 1
    login_attempts_per_ip_per_min: int = 10
    login_lockout_failures: int = 5
    login_lockout_s: int = 900
    login_user_lockout_failures: int = 10
    login_global_failures: int = 200
    login_global_window_s: int = 3600


class ModelsConfig(BaseModel):
    """The live model list the web UI offers (`GET /v1/models`)."""

    cache_ttl_s: int = 300
    error_ttl_s: int = 30
    refresh_min_interval_s: int = 10
    timeout_s: float = 10.0
    new_for_s: int = 3 * 86400
    max_models_per_provider: int = 2000
    refresh_interval_s: int = 600
    summary_default_glob: str = "ornith-*"


class SetupDefaults(BaseModel):
    """App settings a client applies when it imports /setup.json."""

    assess: bool = True
    mark_only: bool = False
    answer_in_menu: bool = True
    summary_panel: bool = False
    auto_captions: bool = True


class SetupConfig(BaseModel):
    name: str = "u·tubot server"
    pairing: bool = True
    defaults: SetupDefaults = Field(default_factory=SetupDefaults)
    prompt_set_urls: list[str] = Field(default_factory=list)


class AppConfig(BaseModel):
    """Public download page and update channel."""

    downloader_codes: dict[str, str] = Field(default_factory=dict)
    github_repo: str = ""
    github_token_env: str = "UTUBOT_GITHUB_TOKEN"
    signing_cert_sha256: str = ""
    apksigner_path: str = ""
    apksigner_timeout_s: float = 120.0
    sync_timeout_s: float = 60.0
    sync_releases_per_page: int = 20
    sync_max_apk_bytes: int = 200 * 1024 * 1024
    keep_versions: int = 0
    release_check_ttl_s: int = 600
    release_check_error_ttl_s: int = 60
    release_check_min_interval_s: int = 30


class Config(BaseModel):
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    assess: AssessConfig = Field(default_factory=AssessConfig)
    youtube: YoutubeConfig = Field(default_factory=YoutubeConfig)
    transcripts: TranscriptConfig = Field(default_factory=TranscriptConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    captions: CaptionsConfig = Field(default_factory=CaptionsConfig)
    setup: SetupConfig = Field(default_factory=SetupConfig)
    models: ModelsConfig = Field(default_factory=ModelsConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    default_policy: UserPolicy = Field(default_factory=UserPolicy)
    users: list[UserConfig] = Field(default_factory=list)
    config_path: str = ""
    config_user_names: list[str] = Field(default_factory=list)
    declared_users: list[UserConfig] | None = None

    @property
    def data_dir(self) -> Path:
        return Path(self.server.data_dir)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "utubot.sqlite"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def users_path(self) -> Path:
        if self.server.users_file:
            return Path(self.server.users_file)
        return self.data_dir / "users.toml"

    @property
    def app_dir(self) -> Path:
        return Path(self.server.app_dir)

    def client_ip_secret(self) -> str | None:
        """The shared secret a trusted proxy sends with `client_ip_header`; unset disables the header."""
        env = self.security.client_ip_header_secret_env
        return (os.environ.get(env) or None) if env else None

    def api_key(self, provider: str) -> str | None:
        env = self.llm.providers[provider].api_key_env
        if not env:
            return None
        return os.environ.get(env) or None


def _merge_policy(default: UserPolicy, override: dict) -> UserPolicy:
    return UserPolicy(**{**default.model_dump(), **override})


def resolve_users(cfg: Config, declared: list[UserConfig]) -> list[UserConfig]:
    """Declared users plus users.toml entries, each policy resolved over `[default_policy]`."""
    users = {u.name: u for u in declared}
    users_path = cfg.users_path
    if users_path.exists():
        extra = tomllib.loads(users_path.read_text())
        for entry in extra.get("users", []):
            existing = users.get(entry["name"])
            if existing:
                users[entry["name"]] = existing.model_copy(
                    update={"token_sha256": entry.get("token_sha256") or existing.token_sha256}
                )
            else:
                users[entry["name"]] = UserConfig(**entry)
    resolved = []
    for user in users.values():
        policy_raw = user.policy.model_dump(exclude_unset=True)
        resolved.append(
            user.model_copy(update={"policy": _merge_policy(cfg.default_policy, policy_raw)})
        )
    return resolved


def load_config(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path or os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.exists():
        raw = tomllib.loads(cfg_path.read_text())
    cfg = Config(**raw)
    cfg.config_path = str(cfg_path)
    cfg.config_user_names = [u.name for u in cfg.users]
    cfg.declared_users = list(cfg.users)
    cfg.users = resolve_users(cfg, cfg.declared_users)
    return cfg
