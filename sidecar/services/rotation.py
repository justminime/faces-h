"""Rotation suggestions and safe in-place rotation of originals (#160).

Rotating a photo is the second (and last) file-modifying carve-out from the
read-only invariant, and it is undoable by construction: the rotated image is
written to a temp file in the same folder, the ORIGINAL is moved to the
Recycle Bin, and the temp is renamed into place — restoring from the Bin
restores the untouched original. Network shares have no Recycle Bin, so the
original there is only removed when the caller explicitly allows a permanent
overwrite (the UI warns first, same pattern as #158).

Only JPEG and PNG are rewritten. RAW/HEIC/TIFF are never touched — rewriting
those safely is not possible with this stack.
"""

from __future__ import annotations

import io
import logging
import os

import piexif
from PIL import Image

from services.scanner import is_network_path

logger = logging.getLogger(__name__)

ROTATABLE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# EXIF orientation tag → degrees the pixels must be rotated CW to be upright.
# Mirrored orientations (2,4,5,7) are excluded — flipping is out of scope.
EXIF_ORIENTATION_TO_DEGREES = {3: 180, 6: 90, 8: 270}

# Degrees CW → PIL transpose op (PIL's ROTATE_* are counterclockwise).
_CW_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def read_exif_orientation(path: str) -> int | None:
    """EXIF orientation tag (1-8) for JPEG/TIFF files; None when absent."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in {".jpg", ".jpeg", ".tif", ".tiff"}:
        return None
    try:
        exif = piexif.load(path)
        value = exif.get("0th", {}).get(piexif.ImageIFD.Orientation)
        return int(value) if value else None
    except Exception:  # noqa: BLE001 — malformed EXIF must not break a scan
        return None


def probe_rotation(thumb_jpeg: bytes, recognizer: object, tmp_dir: str) -> int | None:
    """Try 90/180/270° on a thumbnail; return the CW rotation revealing the
    most faces, or None. Sideways photos are exactly the ones upright face
    detection misses, so faces appearing after rotation is a strong signal."""
    os.makedirs(tmp_dir, exist_ok=True)
    best_degrees: int | None = None
    best_faces = 0
    try:
        with Image.open(io.BytesIO(thumb_jpeg)) as img:
            base = img.convert("RGB")
            for degrees, op in _CW_TRANSPOSE.items():
                probe_path = os.path.join(tmp_dir, f"probe_{degrees}.jpg")
                base.transpose(op).save(probe_path, format="JPEG", quality=90)
                try:
                    faces = recognizer.detect_and_embed(probe_path)  # type: ignore[attr-defined]
                finally:
                    try:
                        os.remove(probe_path)
                    except OSError:
                        pass
                if len(faces) > best_faces:
                    best_faces = len(faces)
                    best_degrees = degrees
    except Exception:  # noqa: BLE001 — probing must never break the analysis run
        return None
    return best_degrees if best_faces > 0 else None


def _reset_orientation(exif_bytes: bytes | None) -> bytes | None:
    """Return EXIF bytes with the orientation tag reset to 1 (upright)."""
    if not exif_bytes:
        return None
    try:
        exif = piexif.load(exif_bytes)
        exif.setdefault("0th", {})[piexif.ImageIFD.Orientation] = 1
        result: bytes = piexif.dump(exif)
        return result
    except Exception:  # noqa: BLE001 — keep the pixels even if EXIF is hopeless
        return None


def rotate_original(path: str, degrees: int, allow_permanent_on_network: bool) -> str:
    """Rotate the original file by `degrees` CW, keeping the old version safe.

    Returns "recycled" (original in the Recycle Bin) or "permanent" (network
    fallback). Raises ValueError for unsupported formats/degrees and OSError
    when the original cannot be secured — in which case the file on disk is
    untouched.
    """
    if degrees not in _CW_TRANSPOSE:
        raise ValueError(f"Unsupported rotation: {degrees}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in ROTATABLE_EXTENSIONS:
        raise ValueError(f"Format not safely rewritable: {ext}")

    tmp_path = path + ".rotating.tmp"
    with Image.open(path) as img:
        fmt = img.format or ("PNG" if ext == ".png" else "JPEG")
        exif_bytes = _reset_orientation(img.info.get("exif"))
        icc = img.info.get("icc_profile")
        rotated = img.transpose(_CW_TRANSPOSE[degrees])
        save_kwargs: dict[str, object] = {"format": fmt}
        if fmt == "JPEG":
            # Carry the ORIGINAL's quantization tables + subsampling to the
            # transposed copy (transpose() drops JPEG metadata, so PIL's
            # quality='keep' shortcut can't be used) — the closest a
            # re-encode gets to lossless without libjpeg's jpegtran.
            qtables = getattr(img, "quantization", None)
            if qtables:
                save_kwargs["qtables"] = qtables
            else:
                save_kwargs["quality"] = 95
            try:
                from PIL import JpegImagePlugin  # noqa: PLC0415

                sampling = JpegImagePlugin.get_sampling(img)
                if sampling >= 0:
                    save_kwargs["subsampling"] = sampling
            except Exception:  # noqa: BLE001
                pass
        if exif_bytes:
            save_kwargs["exif"] = exif_bytes
        if icc:
            save_kwargs["icc_profile"] = icc
        rotated.save(tmp_path, **save_kwargs)  # type: ignore[arg-type]

    # Secure the original BEFORE replacing it — undo lives in the Recycle Bin.
    mode = "recycled"
    try:
        from send2trash import send2trash  # noqa: PLC0415

        send2trash(path)
    except Exception as exc:  # noqa: BLE001 — network fallback below
        if allow_permanent_on_network and is_network_path(path):
            # No Recycle Bin on network shares — copy the original into the
            # app's structure-mirroring backup folder first (#161), so the
            # rotation stays undoable for the retention window.
            from services.backup import backup_file  # noqa: PLC0415

            backup_file(path)
            os.remove(path)
            mode = "permanent"
        else:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise OSError(f"could not secure original before rotation: {exc}") from exc

    os.replace(tmp_path, path)
    logger.info("rotated %s by %d° CW (original %s)", path, degrees, mode)
    return mode


def rotated_size_check(before: tuple[int, int], after: tuple[int, int], degrees: int) -> bool:
    """Test helper: 90/270 swap dimensions, 180 keeps them."""
    if degrees in (90, 270):
        return (before[1], before[0]) == after
    return before == after


def upright_thumbnail_probe_order() -> list[int]:
    """Degrees tried by the probe, exposed for tests/documentation."""
    return sorted(_CW_TRANSPOSE)
