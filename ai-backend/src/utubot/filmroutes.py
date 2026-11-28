"""The TV's subtitle picker for a film: a list of subtitles for the stream, and one of them as WebVTT.

The TV asks the server, which already has the add-on client and its cache (`films.py`), instead of
holding a second client. Only the IMDb id, season and episode, the stream's file name and size and the
viewer's language reach the add-on; the TV names a subtitle by the id of the list, never by an address.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Query
from fastapi.responses import JSONResponse, Response

from .films import FilmRefused, film_source

MAX_LANG_CHARS = 16
MAX_FILE_NAME_CHARS = 400
MAX_SUBTITLE_ID_CHARS = 64
STATUS_BY_REASON = {"none": 404, "service": 502}


def install_film_routes(app: FastAPI, d: Any) -> None:
    svc = d.svc
    current_user = d.current_user

    def source_of(source_key: str, file_name: str):
        try:
            return film_source(source_key, file_name)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    def refused(exc: FilmRefused) -> JSONResponse:
        return JSONResponse(
            {"error": exc.message}, status_code=STATUS_BY_REASON.get(exc.reason, 502)
        )

    @app.get("/v1/films/subtitles")
    async def film_subtitles(
        source_key: str = Query(..., max_length=64),
        file_name: str = Query(..., min_length=1, max_length=MAX_FILE_NAME_CHARS),
        size: int | None = Query(None, ge=0),
        lang: str | None = Query(None, max_length=MAX_LANG_CHARS),
        user=Depends(current_user),
    ):
        """`{"subtitles":[{"id","lang","name","score","hash_match","best"?}]}`: the viewer's language, then English."""
        source = source_of(source_key, file_name)
        if isinstance(source, JSONResponse):
            return source
        try:
            listed = await svc.cuts.films.listing(
                source, file_name=file_name, size_bytes=size, preferred_language=lang
            )
        except FilmRefused as exc:
            return refused(exc)
        return {"subtitles": listed}

    @app.get("/v1/films/subtitles/{subtitle}.vtt")
    async def film_subtitle_file(
        subtitle: str,
        source_key: str = Query(..., max_length=64),
        file_name: str = Query(..., min_length=1, max_length=MAX_FILE_NAME_CHARS),
        size: int | None = Query(None, ge=0),
        user=Depends(current_user),
    ):
        if not subtitle or len(subtitle) > MAX_SUBTITLE_ID_CHARS:
            return JSONResponse({"error": "unknown subtitle"}, status_code=404)
        source = source_of(source_key, file_name)
        if isinstance(source, JSONResponse):
            return source
        try:
            body = await svc.cuts.films.webvtt_of(
                source, file_name=file_name, size_bytes=size, subtitle=subtitle
            )
        except FilmRefused as exc:
            return refused(exc)
        return Response(body, media_type="text/vtt; charset=utf-8")
