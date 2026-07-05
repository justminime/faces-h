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


def test_excludes_uvicorn_and_websockets_entirely() -> None:
    """Request/WS noise stays file-only — forwarding a failed WS send's own
    error over the WS would feed back into itself."""
    h = WsLogHandler()
    h.emit(_record("uvicorn.access", logging.ERROR, "GET /x 500"))
    h.emit(_record("uvicorn.error", logging.WARNING, "boom"))
    h.emit(_record("websockets.server", logging.ERROR, "send failed"))
    assert len(h.queue) == 0


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
