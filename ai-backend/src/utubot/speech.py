"""Voice prompts: the phone's recording becomes text through modelgate only.

The audio is posted here as multipart, sent on to modelgate's `POST /v1/audio/transcriptions`
with the configured alias (EVR-464), and only the text comes back. Nothing is stored: no file,
no transcript row, no log of the bytes or the words; the log keeps the client, alias, size and
duration.
"""

from __future__ import annotations

import logging
import time

import httpx

from .config import Config

log = logging.getLogger("utubot.speech")

MSG_NOT_CONFIGURED = "Speech is not configured on this server; type the cut instead."
MSG_BUSY = "Speech service is busy, try again or type it."
MSG_FAILED = "Speech could not be transcribed, try again or type it."
MSG_EMPTY = "The recording was empty; try again or type it."
MSG_TOO_LARGE = "The recording is too long or too large; try again or type it."


class SpeechError(RuntimeError):
    """Speech failed; `message` is the plain reason shown to the owner."""

    def __init__(self, message: str, *, status: int = 503):
        super().__init__(message)
        self.message = message
        self.status = status


class SpeechService:
    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._http = httpx.AsyncClient(timeout=cfg.speech.timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    @property
    def configured(self) -> bool:
        return bool(self.cfg.speech.alias.strip())

    def limit_bytes(self) -> int:
        return self.cfg.speech.max_upload_bytes

    async def transcribe(
        self,
        audio: bytes,
        filename: str = "recording",
        content_type: str = "application/octet-stream",
    ) -> str:
        """The text of one recording; a plain error when modelgate cannot answer."""
        speech = self.cfg.speech

        if not self.configured:
            raise SpeechError(MSG_NOT_CONFIGURED, status=503)
        if not audio:
            raise SpeechError(MSG_EMPTY, status=400)
        if len(audio) > speech.max_upload_bytes:
            raise SpeechError(MSG_TOO_LARGE, status=413)
        provider = speech.provider or self.cfg.llm.default_provider
        provider_cfg = self.cfg.llm.providers.get(provider)
        if provider_cfg is None:
            raise SpeechError(MSG_FAILED, status=503)

        url = provider_cfg.base_url.rstrip("/") + "/audio/transcriptions"
        headers = {}
        key = self.cfg.api_key(provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        data = {"model": speech.alias}
        if speech.language:
            data["language"] = speech.language

        started = time.monotonic()
        try:
            resp = await self._http.post(
                url,
                headers=headers,
                data=data,
                files={"file": (filename, audio, content_type)},
            )
        except httpx.TimeoutException as exc:
            log.warning("speech timed out: alias=%s bytes=%s", speech.alias, len(audio))
            raise SpeechError(MSG_BUSY, status=503) from exc
        except httpx.HTTPError as exc:
            log.warning(
                "speech transport error: alias=%s bytes=%s error=%s",
                speech.alias,
                len(audio),
                type(exc).__name__,
            )
            raise SpeechError(MSG_FAILED, status=502) from exc
        finally:
            log.info(
                "speech: alias=%s bytes=%s duration=%.2fs",
                speech.alias,
                len(audio),
                time.monotonic() - started,
            )

        if resp.status_code in (429, 503, 504):
            raise SpeechError(MSG_BUSY, status=503)
        if resp.status_code == 413:
            raise SpeechError(MSG_TOO_LARGE, status=413)
        if resp.status_code >= 400:
            raise SpeechError(MSG_FAILED, status=502)

        try:
            text = resp.json().get("text")
        except (ValueError, AttributeError) as exc:
            raise SpeechError(MSG_FAILED, status=502) from exc
        if not isinstance(text, str):
            raise SpeechError(MSG_FAILED, status=502)
        return text.strip()
