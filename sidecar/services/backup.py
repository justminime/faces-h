"""Pre-deletion backups for files without a Recycle Bin (#161).

Network shares have no Recycle Bin, so before the app deletes or overwrites a
file there, a copy lands in {data_dir}/trash-backup/ — mirroring the
original folder structure (\\\\nas\\Family\\2025\\x.jpg →
trash-backup/nas/Family/2025/x.jpg) so restores are unambiguous. That keeps
EVERY file-modifying action undoable: local files restore from the Recycle
Bin, network files restore from this folder. Backups are purged after
config.backup_retention_days (default 7) — checked at sidecar startup and
before each new backup; emptied folders are cleaned up with them.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time

logger = logging.getLogger(__name__)

_BACKUP_SUBDIR = "trash-backup"


def backup_dir() -> str:
    d = os.path.join(os.environ.get("FACES_H_DATA_DIR", "."), _BACKUP_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _mirrored_path(path: str) -> str:
    """Map an absolute source path to its mirrored location in the backup dir.

    UNC prefixes are stripped and drive colons dropped:
      \\\\nas\\share\\a\\b.jpg → {backup}/nas/share/a/b.jpg
      C:\\photos\\a\\b.jpg     → {backup}/C/photos/a/b.jpg
    """
    normalized = path.replace("/", "\\").lstrip("\\")
    normalized = normalized.replace(":", "")
    # Guard against weird segments that could escape the backup root.
    parts = [p for p in normalized.split("\\") if p not in ("", ".", "..")]
    safe = [re.sub(r'[<>:"|?*]', "_", p) for p in parts]
    return os.path.join(backup_dir(), *safe)


def backup_file(path: str) -> str:
    """Copy a file into the backup mirror; returns the backup path.

    Raises OSError when the copy fails — callers must then abort the
    destructive action so nothing is ever lost without a safety copy.
    """
    purge_old_backups()
    dest = _mirrored_path(path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(dest)
        dest = f"{stem}.{time.strftime('%Y%m%d-%H%M%S')}{ext}"
    shutil.copy2(path, dest)
    record_backup(dest, path)
    logger.info("backed up %s -> %s (kept %d days)", path, dest, _retention_days())
    return dest


def _retention_days() -> int:
    from config import get_config  # noqa: PLC0415

    return get_config().backup_retention_days


def purge_old_backups(retention_days: int | None = None) -> int:
    """Delete backups older than the retention window; returns count removed.

    Emptied directories are removed too, keeping the mirror tidy.
    """
    days = retention_days if retention_days is not None else _retention_days()
    cutoff = time.time() - days * 86_400
    removed = 0
    root = backup_dir()
    try:
        for dirpath, _dirnames, filenames in os.walk(root, topdown=False):
            for name in filenames:
                if dirpath == root and name == _MANIFEST:
                    continue
                full = os.path.join(dirpath, name)
                try:
                    if os.path.getmtime(full) < cutoff:
                        os.remove(full)
                        removed += 1
                except OSError:
                    continue
            if dirpath != root:
                try:
                    os.rmdir(dirpath)  # only succeeds when empty
                except OSError:
                    pass
    except OSError:
        return removed
    if removed:
        manifest = _load_manifest()
        pruned = {
            rel: orig
            for rel, orig in manifest.items()
            if os.path.isfile(os.path.join(root, rel))
        }
        if len(pruned) != len(manifest):
            _save_manifest(pruned)
        logger.info("purged %d expired backup(s) (older than %d days)", removed, days)
    return removed


_MANIFEST = "backups.json"


def _manifest_path() -> str:
    return os.path.join(backup_dir(), _MANIFEST)


def _load_manifest() -> dict[str, str]:
    import json  # noqa: PLC0415

    try:
        with open(_manifest_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_manifest(manifest: dict[str, str]) -> None:
    import json  # noqa: PLC0415

    try:
        with open(_manifest_path(), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=1)
    except OSError as exc:
        logger.warning("backup manifest write failed: %s", exc)


def record_backup(backup_path: str, original_path: str) -> None:
    """Remember where a backup came from so it can be restored (#162)."""
    rel = os.path.relpath(backup_path, backup_dir())
    manifest = _load_manifest()
    manifest[rel] = original_path
    _save_manifest(manifest)


def list_backups() -> list[dict[str, object]]:
    """Existing backups with their origins, newest first."""
    manifest = _load_manifest()
    entries: list[tuple[int, dict[str, object]]] = []
    retention = _retention_days()
    for rel, original in manifest.items():
        full = os.path.join(backup_dir(), rel)
        try:
            st = os.stat(full)
        except OSError:
            continue  # purged or manually removed
        age_days = (time.time() - st.st_mtime) / 86_400
        backed_up_at = int(st.st_mtime)
        entries.append(
            (
                backed_up_at,
                {
                    "backup": rel,
                    "original_path": original,
                    "file_size": int(st.st_size),
                    "backed_up_at": backed_up_at,
                    "expires_in_days": max(0, round(retention - age_days, 1)),
                },
            )
        )
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return [entry for _, entry in entries]


def restore_backup(rel: str) -> str:
    """Copy a backup back to its original location; returns the restored path.

    Overwrites whatever currently sits at the original path — the backup is
    the version the user chose to bring back. Raises OSError/KeyError on
    failure; the backup copy itself is kept until it expires naturally.
    """
    manifest = _load_manifest()
    if rel not in manifest:
        raise KeyError(f"unknown backup: {rel}")
    src = os.path.join(backup_dir(), rel)
    if not os.path.isfile(src):
        raise OSError(f"backup file missing: {rel}")
    dest = manifest[rel]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(src, dest)
    logger.info("restored backup %s -> %s", rel, dest)
    return dest
