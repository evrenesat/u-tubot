from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel


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
    lang: str = "auto"
    translate_to: str | None = None


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
    duration_s: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if v is not None}
