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
from api.photos import router as photos_router
from api.queue import router as queue_router
from api.scan import router as scan_router
from api.search import router as search_router
from api.transfer import router as transfer_router

app = FastAPI(title="faces-h sidecar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router)
app.include_router(people_router)
app.include_router(photos_router)
app.include_router(queue_router)
app.include_router(faces_router)
app.include_router(search_router)
app.include_router(corrections_router)
app.include_router(models_router)
app.include_router(transfer_router)


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


def _run_selftest(image_path: str, data_dir: str, logger: logging.Logger) -> None:
    """Load the recognizer and run detection on one image, logging the outcome.

    Used to verify a frozen build's ML stack end-to-end without a full scan:
        faces-sidecar.exe --selftest path/to/photo.jpg --data-dir <dir>
    Results land in {data_dir}/logs/sidecar.log.
    """
    try:
        from ml.insightface_recognizer import InsightFaceRecognizer

        recognizer = InsightFaceRecognizer(data_dir)
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
