from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
from collections import deque

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.corrections import router as corrections_router
from api.faces import router as faces_router
from api.models import router as models_router
from api.people import router as people_router
from api.photos import router as photos_router
from api.queue import router as queue_router
from api.backups import router as backups_router
from api.rotation import router as rotation_router
from api.scan import router as scan_router
from api.search import router as search_router
from api.transfer import router as transfer_router

app = FastAPI(title="faces-h sidecar", version="0.1.0")

# Populated at startup from the --token CLI arg.
_api_token: str = ""

# Public paths that never require a token (Tauri polls /health before
# emitting sidecar-ready, so it can't include the token yet).
_TOKEN_EXEMPT = {"/health", "/ws"}


@app.middleware("http")
async def require_token(request: Request, call_next):  # type: ignore[no-untyped-def]
    path = request.url.path
    if path not in _TOKEN_EXEMPT and _api_token:
        token = (
            request.headers.get("X-Faces-Token", "")
            or request.query_params.get("token", "")
        )
        if token != _api_token:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*", "X-Faces-Token"],
)

app.include_router(scan_router)
app.include_router(people_router)
app.include_router(photos_router)
app.include_router(queue_router)
app.include_router(rotation_router)
app.include_router(backups_router)
app.include_router(faces_router)
app.include_router(search_router)
app.include_router(corrections_router)
app.include_router(models_router)
app.include_router(transfer_router)


@app.get("/health")
async def health() -> dict:  # type: ignore[type-arg]
    return {"status": "ok"}


class WsLogHandler(logging.Handler):
    """Buffer engine log records for the UI activity log (#126).

    WARNING+ from every logger, plus INFO from the scanner/ML/clustering
    loggers users actually care about. uvicorn.access (per-request noise) and
    the websockets library logger (forwarding a failed WS send's own error
    would feed back into the WS) are excluded — but NOT uvicorn.error (#175):
    that's where unhandled exceptions in API endpoints get logged (a 500 the
    user should actually see), a distinct code path from WS send failures.
    Rate-limited so a log storm can't flood the socket; drops are counted and
    reported. The log files remain the complete record — this is a filtered
    live view.
    """

    _INFO_PREFIXES = ("services.", "ml.", "api.models", "__main__", "main")
    _EXCLUDED = ("uvicorn.access", "websockets")
    _MAX_PER_SECOND = 20

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.queue: deque[dict[str, object]] = deque(maxlen=200)
        self.dropped = 0
        self._window_start = 0.0
        self._window_count = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.name.startswith(self._EXCLUDED):
                return
            # ui_log_level (#143): "warning" → warnings+ only; "info"
            # (default) → warnings+ everywhere plus INFO from the interesting
            # loggers; "debug" → also DEBUG from those loggers. Read lazily so
            # a config edit takes effect on restart without touching code.
            from config import get_config  # noqa: PLC0415

            ui_level = get_config().ui_log_level
            if record.levelno < logging.WARNING:
                if ui_level == "warning":
                    return
                floor = logging.DEBUG if ui_level == "debug" else logging.INFO
                if record.levelno < floor or not record.name.startswith(
                    self._INFO_PREFIXES
                ):
                    return

            now = time.monotonic()
            if now - self._window_start >= 1.0:
                self._window_start = now
                self._window_count = 0
            if self._window_count >= self._MAX_PER_SECOND:
                self.dropped += 1
                return
            self._window_count += 1

            self.queue.append(
                {
                    "type": "log",
                    "source": "engine",
                    "level": record.levelname.lower(),
                    "message": record.getMessage(),
                    "logger": record.name,
                }
            )
        except Exception:  # noqa: BLE001 — a logging handler must never raise
            pass


_ws_log_handler = WsLogHandler()


@app.on_event("startup")
async def _purge_expired_backups() -> None:
    """Drop trash-backups past their retention window (#161) — cheap, once."""
    try:
        from services.backup import purge_old_backups  # noqa: PLC0415

        await asyncio.to_thread(purge_old_backups)
    except Exception:  # noqa: BLE001 — housekeeping must never block startup
        logging.getLogger(__name__).exception("backup purge failed")


@app.on_event("startup")
async def _start_log_pump() -> None:
    """Drain buffered log records to WebSocket clients twice a second."""

    async def _pump() -> None:
        from api.scan import broadcast_ws  # noqa: PLC0415 — avoid circular import

        while True:
            try:
                while _ws_log_handler.queue:
                    await broadcast_ws(_ws_log_handler.queue.popleft())
                if _ws_log_handler.dropped:
                    n, _ws_log_handler.dropped = _ws_log_handler.dropped, 0
                    await broadcast_ws(
                        {
                            "type": "log",
                            "source": "engine",
                            "level": "warning",
                            "message": f"…{n} log message(s) dropped (rate limit)",
                            "logger": "main",
                        }
                    )
            except Exception:  # noqa: BLE001 — the pump must survive anything
                pass
            await asyncio.sleep(0.5)

    asyncio.create_task(_pump())


