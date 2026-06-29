"""Validates release build configuration files.

Checks that version strings, file paths, and critical settings are consistent
across tauri.conf.json, Cargo.toml, the PyInstaller spec, and the smoke test
script — so a bad config is caught in CI before a release tag is pushed.
"""

from __future__ import annotations

import json
import os
import tomllib


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _read(rel: str) -> str:
    with open(os.path.join(REPO_ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _read_toml(rel: str) -> dict:
    with open(os.path.join(REPO_ROOT, rel), "rb") as f:
        return tomllib.load(f)


def test_tauri_conf_version_matches_cargo_toml() -> None:
    tauri = json.loads(_read("src-tauri/tauri.conf.json"))
    cargo = _read_toml("src-tauri/Cargo.toml")

    assert tauri["version"] == cargo["package"]["version"], (
        f"tauri.conf.json version {tauri['version']!r} "
        f"!= Cargo.toml version {cargo['package']['version']!r}"
    )


def test_tauri_conf_has_required_build_fields() -> None:
    conf = json.loads(_read("src-tauri/tauri.conf.json"))
    assert conf.get("bundle", {}).get("targets") == ["nsis"], (
        "bundle.targets must be ['nsis'] for Windows release"
    )
    ext = conf.get("bundle", {}).get("externalBin", [])
    assert any("faces-sidecar" in e for e in ext), (
        f"bundle.externalBin must include faces-sidecar path; got {ext}"
    )
    nsis = conf.get("bundle", {}).get("windows", {}).get("nsis", {})
    assert nsis.get("installMode") == "currentUser", (
        "nsis.installMode must be 'currentUser'"
    )


def test_pyinstaller_spec_entry_point() -> None:
    spec = _read("sidecar/faces-sidecar.spec")
    assert '"main.py"' in spec or "'main.py'" in spec, (
        "PyInstaller spec must list main.py as entry point"
    )
    assert "faces-sidecar" in spec, (
        "PyInstaller spec must set exe name to faces-sidecar"
    )


def test_pyinstaller_spec_uvicorn_hidden_imports() -> None:
    spec = _read("sidecar/faces-sidecar.spec")
    required = [
        "uvicorn.loops",
        "uvicorn.protocols.http",
        "uvicorn.protocols.websockets",
        "uvicorn.lifespan",
    ]
    for module in required:
        assert module in spec, f"faces-sidecar.spec missing hiddenimport: {module}"


def test_release_workflow_triggers_on_version_tags_and_dispatch() -> None:
    workflow = _read(".github/workflows/release.yml")
    assert "v*.*.*" in workflow, (
        "release.yml must trigger on v*.*.* tag pushes"
    )
    assert "workflow_dispatch" in workflow, (
        "release.yml must support workflow_dispatch so the build can be triggered "
        "from the GitHub Actions UI without pushing a tag from the command line"
    )
    assert "windows-latest" in workflow, (
        "release.yml must run on windows-latest"
    )
    assert "pyinstaller" in workflow.lower(), (
        "release.yml must include a PyInstaller build step"
    )


def test_release_workflow_injects_version_from_tag() -> None:
    """release.yml must patch tauri.conf.json and Cargo.toml before building
    so that releases triggered via the GitHub UI (no code version bump) still
    embed the correct version in the installer."""
    workflow = _read(".github/workflows/release.yml")
    assert "RELEASE_TAG" in workflow and "tauri.conf.json" in workflow and "Cargo.toml" in workflow, (
        "release.yml must have an inject-version step that patches tauri.conf.json "
        "and Cargo.toml from the RELEASE_TAG env var"
    )


def test_build_workflows_rename_sidecar_binary_for_tauri() -> None:
    """Tauri externalBin requires the binary to carry the target-triple suffix.
    Both CI workflows must copy faces-sidecar.exe → faces-sidecar-<triple>.exe."""
    for wf in (".github/workflows/build.yml", ".github/workflows/release.yml"):
        content = _read(wf)
        assert "faces-sidecar-x86_64-pc-windows-msvc.exe" in content, (
            f"{wf} must rename the sidecar binary to include the Tauri target triple"
        )


def test_smoke_test_script_exists_and_is_valid_python() -> None:
    path = os.path.join(REPO_ROOT, "scripts", "smoke_test.py")
    assert os.path.isfile(path), "scripts/smoke_test.py must exist"
    source = _read("scripts/smoke_test.py")
    compile(source, "smoke_test.py", "exec")  # raises SyntaxError if invalid
    assert "/health" in source, "smoke_test.py must check /health endpoint"
    assert "/models/status" in source, "smoke_test.py must check /models/status"
