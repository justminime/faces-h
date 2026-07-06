"""Tests for the engine→UI log bridge (#126)."""

import logging

from main import WsLogHandler


def _record(name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name=name, level=level, pathname="x.py", lineno=1, msg=msg, args=(), exc_info=None
    )


def test_forwards_warnings_from_any_logger() -> None:
    h = WsLogHandler()
    h.emit(_record("db.database", logging.WARNING, "migration failed"))
    assert len(h.queue) == 1
    entry = h.queue[0]
    assert entry["type"] == "log"
    assert entry["source"] == "engine"
    assert entry["level"] == "warning"
    assert entry["message"] == "migration failed"


def test_forwards_info_only_from_interesting_loggers() -> None:
    h = WsLogHandler()
    h.emit(_record("services.scanner", logging.INFO, "scan starting"))
    h.emit(_record("db.database", logging.INFO, "connection opened"))  # not surfaced
    assert [e["message"] for e in h.queue] == ["scan starting"]


def test_excludes_access_log_and_websockets_but_not_uvicorn_error() -> None:
    """Per-request access-log noise and the websockets library (forwarding a
    failed WS send's own error would feed back into itself) stay file-only —
    but uvicorn.error is where unhandled API exceptions get logged (#175),
    and a WARNING+ from there must reach the UI like any other logger."""
    h = WsLogHandler()
    h.emit(_record("uvicorn.access", logging.ERROR, "GET /x 500"))
    h.emit(_record("websockets.server", logging.ERROR, "send failed"))
    h.emit(_record("uvicorn.error", logging.WARNING, "boom"))
    assert [e["message"] for e in h.queue] == ["boom"]


def test_rate_limit_drops_and_counts() -> None:
    h = WsLogHandler()
    for i in range(50):
        h.emit(_record("services.scanner", logging.WARNING, f"warn {i}"))
    assert len(h.queue) == h._MAX_PER_SECOND
    assert h.dropped == 50 - h._MAX_PER_SECOND


def test_handler_never_raises() -> None:
    h = WsLogHandler()
    bad = _record("services.scanner", logging.WARNING, "%s %s")  # broken format
    bad.args = ("only-one",)
    h.emit(bad)  # must not raise


def _set_ui_log_level(tmp_path: object, level: str) -> None:
    import json
    import os
    from pathlib import Path

    from config import reset_config_cache

    Path(str(tmp_path), "config.json").write_text(
        json.dumps({"ui_log_level": level}), encoding="utf-8"
    )
    os.environ["FACES_H_DATA_DIR"] = str(tmp_path)
    reset_config_cache()


def test_ui_log_level_warning_suppresses_info(tmp_path: object) -> None:
    _set_ui_log_level(tmp_path, "warning")
    h = WsLogHandler()
    h.emit(_record("services.scanner", logging.INFO, "scan starting"))
    h.emit(_record("services.scanner", logging.WARNING, "still surfaced"))
    assert [e["message"] for e in h.queue] == ["still surfaced"]


def test_ui_log_level_debug_forwards_debug_from_interesting_loggers(
    tmp_path: object,
) -> None:
    _set_ui_log_level(tmp_path, "debug")
    h = WsLogHandler()
    h.emit(_record("services.scanner", logging.DEBUG, "verbose detail"))
    h.emit(_record("db.database", logging.DEBUG, "not interesting"))  # excluded
    assert [e["message"] for e in h.queue] == ["verbose detail"]


def test_ui_log_level_invalid_falls_back_to_info(tmp_path: object) -> None:
    _set_ui_log_level(tmp_path, "yelling")
    h = WsLogHandler()
    h.emit(_record("services.scanner", logging.INFO, "default behavior"))
    h.emit(_record("services.scanner", logging.DEBUG, "hidden at info"))
    assert [e["message"] for e in h.queue] == ["default behavior"]
