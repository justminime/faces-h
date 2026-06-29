# Software Architecture: faces-h

**Version:** 1.0
**Status:** Draft
**Last updated:** 2026-06-28

---

## Decisions Made

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D-01 | App shell | Tauri 2.0 | ~5-10 MB installer vs ~150 MB for Electron; uses Edge WebView2 (already on Windows 10+); Rust core for reliability |
| D-02 | Frontend | React + TypeScript (Vite) | Matches Notion/Linear design direction; large ecosystem; strong typing |
| D-03 | ML backend | Python 3.11+ sidecar | Best ecosystem for face recognition; bundled via PyInstaller so user installs nothing |
| D-04 | IPC | Local HTTP (FastAPI) + WebSocket | Sidecar is independently testable; WebSocket enables streaming scan progress |
| D-05 | Face model | Swappable model layer | InsightFace buffalo_l as default; DeepFace/FaceNet512 as alternative; interface enforces identical contract |
| D-06 | Metadata DB | SQLite (via `aiosqlite`) | Local, portable, single-file; no server; supports incremental updates |
| D-07 | Vector index | FAISS IVF | Scales to 1M+ embeddings on CPU; IVF partitioning avoids full scans; promoted from Flat as library grows |
| D-08 | Packaging | PyInstaller (sidecar) + Tauri NSIS | Single `.exe` installer; user installs nothing extra |
| D-09 | CI/CD | GitHub Actions | All issues, builds, tests, and releases on GitHub |

---

## Open Decisions

| # | Question | Blocks | Owner |
|---|----------|--------|-------|
| ~~OD-01~~ | ~~InsightFace buffalo_l vs DeepFace/FaceNet512~~ | **RESOLVED: InsightFace buffalo_l** (ArcFace/R100 via ONNX Runtime; Immich precedent; strongest for aging + sibling disambiguation) | — |
| OD-02 | Default cosine similarity threshold for auto-assign vs uncertain queue | M1 clustering | **Placeholder: auto_assign=0.68, uncertain=0.50. Tune after first real-world scan.** |
| ~~OD-03~~ | ~~Cluster merge UX~~ | **RESOLVED: Explicit "Merge with…" button in person detail panel → person picker → confirmation dialog. No drag-and-drop.** | — |
| ~~OD-04~~ | ~~Multiple faces per photo~~ | **RESOLVED: Each face detected and clustered independently. A photo with 3 faces creates 3 independent records — appears in all 3 people's galleries. Faces below detection size threshold (~20px) are skipped and logged as a count in the UI.** | — |
| ~~OD-05~~ | ~~Delete person~~ | **RESOLVED: Deleting a person removes their name and labels only. All associated face embeddings return to the unnamed queue for re-identification. Photos are never touched.** | — |
| ~~OD-06~~ | ~~FAISS index promotion thresholds~~ | **RESOLVED: Flat (<10K embeddings) → IVFFlat/nlist=256 (10K–250K) → IVFPQ/nlist=2048/PQ16 (250K+). Rebuilds run in background; old index serves queries during rebuild.** | — |

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri 2.0 App Shell (Rust)               │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              React + TypeScript UI                  │   │
│  │         (WebView2 — Edge on Windows)                │   │
│  │                                                     │   │
│  │   Sidebar │ Photo Grid │ Detail Panel               │   │
│  └──────────────────┬──────────────────────────────────┘   │
│                     │ HTTP + WebSocket (127.0.0.1:PORT)     │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│              Python Sidecar (FastAPI + uvicorn)             │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Scanner    │  │  ML Engine   │  │  Query Service   │  │
│  │   Service    │  │  (Swappable) │  │                  │  │
│  │              │  │              │  │  Multi-person    │  │
│  │  File walk   │  │  Detect      │  │  AND search      │  │
│  │  EXIF read   │  │  Embed       │  │  Date filter     │  │
│  │  Progress    │  │  Cluster     │  │  Path lookup     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────────────────┘  │
│         │                 │                                  │
│  ┌──────▼─────────────────▼──────────────────────────────┐  │
│  │              Data Layer                               │  │
│  │                                                       │  │
│  │   SQLite (aiosqlite)          FAISS Index             │  │
│  │   ─────────────────           ──────────────          │  │
│  │   faces.db                    faces.index             │  │
│  │   %APPDATA%\faces-h\          %APPDATA%\faces-h\      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Tauri App Shell (Rust)

Responsibilities:
- Launch the Python sidecar on startup; pass it a dynamically allocated local port
- Shut the sidecar down cleanly on app exit
- Expose Tauri commands to the frontend for system-level operations (open file in Windows Photos, reveal in Explorer)
- Handle auto-launch at system start (optional, post-v1)

