"""Scan API router: HTTP endpoints and WebSocket for scan progress."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from db.database import get_db
from services.scanner import get_status, run_scan

router = APIRouter()
logger = logging.getLogger(__name__)


class _ConnectionManager:
    """Tracks active WebSocket connections and broadcasts JSON messages to all."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(json.dumps(message))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_manager = _ConnectionManager()


async def broadcast_ws(message: dict[str, Any]) -> None:
    """Broadcast a JSON message to all connected WebSocket clients."""
    await _manager.broadcast(message)


class StartScanRequest(BaseModel):
    root_path: str


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await _manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _manager.disconnect(ws)


@router.post("/scan/start")
async def start_scan(body: StartScanRequest) -> dict[str, str]:
    if get_status().running:
        logger.info("scan/start: already running — ignoring request for %s", body.root_path)
        return {"status": "already_running"}

    logger.info("scan/start: root_path=%s", body.root_path)

    async def _run() -> None:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO scan_roots(path, added_at) VALUES(?, ?) ON CONFLICT(path) DO NOTHING",
                (body.root_path, int(time.time())),
            )
            await db.commit()
            logger.info("scan starting: root=%s", body.root_path)
            await run_scan(body.root_path, _manager.broadcast, db)
            logger.info("scan finished: root=%s", body.root_path)

    asyncio.create_task(_run())
    return {"status": "started"}


@router.post("/scan/rescan")
async def rescan_all() -> dict[str, str]:
    """Re-scan every root folder that has been added previously."""
    if get_status().running:
        logger.info("scan/rescan: already running — ignoring")
        return {"status": "already_running"}

    async def _run() -> None:
        async with get_db() as db:
            cur = await db.execute("SELECT path FROM scan_roots ORDER BY added_at")
            roots = [row["path"] for row in await cur.fetchall()]
        logger.info("scan/rescan: %d root(s) — %s", len(roots), roots)
        if not roots:
            await _manager.broadcast({"type": "scan_complete"})
            return
        for root in roots:
            async with get_db() as db:
                logger.info("scan starting: root=%s", root)
                await run_scan(root, _manager.broadcast, db)
                logger.info("scan finished: root=%s", root)

    asyncio.create_task(_run())
    return {"status": "started"}


@router.get("/scan/roots")
async def list_roots() -> list[dict[str, Any]]:
    """Return all configured scan root folders."""
    async with get_db() as db:
        cur = await db.execute("SELECT id, path, added_at FROM scan_roots ORDER BY added_at")
        rows = await cur.fetchall()
        return [{"id": row["id"], "path": row["path"], "added_at": row["added_at"]} for row in rows]


@router.get("/scan/status")
async def scan_status() -> dict[str, Any]:
    s = get_status()
    return {
        "running": s.running,
        "paused": s.paused,
        "root_path": s.root_path,
        "total": s.total,
        "scanned": s.scanned,
        "skipped": s.skipped,
        "error_count": s.error_count,
        "eta_seconds": s.eta_seconds(),
    }


@router.post("/scan/pause")
async def pause_scan() -> dict[str, str]:
    get_status().paused = True
    return {"status": "paused"}


@router.post("/scan/resume")
async def resume_scan() -> dict[str, str]:
    get_status().paused = False
    return {"status": "resumed"}
