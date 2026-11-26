from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, field_validator

from .db import MAX_CHANNEL_ID_CHARS, MAX_CHANNEL_NAME_CHARS
from .ledger import KNOWN_CATEGORIES


class VideoMeta(BaseModel):
    """What the app knows from a card for triage. Every field but `video_id` is optional; the assess
    prompt judges clickbait from the title plus this context, so a punchy headline on a subscribed
    creator's regular show is not called clickbait. Missing fields are simply not sent."""

    video_id: str
    title: str | None = None
    channel: str | None = None
    channel_id: str | None = None
    duration_s: int | None = None
    published: str | None = None
    upload_date: str | None = None
    views: str | None = None
    likes: int | None = None
    dislikes: int | None = None
    is_subscribed: bool | None = None
    subscriber_count: int | None = None
    channel_description: str | None = None
    description: str | None = None
    channel_titles: list[str] | None = None
    is_short: bool | None = None
    is_live: bool | None = None


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
    force: bool = False


class CutCreateRequest(BaseModel):
    """A director's cut request: a preset id, a prompt the owner typed, or an empty request
    (`await_prompt`) the phone fills later."""

    preset: str | None = Field(None, max_length=64)
    prompt: str | None = Field(None, max_length=2000)
    await_prompt: bool = False
    mode: str | None = Field(None, max_length=16)
    force: bool = False


class CutPromptBody(BaseModel):
    """The description a phone sends to fill a waiting cut request."""

    prompt: str = Field(max_length=2000)
    mode: str | None = Field(None, max_length=16)


class CutChoiceRequest(BaseModel):
    """What the viewer chose for a video: a preset, one of their requests, or no cut."""

    preset: str | None = Field(None, max_length=64)
    request: str | None = Field(None, max_length=64)
    off: bool = False


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


class LedgerReport(BaseModel):
    """A client (TV, extension) reporting one of its own failures to the error ledger."""

    operation: str
    message: str
    video_id: str | None = None
    component: str | None = None  # "client" by default; "job"/"youtube"/... for server-side
    category: str | None = None  # optional hint; the backend categorises when omitted
    detail: str | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, value):
        if value is not None and value not in KNOWN_CATEGORIES:
            raise ValueError("category is not one of the known categories")
        return value


class ImportRequest(BaseModel):
    url: str


class DefaultRequest(BaseModel):
    key: str


class InboxIds(BaseModel):
    ids: list[int] = Field(default_factory=list, max_length=200)


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
    prime: bool = False
    password: str | None = Field(default=None, max_length=512)


class ProviderBody(BaseModel):
    """One user's own upstream: an OpenAI-compatible base url and the key that authenticates there.
    Sent by a user for themselves; the key is stored on the server, never returned."""

    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=4096)


class UserPatch(BaseModel):
    admin: bool | None = None
    prime: bool | None = None


class ResolveRequest(BaseModel):
    text: str = Field(max_length=1024)
