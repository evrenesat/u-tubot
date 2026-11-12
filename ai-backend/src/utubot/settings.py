"""Per-user settings document (`GET/PUT /v1/me/settings`).

One store, no copies. The document is a view over what already holds each value:

- everything in `UserPolicy` (filtering, language, auto_long, models, transcript policy, TV
  settings) lives in the user's override row of `policy_overrides`, which also carries the version;
- the two prompt defaults live in `user_default` / `user_panel_default`.

Resolution of a value, highest first: the user's override, the user's `[users.policy]`,
`[default_policy]`, then the server setting a `None` field follows (see `UserPolicy`).
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .auth import Auth, VersionConflict, build_policy, describe_validation
from .config import MODEL_TASKS, Config, LLMTask, UserPolicy
from .modelcatalog import ModelCatalog, ModelNotListed
from .prompts import DEFAULT_BUILTIN_KEY, PromptStore

SECTION_FIELDS: dict[str, tuple[str, ...]] = {
    "filtering": (
        "hide_topics",
        "mark_topics",
        "hide_clickbait_above",
        "mark_clickbait_above",
        "hide_low_quality_above",
        "mark_low_quality_above",
        "mark_inflated_ratio_below",
        "inflated_min_duration_s",
        "answer_in_label",
        "mark_only",
    ),
    "summaries": ("language", "auto_long"),
    "transcripts": ("auto_transcribe", "auto_transcribe_max_minutes"),
    "tv": ("summary_delay_ms", "summary_panel", "auto_captions", "update_checks"),
}
PROMPT_KEYS = ("default", "panel_default")
SECTIONS = ("models", "prompts", *SECTION_FIELDS)
FIELD_SECTION = {f: s for s, fields in SECTION_FIELDS.items() for f in fields}


class SettingsError(Exception):
    def __init__(self, status: int, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def task_model_name(task: LLMTask) -> str:
    return f"{task.provider}:{task.model}" if task.provider else task.model


def configured_models(cfg: Config) -> dict[str, str]:
    """What each task runs on without a user choice: the `[llm.<task>]` tables."""
    llm = cfg.llm
    tasks = {
        "glance": llm.glance_task(),
        "summary": llm.summary,
        "answer": llm.answer,
        "triage": llm.triage,
        "analysis": llm.analysis,
    }
    return {name: task_model_name(tasks[name]) for name in MODEL_TASKS}


def resolved_fields(cfg: Config, policy: UserPolicy) -> dict[str, Any]:
    """Every settable policy field with `None` replaced by the server setting it follows."""
    values = policy.model_dump()
    values["auto_long"] = cfg.summary.auto_long if policy.auto_long is None else policy.auto_long
    setup = cfg.setup.defaults
    for name in ("mark_only", "summary_panel", "auto_captions"):
        if values[name] is None:
            values[name] = getattr(setup, name)
    return values


class SettingsService:
    def __init__(self, cfg: Config, auth: Auth, prompts: PromptStore, catalog: ModelCatalog):
        self.cfg, self.auth, self.prompts, self.catalog = cfg, auth, prompts, catalog

    def _sections(self, cfg_values: dict[str, Any]) -> dict[str, Any]:
        return {
            section: {field: cfg_values[field] for field in fields}
            for section, fields in SECTION_FIELDS.items()
        }

    def _resolved(self, name: str, policy: UserPolicy) -> dict[str, Any]:
        values = resolved_fields(self.cfg, policy)
        out = self._sections(values)
        defaults = configured_models(self.cfg)
        out["models"] = {t: policy.models.get(t) or defaults[t] for t in MODEL_TASKS}
        return out

    def effective(self, name: str) -> dict[str, Any]:
        user = self.auth.user_config(name)
        if user is None:
            raise SettingsError(404, "unknown user")
        out = self._resolved(name, user.policy)
        out["prompts"] = {
            "default": self.prompts.default_key(name),
            "panel_default": self.prompts.panel_key(name),
        }
        return out

    def defaults(self, name: str) -> dict[str, Any]:
        out = self._resolved(name, self.auth.base_policy(name))
        out["prompts"] = {
            "default": DEFAULT_BUILTIN_KEY,
            "panel_default": self.prompts.server_panel_key(),
        }
        return out

    def overrides(self, name: str) -> dict[str, Any]:
        raw = self.auth.policy_override(name)
        out: dict[str, Any] = {}
        for field, value in raw.items():
            if field == "models":
                if value:
                    out["models"] = dict(value)
            elif field in FIELD_SECTION:
                out.setdefault(FIELD_SECTION[field], {})[field] = value
        chosen = {
            "default": self.prompts.default_key(name),
            "panel_default": self.prompts.panel_key(name),
        }
        for key, present in self.prompts.has_override(name).items():
            if present:
                out.setdefault("prompts", {})[key] = chosen[key]
        return out

    def document(self, name: str) -> dict[str, Any]:
        version, updated_at = self.auth.settings_version(name)
        return {
            "user": name,
            "version": version,
            "updated_at": updated_at or None,
            "settings": self.effective(name),
            "overrides": self.overrides(name),
            "defaults": self.defaults(name),
            "choices": {
                "tasks": list(MODEL_TASKS),
                "auto_transcribe": ["off", "on_dwell", "on_open"],
            },
        }

    def _parse(
        self, body: Any
    ) -> tuple[dict[str, Any], dict[str, str | None], dict[str, str | None]]:
        """Split a PUT body into policy fields, task models and prompt keys (None resets)."""
        if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
            raise SettingsError(400, 'body must be {"settings": {...}}')
        fields: dict[str, Any] = {}
        models: dict[str, str | None] = {}
        prompts: dict[str, str | None] = {}
        for section, values in body["settings"].items():
            if section not in SECTIONS or not isinstance(values, dict):
                raise SettingsError(400, f"unknown settings section {section!r}")
            for key, value in values.items():
                if section == "models":
                    if key not in MODEL_TASKS:
                        raise SettingsError(400, f"unknown model task {key!r}")
                    models[key] = value if value else None
                elif section == "prompts":
                    if key not in PROMPT_KEYS:
                        raise SettingsError(400, f"unknown prompt setting {key!r}")
                    prompts[key] = value if value else None
                elif key in SECTION_FIELDS[section]:
                    fields[key] = value
                else:
                    raise SettingsError(400, f"unknown setting {section}.{key}")
        return fields, models, prompts

    async def update(
        self, name: str, body: Any, *, is_admin: bool = False, require_version: bool = False
    ) -> dict[str, Any]:
        """Apply a partial settings document.

        `allow_unlisted_models` is for admins. `require_version` (browser sessions) refuses a
        write that does not say which version it was made from (428). Everything after the model
        check runs without yielding, and the write itself is a compare-and-set on the version, so
        two writers from the same version cannot both succeed.
        """
        fields, models, prompts = self._parse(body)
        allow_unlisted = bool(body.get("allow_unlisted_models"))
        if allow_unlisted and not is_admin:
            raise SettingsError(403, "allow_unlisted_models is for admins only")
        supplied = body.get("version")
        if require_version and supplied is None:
            raise SettingsError(
                428,
                "send the settings version you loaded with the change",
                version=self.auth.settings_version(name)[0],
            )
        for value in models.values():
            if value is not None and not isinstance(value, str):
                raise SettingsError(400, "a model must be a string")
        if not (fields or models or prompts):
            return self.document(name)
        await self._check_models(models, allow_unlisted)
        current, _ = self.auth.settings_version(name)
        if supplied is not None and supplied != current:
            raise SettingsError(
                409, "settings changed since you loaded them; reload", version=current
            )
        for key, value in prompts.items():
            if value is not None and (
                not isinstance(value, str) or not self.prompts.resolve(name, value)
            ):
                raise SettingsError(400, f"unknown prompt for {key}: {value}")
        override = self._merged_override(name, fields, models)
        try:
            self.auth.write_override(name, override, expected=current)
        except VersionConflict as exc:
            raise SettingsError(
                409, "settings changed since you loaded them; reload", version=exc.version
            ) from exc
        self._apply_prompts(name, prompts)
        return self.document(name)

    def _merged_override(
        self, name: str, fields: dict[str, Any], models: dict[str, str | None]
    ) -> dict[str, Any]:
        override = dict(self.auth.policy_override(name))
        chosen_models = dict(override.get("models") or {})
        for task, value in models.items():
            if value is None:
                chosen_models.pop(task, None)
            else:
                chosen_models[task] = value
        trial = {k: v for k, v in override.items() if k not in fields and k != "models"}
        trial.update({k: v for k, v in fields.items() if v is not None})
        if chosen_models:
            trial["models"] = chosen_models
        try:
            policy = build_policy(self.auth.base_policy(name), trial)
        except ValidationError as exc:
            raise SettingsError(
                400, describe_validation(exc).replace("invalid policy", "invalid settings")
            ) from exc
        for key in fields:
            if fields[key] is not None:
                trial[key] = getattr(policy, key)
        if chosen_models:
            trial["models"] = UserPolicy(models=chosen_models).models
        return trial

    async def _check_models(self, models: dict[str, str | None], allow_unlisted: bool) -> None:
        if allow_unlisted:
            return
        for value in {v for v in models.values() if v}:
            try:
                await self.catalog.check(value)
            except ModelNotListed as exc:
                raise SettingsError(400, str(exc), unlisted=value) from exc

    def _apply_prompts(self, name: str, prompts: dict[str, str | None]) -> None:
        for key, value in prompts.items():
            setter = (
                self.prompts.set_default if key == "default" else self.prompts.set_panel_default
            )
            clearer = (
                self.prompts.clear_default if key == "default" else self.prompts.clear_panel_default
            )
            if value is None:
                clearer(name)
            else:
                setter(name, value)
