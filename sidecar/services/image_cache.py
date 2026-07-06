"""Disk cache for generated thumbnails and face crops (#114).

Every /photos/{id}/thumbnail and /faces/{id}/crop request used to decode the
full-resolution original (possibly over SMB for network roots) on every hit.
Generated JPEGs are now stored under {data_dir}/cache/ and served from disk
until the source photo's mtime changes.

The cache lives entirely inside the app data dir — photo files themselves are
never written, moved, or deleted (project invariant). The source mtime is
embedded in the cache filename, so a modified photo naturally misses the cache;
stale variants for the same key are removed on write.

Size is bounded by _CACHE_MAX_BYTES with oldest-first (mtime) eviction, checked
opportunistically every _EVICTION_CHECK_INTERVAL writes rather than per request.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading

logger = logging.getLogger(__name__)

_CACHE_SUBDIR = "cache"

# 2 GB default cap; make configurable via config.json when #107 lands.
_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
_EVICTION_CHECK_INTERVAL = 100

_write_count = 0
_evict_lock = threading.Lock()


def _cache_dir(kind: str) -> str:
    data_dir = os.environ.get("FACES_H_DATA_DIR", ".")
    d = os.path.join(data_dir, _CACHE_SUBDIR, kind)
    os.makedirs(d, exist_ok=True)
    return d


def cache_key(kind: str, entity_id: int, source_mtime: int, variant: str = "") -> str:
    """Absolute cache path for one generated image.

    The source mtime is part of the name: a modified photo misses the cache
    without any extra stat bookkeeping.
    """
    suffix = f"_{variant}" if variant else ""
    return os.path.join(_cache_dir(kind), f"{entity_id}{suffix}_{source_mtime}.jpg")


def get(path: str) -> bytes | None:
    """Return cached bytes, or None on miss. Never raises."""
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def put(path: str, data: bytes) -> None:
    """Write bytes to the cache atomically; drop stale variants of the same key.

    Best-effort: a full disk or permission error must never break image
    serving, so failures are logged and swallowed.
    """
    global _write_count
    try:
        directory = os.path.dirname(path)
        filename = os.path.basename(path)
        # "{id}[_{variant}]_{mtime}.jpg" → everything up to the mtime is the key.
        key_prefix = filename.rsplit("_", 1)[0] + "_"

        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

        for name in os.listdir(directory):
            if name.startswith(key_prefix) and name != filename and name.endswith(".jpg"):
                try:
                    os.remove(os.path.join(directory, name))
                except OSError:
                    pass

        _write_count += 1
        if _write_count % _EVICTION_CHECK_INTERVAL == 0:
            _evict_if_needed()
    except OSError as exc:
        logger.warning("image cache write failed for %s: %s", path, exc)


def _evict_if_needed(max_bytes: int | None = None) -> None:
    """Delete oldest cache files (by mtime) until total size fits the cap."""
    cap = max_bytes if max_bytes is not None else _CACHE_MAX_BYTES
    root = os.path.join(os.environ.get("FACES_H_DATA_DIR", "."), _CACHE_SUBDIR)
    if not _evict_lock.acquire(blocking=False):
        return  # another thread is already evicting
    try:
        entries: list[tuple[float, int, str]] = []
        total = 0
        for dirpath, _, filenames in os.walk(root):
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                entries.append((st.st_mtime, st.st_size, full))
                total += st.st_size
        if total <= cap:
            return
        entries.sort()  # oldest first
        for _, size, full in entries:
            try:
                os.remove(full)
                total -= size
            except OSError:
                continue
            if total <= cap:
                break
        logger.info("image cache evicted down to %d bytes", total)
    finally:
        _evict_lock.release()


def generate_thumbnail_bytes(photo_path: str, size: int) -> bytes:
    """Decode, orient, downscale, and JPEG-encode one photo (CPU-bound).

    Runs inside a worker thread (asyncio.to_thread) — PIL work in the event
    loop serialized every image request behind one core (#150).
    """
    import io  # noqa: PLC0415

    from PIL import Image, ImageOps  # noqa: PLC0415

    with Image.open(photo_path) as src_img:
        oriented = ImageOps.exif_transpose(src_img) or src_img
        rgb = oriented.convert("RGB")
        rgb.thumbnail((size, size))
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def warm_thumbnail(photo_id: int, photo_path: str, mtime: int, size: int = 256) -> None:
    """Pre-generate a photo's thumbnail into the disk cache (best effort).

    Called from the scanner right after a photo is processed so the first
    gallery visit is a cache read instead of a full-resolution decode (#150).
    """
    path = cache_key("thumbs", photo_id, mtime, variant=str(size))
    if os.path.exists(path):
        return
    try:
        put(path, generate_thumbnail_bytes(photo_path, size))
    except Exception as exc:  # noqa: BLE001 — warmup must never break a scan
        logger.debug("thumbnail warm failed for %s: %s", photo_path, exc)