def _setup_logging(data_dir: str, log_level: str = "INFO") -> None:
    """Configure rotating file logging to {data_dir}/logs/sidecar.log.

    5 MB per file, 3 backups kept. Console output is added when a TTY is
    attached (dev mode). uvicorn loggers propagate to the root logger so
    all server events appear in the same file.
    """
    log_dir = os.path.join(data_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        os.path.join(log_dir, "sidecar.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    root.addHandler(file_handler)
    # Live view for the in-app activity log (#126); drained by the pump task.
    root.addHandler(_ws_log_handler)

    if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)


def _parent_alive(parent_pid: int) -> bool:
    """Best-effort check that the Tauri shell that spawned us still exists.

    Falls back to True (assume alive) when psutil is unavailable or errors,
    so a broken probe can never take down a healthy sidecar.
    """
    try:
        import psutil  # noqa: PLC0415 — optional dependency, probed lazily
    except ImportError:
        return True
    try:
        return bool(psutil.pid_exists(parent_pid))
    except Exception:
        return True


def _start_parent_watchdog(parent_pid: int, poll_seconds: float = 2.0) -> None:
    """Exit the sidecar when the app that spawned it dies (#119).

    Covers force-kills of faces-h.exe where the window-close handler never
    runs — without this an orphan sidecar keeps the port and the SQLite WAL
    locked, breaking the next launch and in-place upgrades.
    """

    def _watch() -> None:
        logger = logging.getLogger(__name__)
        while True:
            if not _parent_alive(parent_pid):
                logger.warning(
                    "parent process %d exited — shutting down sidecar", parent_pid
                )
                os._exit(0)
            time.sleep(poll_seconds)

    threading.Thread(target=_watch, daemon=True, name="parent-watchdog").start()


def _run_selftest(image_path: str, data_dir: str, logger: logging.Logger) -> None:
    """Load the recognizer and run detection on one image, logging the outcome.

    Used to verify a frozen build's ML stack end-to-end without a full scan:
        faces-sidecar.exe --selftest path/to/photo.jpg --data-dir <dir>
    Results land in {data_dir}/logs/sidecar.log.
    """
    try:
        from config import get_config
        from ml.factory import get_recognizer

        recognizer = get_recognizer(get_config(), data_dir)
        results = recognizer.detect_and_embed(image_path)
        logger.info("selftest: detected %d face(s) in %s", len(results), image_path)
        for i, face in enumerate(results):
            logger.info(
                "selftest:   face %d — bbox=%s det_conf=%.3f", i, face.bbox, face.detection_confidence
            )
    except Exception:
        logger.exception("selftest: recognizer failed to initialise for %s", image_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="faces-h Python sidecar")
    parser.add_argument("--port", type=int, default=51423)
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--app-version", type=str, default="unknown")
    parser.add_argument("--token", type=str, default="", help="Shared secret required on X-Faces-Token header")
    parser.add_argument(
        "--parent-pid",
        type=int,
        default=0,
        help="PID of the app shell that spawned this sidecar; the sidecar exits "
        "when that process dies so no orphan holds the DB/port (#119).",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("FACES_H_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    parser.add_argument(
        "--selftest",
        type=str,
        default=None,
        metavar="IMAGE",
        help="Run face detection on a single image, log the result, and exit. "
        "Diagnostic for verifying the bundled ML stack works in a frozen build.",
    )
    args = parser.parse_args()

    global _api_token
    _api_token = args.token

    os.environ["FACES_H_DATA_DIR"] = args.data_dir
    os.makedirs(args.data_dir, exist_ok=True)

    _setup_logging(args.data_dir, args.log_level)

    logger = logging.getLogger(__name__)
    logger.info(
        "faces-h sidecar starting — version=%s port=%d data_dir=%s python=%s platform=%s",
        args.app_version,
        args.port,
        args.data_dir,
        sys.version.split()[0],
        platform.platform(),
    )

    if args.selftest is not None:
        _run_selftest(args.selftest, args.data_dir, logger)
        return

    if args.parent_pid > 0:
        _start_parent_watchdog(args.parent_pid)
        logger.info("parent watchdog active — following pid %d", args.parent_pid)

    db_path = os.path.join(args.data_dir, "faces.db")
    model_dir = os.path.join(args.data_dir, "models", "buffalo_l")
    model_ready = os.path.isdir(model_dir) and bool(os.listdir(model_dir)) if os.path.isdir(model_dir) else False
    logger.info(
        "startup state — db_exists=%s model_ready=%s",
        os.path.isfile(db_path),
        model_ready,
    )

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level=args.log_level.lower(),
        # Hand uvicorn log config to our root handler instead of its defaults.
        log_config=None,
    )


if __name__ == "__main__":
    main()
