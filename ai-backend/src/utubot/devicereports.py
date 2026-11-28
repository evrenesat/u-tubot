"""Crash reports and player logs a TV uploads: stored per user and device, kept for a while, read from the CLI.

The TV redacts what must not leave it (stream addresses, tokens) before it sends; the server stores the report as it came and never
logs its content.
"""

from __future__ import annotations

import gzip
import json
import time
import zlib
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import ReportsConfig
from .db import Database

MAX_FIELD_CHARS = 120
SECONDS_PER_DAY = 86400.0


class ReportRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def unpack(body: bytes, gzipped: bool, limit: int) -> dict[str, Any]:
    """The JSON object of an upload; refused when it is too large (also once unpacked), not gzip or not an object."""
    if len(body) > limit:
        raise ReportRefused(413, "the report is too large")
    if gzipped:
        try:
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            body = decoder.decompress(body, limit + 1)
            if decoder.unconsumed_tail or len(body) > limit:
                raise ReportRefused(413, "the report is too large")
        except zlib.error:
            raise ReportRefused(400, "the body is not gzip") from None
    try:
        doc = json.loads(body)
    except ValueError:
        raise ReportRefused(400, "the body is not JSON") from None
    if not isinstance(doc, dict):
        raise ReportRefused(400, "the report must be a JSON object")
    return doc


def _count(doc: dict[str, Any], kind: str) -> int:
    failures = doc.get("failures")
    if not isinstance(failures, list):
        return 0
    return sum(1 for f in failures if isinstance(f, dict) and f.get("kind") == kind)


def _count_errors(doc: dict[str, Any]) -> int:
    failures = doc.get("failures")
    if not isinstance(failures, list):
        return 0
    return sum(
        1 for f in failures if isinstance(f, dict) and str(f.get("kind", "")).endswith("error")
    )


def _text(value: Any) -> str:
    return str(value)[:MAX_FIELD_CHARS] if value is not None else ""


class DeviceReports:
    def __init__(self, cfg: ReportsConfig, db: Database, clock=time.time):
        self.cfg, self.db, self.clock = cfg, db, clock

    def save(self, user: str, device_id: str, device_name: str, doc: dict[str, Any]) -> int:
        raw = json.dumps(doc, separators=(",", ":")).encode()
        packed = gzip.compress(raw)
        app = doc.get("app")
        version = _text(app.get("version")) if isinstance(app, dict) else ""
        now = self.clock()
        new_id = self.db.execute_id(
            "INSERT INTO device_reports(user,device_id,device_name,received_at,app_version,crashes,anrs,errors,size,body) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                user,
                device_id,
                device_name,
                now,
                version,
                _count(doc, "crash"),
                _count(doc, "anr"),
                _count_errors(doc),
                len(raw),
                packed,
            ],
        )
        self.prune(user)
        return new_id

    def prune(self, user: str) -> None:
        self.db.execute(
            "DELETE FROM device_reports WHERE received_at<?",
            [self.clock() - self.cfg.keep_days * SECONDS_PER_DAY],
        )
        rows = self.db.all(
            "SELECT id, LENGTH(body) n FROM device_reports WHERE user=? ORDER BY id DESC", [user]
        )
        total = 0
        for row in rows:
            total += int(row["n"])
            if total > self.cfg.max_bytes_per_user:
                self.db.execute(
                    "DELETE FROM device_reports WHERE user=? AND id<=?", [user, row["id"]]
                )
                break

    def list(self, user: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        where, args = ("WHERE user=?", [user]) if user else ("", [])
        rows = self.db.all(
            "SELECT id,user,device_id,device_name,received_at,app_version,crashes,anrs,errors,size "
            f"FROM device_reports {where} ORDER BY id DESC LIMIT ?",
            [*args, limit],
        )
        return [dict(r) for r in rows]

    def get(self, report_id: int) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM device_reports WHERE id=?", [report_id])
        if row is None:
            return None
        meta = {k: row[k] for k in row.keys() if k != "body"}
        return {**meta, "report": json.loads(gzip.decompress(row["body"]))}

    def counts(self, user: str | None = None, days: int = 7) -> dict[str, int]:
        since = self.clock() - days * SECONDS_PER_DAY
        where, args = ("AND user=?", [user]) if user else ("", [])
        row = self.db.one(
            "SELECT COUNT(*) reports, COALESCE(SUM(crashes),0) crashes, COALESCE(SUM(anrs),0) anrs "
            f"FROM device_reports WHERE received_at>=? {where}",
            [since, *args],
        )
        return {
            "days": days,
            "reports": int(row["reports"]),
            "crashes": int(row["crashes"]),
            "anrs": int(row["anrs"]),
        }


NO_DEVICE = "this route is for a paired TV; a browser session or config token has no device"


def install_report_routes(app: FastAPI, d: Any) -> None:
    svc = d.svc
    current_user = d.current_user

    @app.post("/v1/device/reports")
    async def device_reports_post(request: Request, user=Depends(current_user)):
        """A TV's crash reports and player log, gzip or plain JSON; the answer is the id once stored."""
        device_id = svc.auth.device_id_of(getattr(request.state, "principal", None))
        if device_id is None:
            raise HTTPException(400, NO_DEVICE)
        limit = svc.cfg.reports.max_report_bytes
        gzipped = request.headers.get("content-encoding", "").lower() == "gzip"
        body = bytearray()
        async for chunk in request.stream():
            body += chunk
            if len(body) > limit:
                return JSONResponse({"error": "the report is too large"}, status_code=413)
        try:
            doc = unpack(bytes(body), gzipped, limit)
        except ReportRefused as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status)
        names = {dev["id"]: dev["device"] for dev in svc.auth.list_devices(user.name)}
        report_id = svc.device_reports.save(user.name, device_id, names.get(device_id, ""), doc)
        return {"id": str(report_id)}
