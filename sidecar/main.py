from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import platform
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.corrections import router as corrections_router
from api.faces import router as faces_router
from api.models import router as models_router
from api.people import router as people_router
from api.queue import router as queue_router
from api.scan import router as scan_router
from api.search import router as search_router

app = FastAPI(title="faces-h sidecar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router)
app.include_router(people_router)
app.include_router(queue_router)
app.include_router(faces_router)
app.include_router(search_router)
app.include_router(corrections_router)
app.include_router(models_router)


@app.get("/health")
async def health() -> dict:  # type: ignore[type-arg]
    return {"status": "ok"}


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

    if sys.stdout is not None and hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(fmt)
        root.addHandler(console)


def main() -> None:
    parser = argparse.ArgumentParser(description="faces-h Python sidecar")
    parser.add_argument("--port", type=int, default=51423)
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--app-version", type=str, default="unknown")
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("FACES_H_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

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
