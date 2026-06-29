# Implementation Plan: faces-h

**Version:** 1.0  
**Status:** Draft  
**Last updated:** 2026-06-28  
**Reference:** `docs/ARCHITECTURE.md`, `docs/PRD.md`

This document is structured for execution by Claude Code specialist subagents. Each issue is self-contained: it lists its dependencies, the exact files to create or modify, and a binary acceptance checklist. Agents should not begin an issue until all listed dependencies are merged to `main`.

---

## Agent Specializations

| Agent role | Owns |
|-----------|------|
| **Infra** | Repo scaffold, CI/CD workflows, GitHub templates, branch protection |
| **Python** | Sidecar (FastAPI, scanner, ML engine, FAISS, SQLite, re-evaluation) |
| **Rust** | Tauri shell, sidecar lifecycle, OS commands (open in viewer, reveal in Explorer) |
| **Frontend** | React/TypeScript UI, design system tokens, all views and components |

---

## Dependency Graph

```
[P0-01] Repo scaffold
    └── [P0-02] CI/CD workflows
            ├── [P1-01] Sidecar scaffold        ← Python agent
            │       ├── [P1-02] SQLite schema
            │       ├── [P1-03] Scanner service
            │       ├── [P1-04] FAISS index manager
            │       └── [P1-05] ML engine + InsightFace
            │               └── [P1-06] Clustering service
            ├── [P2-01] Tauri shell scaffold     ← Rust agent
            │       └── [P2-02] Sidecar IPC bridge
            └── [P3-01] Frontend scaffold        ← Frontend agent
                    └── [P3-02] Design system tokens

[P1-02, P1-05, P2-02, P3-02] → [P4-01] Gallery view
[P4-01] → [P4-02] Naming workflow
[P4-02] → [P4-03] Uncertain queue
[P4-03] → [P5-01] Search
[P4-02] → [P5-02] Corrections + re-evaluation
[P5-01, P5-02] → [P6-01] Onboarding flow
[P6-01] → [P6-02] Performance profiling (5TB)
[P6-02] → [P6-03] Windows release build
```

---

## Phase 0 — Repository & CI/CD

> **Infra agent.** Must complete before any other work begins. Creates the repo skeleton, all GitHub Actions workflows, and issue/PR templates.

---

### P0-01 · Scaffold repository structure

**Labels:** `infra`  
**Milestone:** M1 — Foundation  
**Depends on:** nothing

**Create this directory tree (empty files where noted):**

```
faces-h/
├── src-tauri/
│   ├── src/
│   │   └── main.rs          # placeholder
│   ├── Cargo.toml           # placeholder
│   └── tauri.conf.json      # placeholder
├── src/
│   ├── main.tsx             # placeholder
│   └── App.tsx              # placeholder
├── sidecar/
│   ├── api/
│   │   └── __init__.py
│   ├── ml/
│   │   └── __init__.py
│   ├── db/
│   │   └── __init__.py
│   ├── index/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   ├── tests/
│   │   └── __init__.py
│   ├── main.py              # FastAPI entry point (placeholder)
│   └── requirements.txt     # see below
├── .github/
│   ├── workflows/           # created in P0-02
│   ├── ISSUE_TEMPLATE/      # created in P0-02
│   └── pull_request_template.md
├── .gitignore
├── package.json             # see below
└── vite.config.ts           # placeholder
```

**`.gitignore`:**
```
# Python
__pycache__/
*.pyc
.venv/
sidecar/dist/
sidecar/*.spec

# Node
node_modules/
dist/

# Rust / Tauri
target/
src-tauri/target/

# App data (never commit)
*.db
*.index

# OS
.DS_Store
Thumbs.db
```

**`sidecar/requirements.txt`:**
```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
aiosqlite>=0.20.0
insightface>=0.7.3
onnxruntime>=1.18.0
faiss-cpu>=1.8.0
Pillow>=10.3.0
pillow-heif>=0.16.0
piexif>=1.1.3
numpy>=1.26.0
ruff>=0.4.0
mypy>=1.10.0
pytest>=8.2.0
pytest-cov>=5.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
pyinstaller>=6.7.0
```

**`package.json`** (root-level, for frontend):
```json
{
  "name": "faces-h",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest",
    "lint": "eslint src --ext ts,tsx",
    "type-check": "tsc --noEmit",
    "tauri": "tauri"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "zustand": "^4.5.0",
    "@tanstack/react-query": "^5.40.0"
  },
  "devDependencies": {
    "@tauri-apps/cli": "^2.0.0",
    "@tauri-apps/api": "^2.0.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vitest": "^1.6.0",
    "@testing-library/react": "^16.0.0",
    "@testing-library/user-event": "^14.5.0",
    "eslint": "^8.57.0",
    "@typescript-eslint/eslint-plugin": "^7.0.0",
    "@typescript-eslint/parser": "^7.0.0"
  }
}
```

**`pull_request_template.md`:**
```markdown
## Summary
<!-- What does this PR do? -->

## Issue
Closes #

## Checklist
- [ ] Tests added or updated
- [ ] `ruff check` passes (Python)
- [ ] `mypy` passes (Python)
- [ ] `tsc --noEmit` passes (TypeScript)
- [ ] `cargo clippy` passes (Rust)
- [ ] No photo files are read/written/moved/deleted by this change
```