The shell does **no ML work**. Its job is process management and OS integration.

### 2. React + TypeScript Frontend

Responsibilities:
- All UI rendering (see `docs/DESIGN.md` for visual direction)
- HTTP requests to the Python sidecar for data
- WebSocket connection for real-time scan progress and re-evaluation notifications
- State management: lightweight (Zustand or React Query — TBD in implementation)

Key views:
- Person list sidebar with face medallions
- Adaptive photo grid (user-controlled thumbnail size)
- Naming / confirmation workflow
- Uncertain face review queue
- Search with multi-person AND + date range
- Scan progress indicator

### 3. Python Sidecar

#### 3a. Scanner Service

- Walks the selected root folder recursively
- Reads image files (JPG, PNG, HEIC, TIFF, RAW)
- Skips corrupt/unreadable files gracefully (logs, continues)
- Sends progress events over WebSocket: `{ scanned: N, total: N, eta_seconds: N }`
- Persists scan state to SQLite on each batch so progress survives app restarts
- Detects new files on subsequent runs (incremental: compares file path + mtime to DB)

Throughput target: ≥500 photos/min on mid-range CPU (i5/Ryzen 5).

#### 3b. ML Engine (Swappable Model Layer)

The face recognition model is hidden behind an abstract interface. The active model is set in `config.json` in `%APPDATA%\faces-h\`.

```
FaceRecognizer (abstract)
├── detect_and_embed(image_path) → List[FaceResult]
│     FaceResult: { bbox, embedding[512], detection_confidence }
│
├── InsightFaceRecognizer   (default: buffalo_l via ONNX Runtime)
└── DeepFaceRecognizer      (alternative: FaceNet512)
```

Both models output 512-dimensional L2-normalized embeddings. Downstream clustering and FAISS are model-agnostic.

**Reliability enforcement:** The ML engine never auto-assigns a face. It returns an embedding and a detection confidence. Assignment confidence (cosine similarity to a cluster centroid) is computed separately and gated by the threshold in config. Faces below the threshold go to the uncertain queue regardless of which model produced them.

#### 3c. Clustering Service

- Computes cosine similarity between a new embedding and existing cluster centroids via FAISS
- If similarity ≥ threshold: tentatively assigns to cluster (still logged as pending if borderline)
- If similarity < threshold: marks face as "uncertain", surfaces to confirmation queue
- Updates cluster centroid on each confirmed assignment (rolling average)
- Triggers re-evaluation job when a user correction is received

#### 3d. Re-evaluation Service

- Triggered by a user correction (mark wrong + reassign)
- Re-scores all embeddings in the affected cluster(s) against updated centroid
- Moves newly-uncertain faces to the confirmation queue
- Emits a summary notification when complete: `{ moved: N, newly_uncertain: N }`
- Runs as a background async task; never blocks browsing

#### 3e. Query Service

- `GET /people` — list all named people with medallion face and photo count
- `GET /people/{id}/photos` — all photos for a person, sorted by date
- `POST /search` — multi-person AND query with optional date range
- `GET /photos/{id}` — photo detail with face assignments
- `GET /queue/uncertain` — faces pending user confirmation
- `POST /photos/{id}/correct` — submit a correction

---

## Data Model

### SQLite Schema (`faces.db`)

```sql
-- Source files
CREATE TABLE photos (
    id          INTEGER PRIMARY KEY,
    path        TEXT NOT NULL UNIQUE,
    mtime       INTEGER NOT NULL,       -- file modified time for incremental scan
    scanned_at  INTEGER,
    width       INTEGER,
    height      INTEGER,
    taken_at    INTEGER                 -- from EXIF if available
);

-- Detected faces
CREATE TABLE faces (
    id              INTEGER PRIMARY KEY,
    photo_id        INTEGER NOT NULL REFERENCES photos(id),
    bbox_x          REAL, bbox_y REAL, bbox_w REAL, bbox_h REAL,
    detection_conf  REAL NOT NULL,
    embedding_id    INTEGER,            -- row index in FAISS index
    person_id       INTEGER REFERENCES people(id),
    assign_conf     REAL,               -- cosine similarity at time of assignment
    assign_status   TEXT NOT NULL       -- 'assigned' | 'uncertain' | 'unreviewed' | 'rejected'
);

-- Named people
CREATE TABLE people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  INTEGER NOT NULL,
    centroid    BLOB                    -- serialized numpy array (rolling average embedding)
);

-- Correction history
CREATE TABLE corrections (
    id              INTEGER PRIMARY KEY,
    face_id         INTEGER NOT NULL REFERENCES faces(id),
    old_person_id   INTEGER,
    new_person_id   INTEGER,
    corrected_at    INTEGER NOT NULL
);

