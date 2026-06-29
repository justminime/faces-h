"""Verify rotating log file setup for the sidecar."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys


# Add sidecar root to path so we can import main directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import _setup_logging  # noqa: E402


def test_log_file_created(tmp_path: object) -> None:
    """_setup_logging creates sidecar.log inside {data_dir}/logs/."""
    # Reset root logger between test runs
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    try:
        data_dir = str(tmp_path)
        _setup_logging(data_dir)

        log_path = os.path.join(data_dir, "logs", "sidecar.log")
        assert os.path.isfile(log_path), f"Expected log file at {log_path}"
    finally:
        root.handlers = original_handlers


def test_log_file_is_rotating(tmp_path: object) -> None:
    """The file handler is a RotatingFileHandler with 5 MB cap and 3 backups."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    try:
        _setup_logging(str(tmp_path))

        file_handlers = [
            h for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
        ]
        assert file_handlers, "No RotatingFileHandler registered"
        handler = file_handlers[0]
        assert handler.maxBytes == 5 * 1024 * 1024, (
            f"Expected maxBytes=5242880, got {handler.maxBytes}"
        )
        assert handler.backupCount == 3, (
            f"Expected backupCount=3, got {handler.backupCount}"
        )
    finally:
        root.handlers = original_handlers


def test_log_writes_appear_in_file(tmp_path: object) -> None:
    """Messages logged after setup appear in sidecar.log."""
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    root.handlers.clear()

    try:
        data_dir = str(tmp_path)
        _setup_logging(data_dir)

        logging.getLogger("test.sidecar").info("hello from test")

        # Flush all handlers
        for h in logging.getLogger().handlers:
            h.flush()

        log_path = os.path.join(data_dir, "logs", "sidecar.log")
        content = open(log_path, encoding="utf-8").read()
        assert "hello from test" in content, (
            "Log message not found in sidecar.log"
        )
    finally:
        root.handlers = original_handlers