**Acceptance criteria:**
- [ ] All directories and placeholder files exist and are committed
- [ ] `.gitignore` covers Python, Node, Rust, and OS artifacts
- [ ] `package.json` present with correct scripts
- [ ] `sidecar/requirements.txt` present with all packages listed

---

### P0-02 · GitHub Actions workflows and issue templates

**Labels:** `infra`  
**Milestone:** M1 — Foundation  
**Depends on:** P0-01

Create the following files exactly as specified.

---

**`.github/workflows/ci.yml`**

Runs on every PR and push to `main`. Python and frontend jobs use `ubuntu-latest` (faster). Rust job also uses `ubuntu-latest` for clippy/unit tests.

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  python:
    name: Python — lint, type-check, test
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: sidecar

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: sidecar/requirements.txt

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Lint (ruff)
        run: ruff check .

      - name: Type check (mypy)
        run: mypy . --ignore-missing-imports

      - name: Tests (pytest)
        run: pytest tests/ --cov=. --cov-report=xml --cov-fail-under=70

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          files: sidecar/coverage.xml
          flags: python
        continue-on-error: true

  frontend:
    name: Frontend — lint, type-check, test
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - name: Install dependencies
        run: npm ci

      - name: Lint (eslint)
        run: npm run lint

      - name: Type check
        run: npm run type-check

      - name: Tests (vitest)
        run: npm test

  rust:
    name: Rust — clippy, test
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Install system dependencies (WebKitGTK for Tauri on Linux)
        run: |
          sudo apt-get update
          sudo apt-get install -y \
            libwebkit2gtk-4.1-dev \
            libappindicator3-dev \
            librsvg2-dev \
            patchelf

      - uses: dtolnay/rust-toolchain@stable
        with:
          components: clippy

      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: src-tauri

      - name: Clippy
        run: cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings

      - name: Tests
        run: cargo test --manifest-path src-tauri/Cargo.toml
