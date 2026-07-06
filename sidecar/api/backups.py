"""Backup listing and restore API (#161/#162)."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.database import get_db
from services.backup import list_backups, restore_backup

router = APIRouter(prefix="/backups", tags=["backups"])
logger = logging.getLogger(__name__)


@router.get("")
async def get_backups() -> list[dict[str, Any]]:
    """Pre-deletion backups still inside their retention window, newest first."""
    entries = await asyncio.to_thread(list_backups)
    for e in entries:
        original = str(e["original_path"])
        e["filename"] = os.path.basename(original)
        e["folder"] = os.path.dirname(original)
    return entries


class RestoreRequest(BaseModel):
    backup: str
    confirmed: bool = False


@router.post("/restore")
async def restore(body: RestoreRequest) -> dict[str, Any]:
    """Copy a backup back to its original location (#162).

    Overwrites whatever currently sits there — the backup is the version the
    user chose to bring back. The matching DB row (if any) is revived and
    queued for re-analysis so the next scan re-processes the file.
    """
    if not body.confirmed:
        raise HTTPException(status_code=400, detail="confirmed must be true")
    try:
        restored_path = await asyncio.to_thread(restore_backup, body.backup)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Backup not found") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Restore failed: {exc}") from exc

    async with get_db() as db:
        try:
            st = os.stat(restored_path)
            await db.execute(
                """UPDATE photos
                      SET missing = 0, faces_extracted = 0, mtime = ?,
                          file_size = ?, blur_score = NULL, phash = NULL,
                          content_hash = NULL
                    WHERE path = ?""",
                (int(st.st_mtime), int(st.st_size), restored_path),
            )
            await db.commit()
        except OSError:
            pass

    logger.info("backup restored to %s", restored_path)
    return {"restored": restored_path}
