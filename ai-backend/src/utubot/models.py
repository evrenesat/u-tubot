from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel

from .db import MAX_CHANNEL_ID_CHARS, MAX_CHANNEL_NAME_CHARS


class VideoMeta(BaseModel):
    video_id: str
    title: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    duration_s: int | None = None
    published: str | None = None
    views: str | None = None
    is_short: bool | None = None
    is_live: bool | None = None
    description: str | None = None


class Flag(BaseModel):
    kind: Literal["clickbait", "low_quality", "inflated", "topic"]
    label: str
    severity: float
    reason: str = ""


class Verdict(BaseModel):
    video_id: str
    status: Literal["ready", "pending"] = "ready"
    action: Literal["none", "mark", "hide"] = "none"
    mark_label: str | None = None
    flags: list[Flag] = Field(default_factory=list)
    title_question: str | None = None
    answer_short: str | None = None
    insight_ready: bool = False
    captions_ready: bool = False


class AssessRequest(BaseModel):
    videos: list[VideoMeta]
    section: str = "other"
    wait_ms: int | None = None


class SummaryAdhoc(BaseModel):
    prompt_text: str
    system: str | None = None
    wait_ms: int | None = None
    max_tokens: int | None = None


class AskRequest(BaseModel):
    question: str
    wait_ms: int | None = None


class CaptionsRequest(BaseModel):
    """A captions job. An unset `translate_to` follows the `[captions] translate_to` default
    ("en"): the goal is English captions whatever the source language; "off" keeps the source."""

    lang: str = "auto"
    translate_to: str | None = None


class CutCreateRequest(BaseModel):
    """A director's cut request: a preset id, a prompt the owner typed, or an empty request
    (`await_prompt`) the phone fills later."""

    preset: str | None = Field(None, max_length=64)
    prompt: str | None = Field(None, max_length=2000)
    await_prompt: bool = False
    mode: Literal["quick", "watched"] | None = None


class CutPromptBody(BaseModel):
    """The description a phone sends to fill a waiting cut request."""

    prompt: str = Field(max_length=2000)
    mode: Literal["quick", "watched"] | None = None


class CutChannelMode(BaseModel):
    """The owner's default cut mode for one channel; `mode: null` clears it."""

    mode: Literal["quick", "watched"] | None = None
    channel_name: str | None = Field(None, max_length=MAX_CHANNEL_NAME_CHARS)


class CutPresetSave(BaseModel):
    """A description the owner saves as his own cut preset (phone only in v1)."""

    label: str = Field(min_length=1, max_length=60)
    prompt: str = Field(min_length=1, max_length=2000)
    length_min: float | None = None
    length_frac: float | None = None


class PairRequest(BaseModel):
    code: str = Field(max_length=16)
    device: str = Field(default="device", max_length=200)


class PairCodeRequest(BaseModel):
    user: str


class PolicyPatch(RootModel[dict[str, Any]]):
    pass


class FeedbackRequest(BaseModel):
    video_id: str
    kind: str
    correct: bool
    note: str | None = None


class ImportRequest(BaseModel):
    url: str


class DefaultRequest(BaseModel):
    key: str


class QueryMeta(BaseModel):
    title: str | None = None
    channel: str | None = None
    channel_id: str | None = Field(None, max_length=MAX_CHANNEL_ID_CHARS)
    duration_s: int | None = None
    is_live: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class LoginRequest(BaseModel):
    username: str | None = Field(default=None, max_length=64)
    password: str | None = Field(default=None, max_length=512)
    token: str | None = Field(default=None, max_length=512)


class PasswordChange(BaseModel):
    current_password: str | None = Field(default=None, max_length=512)
    new_password: str = Field(max_length=512)


class PasswordSet(BaseModel):
    password: str = Field(max_length=512)


class NewUser(BaseModel):
    name: str = Field(max_length=64)
    admin: bool = False
    password: str | None = Field(default=None, max_length=512)


class UserPatch(BaseModel):
    admin: bool


class ResolveRequest(BaseModel):
    text: str = Field(max_length=1024)