```

---

**`.github/workflows/build.yml`**

Builds the Windows installer on every push to `main`. Uses `windows-latest` because PyInstaller and Tauri's NSIS bundler require the target OS.

```yaml
name: Build (Windows)

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  build-windows:
    name: Build Windows installer
    runs-on: windows-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: sidecar/requirements.txt

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - uses: dtolnay/rust-toolchain@stable

      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: src-tauri

      - name: Install Python dependencies
        run: pip install -r sidecar/requirements.txt

      - name: Build Python sidecar (PyInstaller)
        run: |
          cd sidecar
          pyinstaller faces-sidecar.spec
        # faces-sidecar.spec is committed to the repo (created in P1-01)

      - name: Install Node dependencies
        run: npm ci

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tauriScript: npm run tauri

      - name: Upload installer artifact
        uses: actions/upload-artifact@v4
        with:
          name: faces-h-windows-installer-${{ github.sha }}
          path: src-tauri/target/release/bundle/nsis/*.exe
          retention-days: 30
```

---

**`.github/workflows/release.yml`**

Triggered when a version tag is pushed (`v*.*.*`). Builds the installer and creates a GitHub Release with it attached.

```yaml
name: Release

on:
  push:
    tags:
      - "v*.*.*"

permissions:
  contents: write

jobs:
  release-windows:
    name: Build and release Windows installer
    runs-on: windows-latest

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
          cache-dependency-path: sidecar/requirements.txt

      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: "npm"

      - uses: dtolnay/rust-toolchain@stable

      - uses: Swatinem/rust-cache@v2
        with:
          workspaces: src-tauri

      - name: Install Python dependencies
        run: pip install -r sidecar/requirements.txt

      - name: Build Python sidecar (PyInstaller)
        run: |
          cd sidecar
          pyinstaller faces-sidecar.spec

      - name: Install Node dependencies
        run: npm ci

      - name: Build Tauri app
        uses: tauri-apps/tauri-action@v0
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        with:
          tauriScript: npm run tauri
          tagName: ${{ github.ref_name }}
          releaseName: "faces-h ${{ github.ref_name }}"
          releaseBody: |
            ## Installation
            Download `faces-h-setup-*.exe` and run it. No additional software required.

            The app will download the face recognition model (~300 MB) on first launch.
          releaseDraft: false
          prerelease: false

      - name: Upload release asset
        uses: softprops/action-gh-release@v2
        with:
          files: src-tauri/target/release/bundle/nsis/*.exe
          generate_release_notes: true
```

---

**`.github/ISSUE_TEMPLATE/bug_report.yml`:**
```yaml
name: Bug report
description: Something is broken
labels: [bug]
body:
  - type: textarea
    id: description
    attributes:
      label: What happened?
    validations:
      required: true
  - type: textarea
    id: steps
    attributes:
      label: Steps to reproduce
    validations:
      required: true
  - type: textarea
    id: expected
    attributes:
      label: Expected behavior
    validations:
      required: true
  - type: input
    id: version
    attributes:
      label: App version
    validations:
      required: true
```

**`.github/ISSUE_TEMPLATE/feature_request.yml`:**
```yaml
name: Feature request
description: New capability or enhancement
labels: [feature]
body:
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
    validations:
      required: true
  - type: textarea
    id: solution
    attributes:
      label: Proposed solution
    validations:
      required: true
  - type: textarea
    id: acceptance
    attributes:
      label: Acceptance criteria
      placeholder: "- [ ] ..."
    validations:
      required: true
```

**`.github/ISSUE_TEMPLATE/spike.yml`:**
```yaml
name: Spike
description: Time-boxed investigation with no required code output
labels: [spike]
body:
  - type: textarea
    id: question
    attributes:
      label: Question to answer
    validations:
      required: true
  - type: input
    id: timebox
    attributes:
      label: Time budget
      placeholder: e.g. 4 hours
    validations:
      required: true
  - type: textarea
    id: output
    attributes:
      label: Expected output
      placeholder: "A written summary, benchmark numbers, a recommendation, ..."
    validations:
      required: true
```

**Acceptance criteria:**
- [ ] All three workflow files committed to `.github/workflows/`
- [ ] `ci.yml` triggers on PR; all three jobs (python, frontend, rust) are defined
- [ ] `build.yml` triggers on push to `main`; produces a `.exe` artifact
- [ ] `release.yml` triggers on `v*.*.*` tags; creates a GitHub Release with the `.exe` attached
- [ ] Three issue templates committed to `.github/ISSUE_TEMPLATE/`
- [ ] PR template committed
- [ ] Branch protection on `main`: PR required, CI must pass, no direct push (configure in GitHub repo settings — cannot be done via file commit)

---

## Phase 1 — Python Sidecar Foundation

> **Python agent.** All issues in this phase are independent of the Tauri shell and can be developed and tested in isolation. The sidecar must be runnable with `uvicorn sidecar.main:app` for local development.

---

### P1-01 · FastAPI sidecar scaffold and PyInstaller spec

**Labels:** `infra`, `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P0-01

**Files to create:**

`sidecar/main.py`:
```python
import argparse
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="faces-h sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # restricted to tauri origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=51423)
    parser.add_argument("--data-dir", type=str, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
```

`sidecar/faces-sidecar.spec` (PyInstaller spec):
```python
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[str(Path(".").resolve())],
    binaries=[],
    datas=[],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="faces-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
```

`sidecar/tests/test_health.py`:
```python
import pytest
from httpx import AsyncClient, ASGITransport
from sidecar.main import app

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

`sidecar/pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

`sidecar/mypy.ini`:
```ini
[mypy]
python_version = 3.11
strict = false
ignore_missing_imports = true
```

**Acceptance criteria:**
- [ ] `uvicorn sidecar.main:app --port 51423 --app-dir .` starts without errors
- [ ] `GET http://127.0.0.1:51423/health` returns `{"status": "ok"}`
- [ ] `pytest sidecar/tests/` passes
- [ ] `pyinstaller sidecar/faces-sidecar.spec` produces `sidecar/dist/faces-sidecar.exe`
- [ ] CI python job passes on this branch

---

### P1-02 · SQLite schema and migrations

**Labels:** `db`, `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P1-01

**Files to create:**

`sidecar/db/schema.py` — defines `CREATE TABLE` statements as constants.  
`sidecar/db/database.py` — async context manager wrapping `aiosqlite`; applies schema on first connect.  
`sidecar/tests/test_database.py` — verifies all tables are created; verifies foreign key constraints.

Schema must exactly match `docs/ARCHITECTURE.md § SQLite Schema`. Tables: `photos`, `faces`, `people`, `corrections`, `scan_state`.

Add indexes:
```sql
CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_faces_status ON faces(assign_status);
CREATE INDEX IF NOT EXISTS idx_photos_path ON photos(path);
CREATE INDEX IF NOT EXISTS idx_photos_taken_at ON photos(taken_at);
```

Enable WAL mode and foreign keys on every connection:
```python
await db.execute("PRAGMA journal_mode=WAL")
await db.execute("PRAGMA foreign_keys=ON")
```

**Acceptance criteria:**
- [ ] `pytest sidecar/tests/test_database.py` passes
- [ ] All five tables created with correct columns and types
- [ ] WAL mode and FK enforcement verified in tests
- [ ] Database file created at the path passed via `--data-dir`

---

### P1-03 · File scanner service

**Labels:** `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P1-02

**Files to create:**

`sidecar/services/scanner.py` — async generator that walks a root directory, yields `PhotoFile` dataclasses, skips unreadable files (log + continue), reads EXIF `DateTimeOriginal` via `piexif`, opens HEIC via `pillow-heif`.

`sidecar/api/scan.py` — FastAPI router with:
- `POST /scan/start` — accepts `{ "root_path": "C:\\Users\\..." }`, writes to `scan_state`, starts background task
- `GET /scan/status` — returns current scan state
- `POST /scan/pause` / `POST /scan/resume`
- `WebSocket /ws` — streams `scan_progress` events (see ARCHITECTURE.md § IPC Protocol)

Supported extensions: `.jpg`, `.jpeg`, `.png`, `.heic`, `.heif`, `.tiff`, `.tif`, `.raw`, `.cr2`, `.nef`, `.arw`, `.dng`

Incremental logic: before inserting a photo, check `SELECT id FROM photos WHERE path=? AND mtime=?`. Skip if match found.

**Acceptance criteria:**
- [ ] `POST /scan/start` with a local folder begins walking; `GET /scan/status` returns progress
- [ ] Corrupt/unreadable files are skipped; scan continues; error count incremented in state
- [ ] Re-running scan on same folder only processes new/changed files (incremental)
- [ ] WebSocket receives `scan_progress` events every 100 files
- [ ] `pytest sidecar/tests/test_scanner.py` passes (use a temporary directory with synthetic images)
- [ ] Throughput test: ≥500 files/min on the CI runner (even with empty embed stubs)

---

### P1-04 · FAISS index manager

**Labels:** `ml`, `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P1-02

**Files to create:**

`sidecar/index/faiss_manager.py`:

```python
class FAISSManager:
    """
    Manages a FAISS index with automatic promotion:
      <10K embeddings  → IndexFlatIP (exact)
      10K–250K         → IndexIVFFlat (nlist=256)
      250K+            → IndexIVFPQ (nlist=2048, PQ16)

    Index is persisted to {data_dir}/faces.index.
    Promotion rebuilds run in a background thread; old index serves queries during rebuild.
    """
    def add(self, embedding_id: int, embedding: np.ndarray) -> None: ...
    def search(self, embedding: np.ndarray, k: int = 10) -> list[tuple[int, float]]:
        """Returns list of (embedding_id, cosine_similarity) sorted descending."""
        ...
    def save(self) -> None: ...
    def load(self) -> None: ...
    def needs_promotion(self) -> bool: ...
    def promote(self) -> None: ...  # runs synchronously; call from background thread
```

`sidecar/tests/test_faiss_manager.py`:
- Add 100 synthetic 512-dim embeddings; verify `search` returns correct nearest neighbor
- Add 10,001 embeddings; verify `needs_promotion()` returns `True` and `promote()` rebuilds to IVFFlat
- Verify save/load round-trip preserves search results

**Acceptance criteria:**
- [ ] `pytest sidecar/tests/test_faiss_manager.py` passes
- [ ] Correct promotion thresholds: Flat < 10K, IVFFlat 10K–250K, IVFPQ 250K+
- [ ] `faces.index` written to `--data-dir` on `save()`
- [ ] `load()` restores index from disk; search results identical

---

### P1-05 · ML engine — InsightFace buffalo_l

**Labels:** `ml`, `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P1-01

**Files to create:**

`sidecar/ml/base.py` — `FaceResult` dataclass and `FaceRecognizer` ABC (exact interface from ARCHITECTURE.md § Swappable Model Interface).

`sidecar/ml/insightface_recognizer.py`:
- Implements `FaceRecognizer`
- Loads buffalo_l from `{data_dir}/models/buffalo_l/` on first call; downloads if missing (progress logged to stdout)
- Returns `[]` (not raises) on corrupt or unreadable images
- Normalizes bounding boxes to 0–1 relative coordinates
- L2-normalizes embeddings before returning

`sidecar/ml/factory.py`:
```python
def get_recognizer(config: dict, data_dir: Path) -> FaceRecognizer:
    model = config.get("face_model", "insightface_buffalo_l")
    if model == "insightface_buffalo_l":
        return InsightFaceRecognizer(data_dir)
    if model == "deepface_facenet512":
        return DeepFaceRecognizer(data_dir)
    raise ValueError(f"Unknown face model: {model}")
```

`sidecar/tests/test_ml_engine.py`:
- Use a synthetic 100×100 white image → verify `detect_and_embed` returns `[]` without raising
- Use a real face image (include a small test fixture in `sidecar/tests/fixtures/`) → verify at least one `FaceResult` returned with correct shape
- Verify embeddings are L2-normalized (norm ≈ 1.0)

**Acceptance criteria:**
- [ ] `pytest sidecar/tests/test_ml_engine.py` passes
- [ ] `FaceResult.embedding` shape is `(512,)` and L2-normalized
- [ ] Corrupt image returns `[]`; no exception propagates
- [ ] Model downloads to `{data_dir}/models/buffalo_l/` on first call
- [ ] `factory.py` returns correct class for each `face_model` config value

---

### P1-06 · Clustering service

**Labels:** `ml`, `python`  
**Milestone:** M1 — Foundation  
**Depends on:** P1-04, P1-05

**Files to create:**

`sidecar/services/clustering.py`:
```python
class ClusteringService:
    """
    Assigns a new face embedding to a person cluster or the uncertain queue.

    Thresholds (from config, defaults from ARCHITECTURE.md OD-02):
      auto_assign_threshold: 0.68   → assign_status = 'assigned'
      uncertain_threshold:   0.50   → assign_status = 'uncertain'
      below uncertain               → assign_status = 'unreviewed' (new unknown cluster)

    NEVER auto-assigns without meeting the threshold.
    Updates person centroid as rolling average on each confirmed assignment.
    """
    async def assign(self, face_id: int, embedding: np.ndarray) -> AssignResult: ...
    async def confirm(self, face_id: int, person_id: int) -> None: ...
    async def reject(self, face_id: int, correct_person_id: int | None) -> None: ...
    async def update_centroid(self, person_id: int) -> None: ...
```

`sidecar/api/people.py` — FastAPI router:
- `GET /people` — list all named people with photo count and medallion face ID
- `GET /people/{id}/photos` — paginated photo list sorted by `taken_at`
- `POST /people/{id}/name` — assign or update name
- `POST /people/merge` — `{ "source_id": N, "target_id": M }` → merge source into target with confirmation; requires explicit call (no auto-merge)
- `DELETE /people/{id}` — delete person; return all faces to `assign_status = 'unreviewed'`

`sidecar/tests/test_clustering.py`:
- Verify a face above `auto_assign_threshold` gets `assign_status = 'assigned'`
- Verify a face between thresholds gets `assign_status = 'uncertain'`
- Verify a face below `uncertain_threshold` gets `assign_status = 'unreviewed'`
- Verify centroid update moves toward new embedding (rolling average)
- Verify delete person returns faces to `unreviewed`

**Acceptance criteria:**
- [ ] `pytest sidecar/tests/test_clustering.py` passes
- [ ] All three assignment paths tested and correct
- [ ] Merge endpoint moves all faces from source to target; deletes source person record
- [ ] Delete person returns faces to `unreviewed` queue; zero face records deleted

---

## Phase 2 — Tauri Shell

> **Rust agent.** Creates the Tauri 2.0 application shell. The sidecar is treated as a black box — the shell starts it, waits for it to be healthy, and shuts it down.

---

### P2-01 · Tauri 2.0 scaffold

**Labels:** `infra`, `rust`  
**Milestone:** M1 — Foundation  
**Depends on:** P0-01

Bootstrap a Tauri 2.0 project targeting Windows (primary) with the React+Vite frontend already in `src/`.

**`src-tauri/tauri.conf.json`** key settings:
```json
{
  "productName": "faces-h",
  "version": "0.1.0",
  "identifier": "com.faces-h.app",
  "build": {
    "frontendDist": "../dist",
    "devUrl": "http://localhost:5173"
  },
  "bundle": {
    "active": true,
    "targets": ["nsis"],
    "windows": {
      "nsis": {
        "installMode": "currentUser"
      }
    },
    "externalBin": ["../sidecar/dist/faces-sidecar"]
  },
  "app": {
    "windows": [{
      "title": "faces-h",
      "width": 1280,
      "height": 800,
      "minWidth": 900,
      "minHeight": 600
    }]
  }
}
```

**Acceptance criteria:**
- [ ] `npm run tauri dev` launches the app window with the placeholder React UI
- [ ] `cargo clippy` passes with no warnings
- [ ] `cargo test` passes

---

### P2-02 · Sidecar lifecycle and IPC bridge

**Labels:** `rust`, `infra`  
**Milestone:** M1 — Foundation  
**Depends on:** P2-01, P1-01

**`src-tauri/src/main.rs`** must:

1. Allocate a random free port (bind `TcpListener` to `127.0.0.1:0`, read port, drop listener)
2. Launch `faces-sidecar.exe` with args `--port {port} --data-dir {appdata}/faces-h`
3. Poll `GET http://127.0.0.1:{port}/health` with 200ms retries for up to 30 seconds; show loading state in frontend until healthy
4. Inject `SIDECAR_PORT` and `SIDECAR_URL` into the WebView environment so the frontend can connect
5. On app exit, send `SIGTERM` (Windows: `TerminateProcess`) to the sidecar

**Tauri commands to expose to frontend:**
```rust
#[tauri::command]
fn open_in_viewer(path: String) -> Result<(), String>  // ShellExecute("open", path)

#[tauri::command]
fn reveal_in_explorer(path: String) -> Result<(), String>  // explorer.exe /select,path

#[tauri::command]
fn get_sidecar_url() -> String  // returns "http://127.0.0.1:{port}"
```

**Acceptance criteria:**
- [ ] App launch → sidecar starts → health check passes → frontend receives `SIDECAR_URL`
- [ ] App close → sidecar process is terminated (verify via Task Manager)
- [ ] `open_in_viewer` opens a test `.jpg` in Windows Photos
- [ ] `reveal_in_explorer` opens Explorer with the file selected
- [ ] If sidecar fails to start within 30 seconds, app shows an error dialog and exits cleanly

---

## Phase 3 — Frontend Foundation

> **Frontend agent.** Creates the React scaffold, installs design tokens from `docs/DESIGN.md`, and wires up the API client. No ML or Rust work.

---

### P3-01 · React + TypeScript scaffold

**Labels:** `ui`, `infra`  
**Milestone:** M1 — Foundation  
**Depends on:** P0-01

Initialize the Vite + React + TypeScript project in `src/`. Install and configure:
- `eslint` with `@typescript-eslint`
- `vitest` + `@testing-library/react`
- `zustand` for state
- `@tanstack/react-query` for server state

`src/main.tsx` — root render  
`src/App.tsx` — placeholder with `<h1>faces-h</h1>`  
`vite.config.ts` — standard Vite + React config  
`tsconfig.json` — strict mode enabled

**Acceptance criteria:**
- [ ] `npm run dev` serves the app at `localhost:5173`
- [ ] `npm run type-check` passes
- [ ] `npm run lint` passes
- [ ] `npm test` runs with zero failures (one smoke test verifying `<App />` renders)

---

### P3-02 · Design system tokens

**Labels:** `ui`  
**Milestone:** M1 — Foundation  
**Depends on:** P3-01

Implement the token system from `docs/DESIGN.md` as CSS custom properties and a TypeScript constants file.

`src/styles/tokens.css`:
```css
:root {
  --color-bg:          #F6F4F1;
  --color-surface:     #FFFFFF;
  --color-border:      #E3DFDA;
  --color-text-primary:   #1C1917;
  --color-text-secondary: #78716C;
  --color-accent:      #C2522A;

  --font-family: 'DM Sans', system-ui, sans-serif;
  --font-weight-body:    400;
  --font-weight-label:   500;
  --font-weight-name:    600;
  --font-weight-heading: 700;

  --radius-medallion: 50%;
  --radius-card: 6px;
  --transition-ring: ring 150ms ease;
}

@media (prefers-color-scheme: dark) {
  :root {
    --color-bg:          #1C1917;
    --color-surface:     #26211E;
    --color-border:      #3D3733;
    --color-text-primary:   #F6F4F1;
    --color-text-secondary: #A8A29E;
    --color-accent:      #E8714A;
  }
}
```

Add DM Sans via `@fontsource/dm-sans` (npm package — no external CDN).

`src/styles/tokens.ts` — TypeScript mirror of the same values for use in dynamic styles.

`src/components/Medallion.tsx` — circular face image component with terracotta ring on hover/selected state. Props: `{ src: string; selected?: boolean; size?: number }`.

`src/tests/Medallion.test.tsx` — verifies ring class applied when `selected={true}`.

**Acceptance criteria:**
- [ ] Light and dark mode tokens applied via `prefers-color-scheme`
- [ ] DM Sans loaded via npm (no external CDN)
- [ ] `<Medallion>` renders with ring when `selected={true}`
- [ ] `npm test` passes including Medallion test

---

## Phase 4 — Core UI

> **Frontend + Python agents in parallel.** Frontend builds the gallery shell; Python wires the API endpoints. Integration happens at the end of this phase.

---

### P4-01 · Gallery view — person sidebar and photo grid

**Labels:** `ui`  
**Milestone:** M2 — Core ML  
**Depends on:** P3-02, P2-02

Implement the three-panel layout from `docs/DESIGN.md`:

**Left sidebar** (`src/components/Sidebar.tsx`):
- List of named people with `<Medallion>` + name + photo count
- "Unnamed faces" entry at bottom with count badge (terracotta)
- Navigation: People | Search | Settings

**Main area** (`src/components/PhotoGrid.tsx`):
- CSS Grid with `grid-template-columns: repeat(auto-fill, minmax({size}px, 1fr))`
- Size slider (80–300px) persisted to `localStorage`
- On photo click: open detail panel

**Right panel** (`src/components/DetailPanel.tsx`):
- Photo preview
- Taken date, file path
- List of faces in this photo (each as a `<Medallion>` with name or "Unknown")
- "This person is wrong" button on each face (visible on hover)

All data is loaded from mock JSON during this issue. API wiring is done in P4-02.

**Acceptance criteria:**
- [ ] Three-panel layout renders at 1280×800
- [ ] Sidebar person list renders from mock data
- [ ] Grid thumbnail size changes when slider moves; value persists on reload
- [ ] Clicking a photo opens the detail panel
- [ ] "This person is wrong" button appears on hover over a face in the detail panel
- [ ] `npm test` passes

---

### P4-02 · API client and naming workflow

**Labels:** `ui`, `python`  
**Milestone:** M2 — Core ML  
**Depends on:** P4-01, P1-06

**Frontend:**

`src/api/client.ts` — typed fetch wrapper reading `SIDECAR_URL` from Tauri environment. Exports functions for each endpoint from ARCHITECTURE.md § Query Service.

`src/api/ws.ts` — WebSocket manager; reconnects on disconnect; dispatches events to Zustand store.

`src/components/NamingModal.tsx` — shown when clicking an unnamed cluster:
- Grid of sample face crops from the cluster
- Text input for name with autocomplete from existing people
- "Save" button → `POST /people/{id}/name`
- "Skip for now" button

`src/components/MergeModal.tsx` — shown via "Merge with…" button in person detail:
- Person picker (search by name)
- Confirmation step: "Merge [A] into [B]? This cannot be undone."
- On confirm → `POST /people/merge`

**Python:** Ensure `GET /people`, `GET /people/{id}/photos`, `POST /people/{id}/name`, and `POST /people/merge` are fully implemented and return correct shapes (extend P1-06 if incomplete).

**Acceptance criteria:**
- [ ] Naming modal appears on clicking an unnamed cluster; submitting saves name; sidebar updates
- [ ] Merge modal opens from person detail; confirmation required; merge completes
- [ ] WebSocket connection established on app start; `scan_progress` events update progress bar
- [ ] All API calls use `SIDECAR_URL` from Tauri environment (not hardcoded port)

---

### P4-03 · Uncertain face queue

**Labels:** `ui`, `python`  
**Milestone:** M2 — Core ML  
**Depends on:** P4-02

**Frontend** (`src/components/UncertainQueue.tsx`):
- Accessed via "Unnamed faces" in sidebar (count badge always visible)
- Each item shows: face crop, suggested person name, confidence percentage
- "Yes, this is [name]" → confirm → `POST /queue/{face_id}/confirm`
- "No, this is someone else" → opens person picker → `POST /photos/{id}/correct`
- "Skip" → moves to bottom of queue

**Python:**
- `GET /queue/uncertain` — returns paginated list of faces with `assign_status = 'uncertain'`, including suggested person name and `assign_conf`
- `POST /queue/{face_id}/confirm` — sets `assign_status = 'assigned'`
- Confirmation triggers centroid update for the person

**Acceptance criteria:**
- [ ] Queue shows all faces with `assign_status = 'uncertain'`
- [ ] Count badge in sidebar matches queue length; updates in real time
- [ ] Confirming a face removes it from queue and updates person gallery
- [ ] Rejecting a face opens person picker and routes to correction flow

---

## Phase 5 — Search and Corrections

---

### P5-01 · Multi-person search with date filter

**Labels:** `ui`, `python`  
**Milestone:** M4 — Search  
**Depends on:** P4-03

**Python** (`sidecar/api/search.py`):
```
POST /search
Body: { "people_ids": [1, 3], "date_from": "2010-01-01", "date_to": "2015-12-31" }
Returns: paginated list of photos where ALL specified people appear (AND logic)
         each photo includes: path, taken_at, list of face assignments
```

AND query implementation:
```sql
SELECT p.id, p.path, p.taken_at
FROM photos p
WHERE p.id IN (
    SELECT photo_id FROM faces WHERE person_id = ? AND assign_status = 'assigned'
)
AND p.id IN (
    SELECT photo_id FROM faces WHERE person_id = ? AND assign_status = 'assigned'
)
-- one subquery per person_id; parameterized
AND (p.taken_at >= ? OR ? IS NULL)
AND (p.taken_at <= ? OR ? IS NULL)
```

**Frontend** (`src/components/SearchView.tsx`):
- Person chip input (add/remove people by name)
- Date range pickers (from / to)
- Results in adaptive photo grid (reuses `<PhotoGrid>`)
- Each photo: double-click → `open_in_viewer` Tauri command
- Right-click → "Show in Explorer" → `reveal_in_explorer` Tauri command
- "Copy path" option in right-click menu

**Acceptance criteria:**
- [ ] Single-person search returns all photos of that person
- [ ] Two-person AND search returns only photos where both appear
- [ ] Date filter narrows results correctly
- [ ] Double-click opens photo in Windows default viewer
- [ ] `pytest sidecar/tests/test_search.py` passes

---

### P5-02 · Corrections and re-evaluation pipeline

**Labels:** `ml`, `python`, `ui`  
**Milestone:** M5 — Corrections  
**Depends on:** P4-03

**Python** (`sidecar/services/reeval.py`):

```python
class ReEvaluationService:
    """
    Triggered when a user marks a face incorrect and reassigns it.
    
    Steps:
    1. Record correction in corrections table
    2. Update face: person_id = new_person_id, assign_status based on new similarity
    3. Recompute centroid for both old and new person
    4. Re-score ALL faces in old person's cluster against updated centroid
    5. Move newly-uncertain faces to assign_status = 'uncertain'
    6. Emit reeval_complete WebSocket event with summary
    
    Runs as background asyncio task; never blocks API responses.
    """
    async def trigger(self, face_id: int, old_person_id: int, new_person_id: int | None) -> None: ...
```

`sidecar/api/corrections.py`:
- `POST /photos/{photo_id}/faces/{face_id}/correct` — `{ "new_person_id": N | null }` (null = unknown person)

**Frontend:**
- "This person is wrong" button in detail panel → opens correction modal
- Correction modal: person picker with search; "Unknown person" option
- After submit: show toast "Re-evaluating [Name]'s cluster…"
- WebSocket `reeval_complete` event → show toast "8 photos moved from Mom to Aunt Sarah, 3 flagged for review"

**Acceptance criteria:**
- [ ] Marking a face wrong and reassigning updates `corrections` table
- [ ] Re-evaluation re-scores affected cluster in background; API remains responsive
- [ ] `reeval_complete` WebSocket event received by frontend
- [ ] Toast shows correct counts from event payload
- [ ] `pytest sidecar/tests/test_reeval.py` passes

---

## Phase 6 — Ship

---

### P6-01 · Onboarding flow

**Labels:** `ui`, `rust`  
**Milestone:** M6 — Ship  
**Depends on:** P5-01, P5-02

`src/components/Onboarding.tsx` — shown on first launch (detected via `localStorage` flag):

1. **Welcome screen** — one sentence about what the app does; "Get started" button
2. **Folder picker** — native folder picker via Tauri `dialog.open({ directory: true })`; shows selected path; "Start scanning" button
3. **Model download screen** — shown only if `{data_dir}/models/buffalo_l/` is absent; progress bar fed by sidecar stdout events; "Downloading face recognition model (300 MB)…"
4. **Scanning begins** — transitions to main UI; scan progress bar appears in sidebar

**Acceptance criteria:**
- [ ] First launch shows onboarding; subsequent launches skip it
- [ ] Folder picker opens native Windows dialog
- [ ] Model download progress shown if models absent
- [ ] After folder selection, scan starts automatically; progress visible in sidebar

---

### P6-02 · Performance profiling and 5TB validation

**Labels:** `perf`, `python`  
**Milestone:** M6 — Ship  
**Depends on:** P6-01

Create `sidecar/tests/test_performance.py` with benchmarks (marked `@pytest.mark.slow`, excluded from CI by default, run manually):

```python
@pytest.mark.slow
def test_scanner_throughput(tmp_path):
    """Generate 10,000 synthetic JPEGs; measure scan rate; assert >= 500/min."""
    ...

@pytest.mark.slow  
def test_faiss_search_latency_at_scale():
    """Add 250,000 synthetic embeddings; measure p99 search latency; assert < 50ms."""
    ...

@pytest.mark.slow
def test_faiss_memory_at_1m_embeddings():
    """Add 1,000,000 embeddings with IVFPQ; measure RSS; assert < 600MB."""
    ...
```

Add a `[slow]` marker to `pytest.ini`; document how to run: `pytest -m slow sidecar/tests/test_performance.py`.

**Acceptance criteria:**
- [ ] All three benchmark tests exist and run to completion
- [ ] Scanner throughput ≥ 500 photos/min on a standard laptop
- [ ] FAISS p99 search < 50ms at 250K embeddings
- [ ] FAISS RSS < 600MB at 1M embeddings (IVFPQ)
- [ ] Results documented in a PR comment

---

### P6-03 · Windows release build validation

**Labels:** `infra`  
**Milestone:** M6 — Ship  
**Depends on:** P6-02

Validate the full release pipeline end-to-end:

1. Push a `v0.1.0` tag to `main`
2. Verify `release.yml` workflow runs on `windows-latest`
3. Verify PyInstaller builds `faces-sidecar.exe`
4. Verify Tauri NSIS bundler produces `faces-h-setup-0.1.0.exe`
5. Verify GitHub Release is created with the `.exe` attached
6. Download the installer on a clean Windows machine; run it; verify:
   - App installs to `%LOCALAPPDATA%\faces-h\`
   - App launches without requiring Python, Node, or Rust
   - Model downloads on first launch
   - `GET /health` responds from the bundled sidecar
   - Scan a small test folder; verify faces appear in UI

**Acceptance criteria:**
- [ ] `release.yml` completes without errors on `windows-latest`
- [ ] GitHub Release exists at `https://github.com/justminime/faces-h/releases/tag/v0.1.0`
- [ ] `.exe` installer attached to the release
- [ ] App installs and runs on a clean Windows machine with no dev tools installed
- [ ] End-to-end smoke test passes (scan folder → name a person → search returns results)

---

## Summary Table

| Issue | Phase | Agent | Labels | Milestone | Depends on |
|-------|-------|-------|--------|-----------|-----------|
| P0-01 | Repo scaffold | Infra | `infra` | M1 | — |
| P0-02 | CI/CD workflows | Infra | `infra` | M1 | P0-01 |
| P1-01 | Sidecar scaffold | Python | `infra` `python` | M1 | P0-01 |
| P1-02 | SQLite schema | Python | `db` `python` | M1 | P1-01 |
| P1-03 | File scanner | Python | `python` | M1 | P1-02 |
| P1-04 | FAISS manager | Python | `ml` `python` | M1 | P1-02 |
| P1-05 | ML engine (InsightFace) | Python | `ml` `python` | M1 | P1-01 |
| P1-06 | Clustering service | Python | `ml` `python` | M1 | P1-04, P1-05 |
| P2-01 | Tauri scaffold | Rust | `infra` `rust` | M1 | P0-01 |
| P2-02 | Sidecar IPC bridge | Rust | `rust` `infra` | M1 | P2-01, P1-01 |
| P3-01 | React scaffold | Frontend | `ui` `infra` | M1 | P0-01 |
| P3-02 | Design system tokens | Frontend | `ui` | M1 | P3-01 |
| P4-01 | Gallery view | Frontend | `ui` | M2 | P3-02, P2-02 |
| P4-02 | API client + naming | Frontend + Python | `ui` `python` | M2 | P4-01, P1-06 |
| P4-03 | Uncertain queue | Frontend + Python | `ui` `python` | M2 | P4-02 |
| P5-01 | Search | Frontend + Python | `ui` `python` | M4 | P4-03 |
| P5-02 | Corrections + re-eval | ML + Frontend | `ml` `python` `ui` | M5 | P4-03 |
| P6-01 | Onboarding flow | Frontend + Rust | `ui` `rust` | M6 | P5-01, P5-02 |
| P6-02 | Performance profiling | Python | `perf` `python` | M6 | P6-01 |
| P6-03 | Release build validation | Infra | `infra` | M6 | P6-02 |