-- Scan state
CREATE TABLE scan_state (
    key     TEXT PRIMARY KEY,
    value   TEXT
    -- keys: 'root_path', 'last_scanned_path', 'status', 'total_files', 'scanned_files'
);
```

### FAISS Index (`faces.index`)

Stores face embeddings keyed by `embedding_id` (matches `faces.embedding_id`).

**Index strategy by library size:**

| Embedding count | Index type | Rationale |
|----------------|-----------|-----------|
| < 10K | `IndexFlatIP` | Exact cosine search; small enough to be instant |
| 10K – 500K | `IndexIVFFlat` | IVF with ~sqrt(N) lists; trained on first batch |
| 500K+ (5TB libraries) | `IndexIVFPQ` | Product quantization; ~300MB for 1.5M vectors vs 3GB flat |

The index is rebuilt automatically when passing each threshold. Rebuilds run in the background.

At maximum scale (5TB, ~1M photos, ~1.5M face embeddings):
- `IndexIVFPQ` with 2048 lists, PQ16: ~300MB on disk, <500MB in memory
- Search latency: <50ms for a 512-dim query across 1.5M embeddings on CPU

---

## IPC Protocol (Tauri ↔ Python Sidecar)

The Tauri shell launches the sidecar with a randomly assigned local port:

```
faces-sidecar.exe --port 51423 --data-dir "%APPDATA%\faces-h"
```

The frontend connects to `http://127.0.0.1:51423` for HTTP and `ws://127.0.0.1:51423/ws` for events. Tauri's `app.config.ts` passes the port to the frontend via an environment variable injected at startup.

**WebSocket event types:**
```json
{ "type": "scan_progress",     "scanned": 1200, "total": 45000, "eta_seconds": 3600 }
{ "type": "faces_ready",       "count": 14 }
{ "type": "reeval_complete",   "moved": 5, "newly_uncertain": 3, "person": "Mom" }
{ "type": "scan_complete" }
```

---

## Face Recognition Model Layer

### Default: InsightFace buffalo_l

- Detection: RetinaFace (part of buffalo_l pack)
- Recognition: ArcFace (buffalo_l) — 512-dim L2-normalized embeddings
- Runtime: ONNX Runtime (CPU execution provider)
- Model files: bundled inside the PyInstaller sidecar (~300MB models included)

### Alternative: DeepFace + FaceNet512

- Detection: MTCNN or RetinaFace (configurable)
- Recognition: FaceNet512 — 512-dim embeddings
- Runtime: TensorFlow Lite (CPU)
- Model files: bundled inside sidecar (~250MB)

### Switching models

Edit `%APPDATA%\faces-h\config.json`:
```json
{ "face_model": "insightface_buffalo_l" }
```
or
```json
{ "face_model": "deepface_facenet512" }
```

A model change invalidates the FAISS index and triggers a re-scan prompt. Embeddings are not cross-model compatible.

---

## Swappable Model Interface (Python)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np

@dataclass
class FaceResult:
    bbox: tuple[float, float, float, float]   # x, y, w, h (normalized 0-1)
    embedding: np.ndarray                      # shape (512,), L2-normalized
    detection_confidence: float

class FaceRecognizer(ABC):
    @abstractmethod
    def detect_and_embed(self, image_path: str) -> list[FaceResult]:
        """Detect all faces in image and return embeddings. Never raises on bad input."""
        ...
```

---

## Reliability Rules (enforced in code, not policy)

1. A face is never written to `assign_status = 'assigned'` unless `assign_conf >= config.threshold`.
2. `assign_conf` is always cosine similarity to the cluster centroid at assignment time.
3. Any face with `assign_conf < config.threshold` goes to `assign_status = 'uncertain'`.
4. The uncertain queue count is always visible in the sidebar (badge).
5. No face appears in search results until it has `assign_status = 'assigned'`.
6. Re-evaluation does not auto-promote uncertain faces — user confirmation is always required.

---

## GitHub Structure

### Repository Layout (target)

```
faces-h/
├── src-tauri/          # Tauri/Rust shell
├── src/                # React + TypeScript frontend
├── sidecar/            # Python ML backend
│   ├── api/            # FastAPI routes
│   ├── ml/             # FaceRecognizer implementations
│   ├── db/             # SQLite operations
│   ├── index/          # FAISS index manager
│   └── services/       # Scanner, clustering, re-evaluation
├── docs/
│   ├── PRD.md
│   ├── DESIGN.md
│   └── ARCHITECTURE.md
└── .github/
    ├── workflows/
    │   ├── ci.yml          # Lint + test on every PR
    │   ├── build.yml       # Build Windows installer on push to main
    │   └── release.yml     # Create GitHub Release on version tag
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.yml
    │   ├── feature_request.yml
    │   └── spike.yml
    └── pull_request_template.md
