#!/usr/bin/env python3
"""Post-install smoke test for a running faces-h sidecar.

Run this after installing the release build to verify the sidecar is healthy:

    python scripts/smoke_test.py
    python scripts/smoke_test.py --url http://127.0.0.1:51423

Exits 0 on success, 1 on any failure.
Requires only the Python standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _fetch(url: str) -> object:
    with urllib.request.urlopen(url, timeout=10) as resp:
        return json.loads(resp.read())


def _check(label: str, url: str, predicate=None) -> None:
    try:
        data = _fetch(url)
        if predicate is not None:
            predicate(data)
        print(f"  PASS  {label}")
    except Exception as exc:
        print(f"  FAIL  {label}: {exc}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="faces-h post-install smoke test")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:51423",
        help="Base URL of the running sidecar (default: http://127.0.0.1:51423)",
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")

    print(f"faces-h smoke test  [{base}]")
    print()

    _check(
        "GET /health  →  {status: ok}",
        f"{base}/health",
        lambda d: _assert(d.get("status") == "ok", f"expected status=ok, got {d}"),
    )
    _check(
        "GET /models/status  →  has 'ready' field",
        f"{base}/models/status",
        lambda d: _assert("ready" in d, f"missing 'ready' field: {d}"),
    )
    _check(
        "GET /people  →  list",
        f"{base}/people",
        lambda d: _assert(isinstance(d, list), f"expected list, got {type(d).__name__}"),
    )
    _check(
        "GET /scan/status  →  has 'running' field",
        f"{base}/scan/status",
        lambda d: _assert("running" in d, f"missing 'running' field: {d}"),
    )
    _check(
        "GET /queue/count  →  has 'count' field",
        f"{base}/queue/count",
        lambda d: _assert("count" in d, f"missing 'count' field: {d}"),
    )

    print()
    print("All checks passed — installation is healthy.")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    main()
