"""The owner's Stremio account for the films library: log in and import the watch state.

The server logs in with the owner's email and password, keeps only the returned auth key (encrypted
in the secret store, ``films_stremio_auth``), and never stores or logs the password. The import reads
the library with that key and returns the mapped titles and the counts; the TV applies them to its
own films store, so the auth key never leaves the server.

Endpoints:
- ``POST /v1/films/stremio/login``     ``{"email","password"}`` -> sign in, keep the auth key.
- ``POST /v1/films/stremio/import``    read the library, map it, return the items and the counts.
- ``GET  /v1/films/stremio/status``    ``{"set":true|false}`` whether the account is connected.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .stremio import StremioClient, map_library

MAX_EMAIL_CHARS = 254
MAX_PASSWORD_CHARS = 512
STREMIO_SECRET = "films_stremio_auth"
STATUS_BY_REASON = {"auth": 400, "service": 502, "format": 502}


def install_stremio_routes(app: FastAPI, d: Any) -> None:
    svc = d.svc
    current_user = d.current_user
    secrets = svc.secrets

    def client() -> StremioClient:
        return StremioClient(svc.cfg.films.stremio, transport=svc.stremio_transport)

    def refused(reason: str) -> int:
        return STATUS_BY_REASON.get(reason, 502)

    def stremio_error(exc: Any) -> JSONResponse:
        # A StremioError carries a plain, user-facing message and a reason; the password never
        # reaches the response.
        return JSONResponse({"error": exc.message}, status_code=refused(exc.reason))

    def email_ok(value: str) -> bool:
        value = (value or "").strip()
        return "@" in value and 1 <= len(value) <= MAX_EMAIL_CHARS

    def password_ok(value: Any) -> bool:
        return isinstance(value, str) and 1 <= len(value) <= MAX_PASSWORD_CHARS

    @app.post("/v1/films/stremio/login")
    async def stremio_login(
        body: dict[str, Any], request: Request, user=Depends(current_user)
    ) -> dict[str, Any]:
        """Sign in to Stremio and keep the auth key. The password is never stored or returned."""
        if not email_ok(body.get("email")) or not password_ok(body.get("password")):
            return JSONResponse(
                {"error": "Enter your Stremio email and password."}, status_code=400
            )

        try:
            auth_key = client().login(body["email"].strip(), body["password"])
        except Exception as exc:  # noqa: BLE001 - StremioError is the only raised type
            if isinstance(exc, str):
                return JSONResponse({"error": exc}, status_code=400)
            return stremio_error(exc)

        # Stored encrypted, like the other films secrets, but kept on the server only: the import
        # runs here and the TV never receives the auth key.
        secrets.set(user.name, STREMIO_SECRET, auth_key, via="web", by=user.name)
        return {"ok": True}

    @app.post("/v1/films/stremio/import")
    async def stremio_import(request: Request, user=Depends(current_user)) -> dict[str, Any]:
        """The mapped library and the counts: watchlist, resume positions, watched marks, unmapped."""
        auth_key = secrets.get(user.name, STREMIO_SECRET) if secrets is not None else None

        if not auth_key:
            return JSONResponse({"error": "Connect your Stremio account first."}, status_code=400)

        try:
            payload = client().library(auth_key)
        except Exception as exc:  # noqa: BLE001
            return stremio_error(exc)

        items, unmapped = map_library(payload)
        watched = sum(1 for item in items if item.watched)
        resume = sum(1 for item in items if item.position_ms > 0)
        return {
            "watchlist": len(items),
            "resume": resume,
            "watched": watched,
            "unmapped": unmapped,
            "items": [
                {
                    "id": item.id,
                    "type": item.type,
                    "title_id": item.title_id,
                    "name": item.name,
                    "poster": item.poster,
                    "season": item.season,
                    "episode": item.episode,
                    "position_ms": item.position_ms,
                    "watched": item.watched,
                    "last_watched": item.last_watched,
                }
                for item in items
            ],
        }

    @app.get("/v1/films/stremio/status")
    async def stremio_status(user=Depends(current_user)) -> dict[str, bool]:
        connected = False

        if secrets is not None:
            connected = bool(secrets.get(user.name, STREMIO_SECRET))

        return {"set": connected}