```

### Labels

| Label | Use |
|-------|-----|
| `spike` | Time-boxed investigation; no deliverable code required |
| `ml` | Face recognition, clustering, re-evaluation pipeline |
| `ui` | Frontend React components |
| `infra` | Tauri shell, IPC, packaging, CI |
| `db` | SQLite schema, migrations |
| `perf` | Throughput, memory, index size |
| `bug` | Something is broken |
| `blocked` | Waiting on an open decision |

### Milestones

| Milestone | Contents | Goal |
|-----------|----------|------|
| M0 — Spike | OD-01: Benchmark InsightFace vs DeepFace on a real family photo sample | Resolve face model choice; measure CPU throughput; validate 500 photos/min target |
| M1 — Foundation | Tauri shell + Python sidecar IPC; SQLite schema; file scanner; FAISS index scaffolding | App starts, scans a folder, stores embeddings |
| M2 — Core ML | Face detection + embedding pipeline; clustering; uncertain queue | Named clusters appear in UI; confidence queue works |
| M3 — Naming & Gallery | Person sidebar; medallion system; photo gallery per person; name/merge/delete | User can name people and browse their photos |
| M4 — Search | Multi-person AND search; date filter; open in system viewer; file path display | Full search workflow functional |
| M5 — Corrections | Mark wrong; reassign; re-evaluation job; summary notification | Correction loop works end-to-end |
| M6 — Ship | NSIS installer; onboarding flow; performance profiling on 5TB dataset; edge case hardening | v1.0 release |

### GitHub Actions

**`ci.yml`** — runs on every PR:
- Python: `pytest` with coverage; `ruff` lint; `mypy` type check
- Frontend: `vitest`; `eslint`; `tsc --noEmit`
- Tauri: `cargo clippy`; `cargo test`

**`build.yml`** — runs on push to `main`:
- PyInstaller build of sidecar → `sidecar/dist/faces-sidecar.exe`
- Tauri build → `src-tauri/target/release/bundle/nsis/*.exe`
- Upload installer artifact to the workflow run

**`release.yml`** — runs on tag `v*.*.*`:
- All steps from `build.yml`
- Create GitHub Release with the `.exe` installer attached

### Branch Naming

```
feat/<issue-id>-<short-slug>    # e.g. feat/12-face-clustering
fix/<issue-id>-<short-slug>
spike/<short-slug>
chore/<short-slug>
```

`main` is protected: PR required, CI must pass, no direct push.

---

## Tech Stack Summary

| Layer | Technology | Version |
|-------|-----------|---------|
| App shell | Tauri | 2.x |
| Frontend framework | React | 18.x |
| Frontend language | TypeScript | 5.x |
| Frontend build | Vite | 5.x |
| ML backend | Python | 3.11+ |
| HTTP/WS server | FastAPI + uvicorn | latest stable |
| Face model (default) | InsightFace buffalo_l + ONNX Runtime | latest stable |
| Face model (alt) | DeepFace + FaceNet512 | latest stable |
| Vector index | FAISS (faiss-cpu) | latest stable |
| Metadata DB | SQLite via aiosqlite | latest stable |
| EXIF reading | Pillow + piexif | latest stable |
| Sidecar packaging | PyInstaller | latest stable |
| Installer | Tauri NSIS bundler | built-in |
| Python linting | Ruff | latest stable |
| Python types | mypy | latest stable |
| Python tests | pytest + pytest-cov | latest stable |
| Frontend tests | Vitest + @testing-library/react | latest stable |
| CI/CD | GitHub Actions | — |

---

## Key Risks

| Risk | Severity | Mitigation |
|------|----------|-----------|
| InsightFace/DeepFace precision insufficient for siblings across ages | High | M0 spike against a real family photo dataset before writing clustering code |
| FAISS IVF index rebuild on large libraries takes too long | Medium | Rebuild runs in background; app remains usable during rebuild; notify user on completion |
| PyInstaller sidecar triggers Windows antivirus (common for PyInstaller bundles) | Medium | Evaluate Nuitka as an alternative if antivirus false positives appear in testing |
| Tauri WebView2 rendering edge cases on older Windows 10 installs | Low | WebView2 is auto-updated by Windows; Tauri bundles a WebView2 bootstrapper as fallback |
| HEIC/RAW file support on Windows without extra codecs | Medium | Use Pillow-HEIF for HEIC; test RAW support early; document unsupported RAW formats |
| Memory pressure on 5TB library (FAISS index in RAM) | High | Use IVFFlat for early milestones; promote to IVFPQ before M6; target <500MB index in RAM |
