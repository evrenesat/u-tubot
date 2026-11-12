from __future__ import annotations

import os
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

CONFIG_ENV = "UTUBOT_CONFIG"
DEFAULT_CONFIG_PATH = "./config.toml"
DEFAULT_PROVIDER = "default"
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8000/v1"


class LLMTask(BaseModel):
    model: str
    provider: str | None = None
    reasoning_effort: str | None = None
    max_tokens: int = 1024
    temperature: float = 0.2


class ProviderConfig(BaseModel):
    base_url: str = DEFAULT_LLM_BASE_URL
    api_key_env: str | None = None


class LLMConfig(BaseModel):
    providers: dict[str, ProviderConfig] = Field(
        default_factory=lambda: {DEFAULT_PROVIDER: ProviderConfig()}
    )
    default_provider: str = DEFAULT_PROVIDER
    timeout_s: float = 120.0
    retries_on_bad_json: int = 1
    max_concurrency: int = 4
    triage: LLMTask = LLMTask(model="fast", reasoning_effort="none", max_tokens=2500)
    summary: LLMTask = LLMTask(model="worker", max_tokens=900)
    answer: LLMTask = LLMTask(model="worker", max_tokens=600)
    analysis: LLMTask = LLMTask(model="worker", max_tokens=900)
    captions: LLMTask = LLMTask(model="worker", max_tokens=2000)
    smart: LLMTask = LLMTask(model="smart", max_tokens=1500)


class AssessConfig(BaseModel):
    batch_size: int = 25
    max_videos_per_request: int = 50
    wait_ms_cap: int = 3000
    default_wait_ms: int = 1200
    background_concurrency: int = 2
    tier2_daily_cap_per_user: int = 40
    tier2_clickbait_threshold: float = 0.6
    triage_cache_ttl_s: int = 7 * 86400
    title_max_chars: int = 200
    description_max_chars: int = 300


class TranscriptConfig(BaseModel):
    cache_ttl_s: int = 30 * 86400
    max_concurrency: int = 2
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


class CaptionsConfig(BaseModel):
    asr_backend: str = "openai"
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
    audio_format: str = "bestaudio/best"
    asr_chunk_s: int = 600
    translate_batch: int = 40


class UserPolicy(BaseModel):
    language: str = "en"
    hide_topics: list[str] = Field(default_factory=list)
    mark_topics: list[str] = Field(default_factory=list)
    hide_clickbait_above: float = 0.9
    mark_clickbait_above: float = 0.6
    hide_low_quality_above: float = 0.9
    mark_low_quality_above: float = 0.65
    mark_inflated_ratio_below: float = 0.35
    inflated_min_duration_s: int = 300
    answer_in_label: bool = False


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


class Config(BaseModel):
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    assess: AssessConfig = Field(default_factory=AssessConfig)
    transcripts: TranscriptConfig = Field(default_factory=TranscriptConfig)
    summary: SummaryConfig = Field(default_factory=SummaryConfig)
    captions: CaptionsConfig = Field(default_factory=CaptionsConfig)
    setup: SetupConfig = Field(default_factory=SetupConfig)
    app: AppConfig = Field(default_factory=AppConfig)
    default_policy: UserPolicy = Field(default_factory=UserPolicy)
    users: list[UserConfig] = Field(default_factory=list)
    config_path: str = ""

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

    def api_key(self, provider: str) -> str | None:
        env = self.llm.providers[provider].api_key_env
        if not env:
            return None
        return os.environ.get(env) or None


def _merge_policy(default: UserPolicy, override: dict) -> UserPolicy:
    return UserPolicy(**{**default.model_dump(), **override})


def load_config(path: str | os.PathLike | None = None) -> Config:
    cfg_path = Path(path or os.environ.get(CONFIG_ENV, DEFAULT_CONFIG_PATH))
    raw: dict = {}
    if cfg_path.exists():
        raw = tomllib.loads(cfg_path.read_text())
    cfg = Config(**raw)
    cfg.config_path = str(cfg_path)
    users = {u.name: u for u in cfg.users}
    users_path = cfg.users_path
    if users_path.exists():
        extra = tomllib.loads(users_path.read_text())
        for entry in extra.get("users", []):
            existing = users.get(entry["name"])
            if existing:
                users[entry["name"]] = existing.model_copy(
                    update={"token_sha256": entry["token_sha256"]}
                )
            else:
                users[entry["name"]] = UserConfig(**entry)
    resolved = []
    for user in users.values():
        policy_raw = user.policy.model_dump(exclude_unset=True)
        resolved.append(
            user.model_copy(update={"policy": _merge_policy(cfg.default_policy, policy_raw)})
        )
    cfg.users = resolved
    return cfg
