"""Tests for the parent-process watchdog that keeps app + sidecar one unit (#119)."""

import os

import pytest

from main import _parent_alive


def test_parent_alive_for_own_pid() -> None:
    """Our own PID always exists, whether or not psutil is installed."""
    assert _parent_alive(os.getpid()) is True


def test_parent_alive_false_for_bogus_pid() -> None:
    """A PID that cannot exist reports dead (needs psutil for a real probe)."""
    pytest.importorskip("psutil")
    # PID 0 is the idle process on Windows / swapper on Linux; use an absurdly
    # high value instead — pid_exists returns False for it on all platforms.
    assert _parent_alive(2_147_483_000) is False


def test_parent_alive_survives_probe_errors() -> None:
    """A negative PID must not raise — the probe degrades to 'assume alive'."""
    result = _parent_alive(-1)
    assert isinstance(result, bool)
