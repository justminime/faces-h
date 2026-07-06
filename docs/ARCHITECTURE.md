# Software Architecture: faces-h

**Version:** 1.3
**Status:** Draft
**Last updated:** 2026-07-05

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
| D-07 | Vector index | FAISS IVF | Scales to 1M+ embeddings on CPU; IVF partitioning avoids full scans; promoted from Flat as library grows. Wired into assignment since #106: face embeddings are indexed by face id, a top-k shortlist is re-checked exactly against live centroids, and an exhaustive scan remains the fallback below the auto-assign gate |
| D-08 | Packaging | PyInstaller (sidecar) + Tauri NSIS | Single `.exe` installer; user installs nothing extra |
| D-09 | CI/CD | GitHub Actions | All issues, builds, tests, and releases on GitHub; all third-party actions pinned to immutable commit SHAs |
| D-10 | Code signing | SignPath Foundation | Free OSS certificate; signing runs in SignPath infrastructure — private key never touches GitHub runners; installer signed before upload to GitHub Releases |
| D-11 | IPC auth | Per-session token (64-char hex, 256-bit OS CSPRNG) | Generated in Rust at startup via `rand::rngs::OsRng` (#112); passed as `--token` CLI arg to sidecar; required on all HTTP requests (`X-Faces-Token` header) and WebSocket connections (`?token=` query param); `/health` exempt |
| D-12 | Content Security Policy | Tauri `csp` field | `default-src 'self'`; `connect-src http://127.0.0.1:* ws://127.0.0.1:*`; no external script or font sources |
| D-13 | Scan-root trust boundary | Token is the boundary — no separate allowlist | Any local process holding the per-session token is treated as the user. A `/scan/start` allowlist enforced by the sidecar would add no security (the same token authorizes adding roots) while complicating the dialog→scan flow; revisit if the token ever becomes long-lived (#112 M-2, decided 2026-07-05) |

---

## Open Decisions

| # | Question | Blocks | Owner |
|---|----------|--------|-------|
| ~~OD-01~~ | ~~InsightFace buffalo_l vs DeepFace/FaceNet512~~ | **RESOLVED: InsightFace buffalo_l** (ArcFace/R100 via ONNX Runtime; Immich precedent; strongest for aging + sibling disambiguation) | — |
| OD-02 | Default cosine similarity threshold for auto-assign vs uncertain queue | M1 clustering | **Placeholder: auto_assign=0.68, uncertain=0.50. Tune after first real-world scan. Currently code constants; config.json support tracked in #107** |
| ~~OD-03~~ | ~~Cluster merge UX~~ | **RESOLVED: Explicit "Merge with…" button in person detail panel → person picker → confirmation dialog. No drag-and-drop.** | — |
| ~~OD-04~~ | ~~Multiple faces per photo~~ | **RESOLVED: Each face detected and clustered independently. A photo with 3 faces creates 3 independent records — appears in all 3 people's galleries. Faces below detection size threshold (~20px) are skipped and logged as a count in the UI (skip not yet implemented — #111).** | — |
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

**Naming & identity workflow.** Selecting a person in the sidebar shows their
gallery with a header carrying that person's medallion, name, and a
**Name this person / Rename** action. The action opens `NamingModal`
(`POST /people/{id}/name`); on save the sidebar/people list is refetched so the
new name propagates everywhere. In the Detail Panel, each face's `person_id` is
resolved to a display name (the real name, or "Unnamed") rather than a bare
"Unknown", and the face belonging to the person currently being viewed is
enlarged and highlighted with a "this person" badge so it is identifiable in
group photos. Person names are resolved client-side from the loaded people
list, so a rename updates the panel without an extra round-trip.

**Auto-merge on duplicate name.** If the user types a name in `NamingModal` that
already exists (case-insensitive), the Save button becomes **Merge** and a hint
line appears. On confirm, `mergePeople(sourceId, targetId)` is called instead of
`renamePerson` — the source cluster's faces move to the target and the source
record is deleted. No second cluster with the same name is ever created.

**Post-naming library sweep.** After any name is set (`POST /people/{id}/name`)
or after a merge, the sidecar runs `ReEvaluationService.sweep_for_person` as a
background task. The sweep has three passes:
1. **Uncertain** faces whose `suggested_person_id` matches — confirmed if cosine ≥ `auto_assign_threshold`
2. **Unreviewed** faces — embedded and compared against the named centroid; pulled in if ≥ threshold
3. **Unnamed-cluster** faces — moved if this person scores highest AND ≥ threshold

The surviving centroid is rebuilt after each sweep. A `sweep_complete` WebSocket
event is emitted; the frontend shows a toast ("Found N more photos — refreshing")
and bumps `scanVersion` to refresh the sidebar count. Rule 6 is respected: uncertain
faces are never auto-promoted.

**Multi-person photo panel.** The `GET /people/{id}/photos` endpoint paginates at
the photo level (returning photos that contain the selected person) but now returns
**all assigned faces** in each photo, not only the selected person's faces. The
Detail Panel thus shows every named (or unnamed) person present in a photo, not
just the one currently selected in the sidebar.

**Sidebar ··· menu.** All library, identity, and appearance controls live in a single `···` dropdown button in the sidebar header, organized in three sections: Library (Add Folder, Rescan), Identity (Export / Import Named People), Appearance (Light / Dark / Follow System with ✓ on active). Replaces the previous scattered text-link buttons. The `useTheme` hook is called directly inside `Sidebar` so the component owns theme state without threading it through App.

**Activity log.** A collapsible strip fixed at the bottom of the app shell (below the three-panel layout). Shows timestamped entries for all WebSocket events. Five verbosity levels controlled by pill buttons in the bar:

| Level | Content |
|---|---|
| Off | Log hidden; only the pill row remains |
| Errors | Warnings only (network offline, file errors) |
| Scan | Scan progress, completions, sweeps, drive warnings |
| All | Every event (default) |
| Debug | Everything + filename on each scan progress tick |

Implemented as a Zustand store (`src/store/log.ts`) with `push()` / `upsertLast()` / `clear()`. `upsertLast` replaces the previous entry of the same kind so rapidly-updating progress ticks don't flood the list. Capped at 200 entries. Auto-scrolls when the user is at the bottom; stops auto-scrolling when they scroll up.

**Incremental photo loading.** Photos are loaded `PAGE_SIZE=50` at a time using an
`IntersectionObserver` sentinel at the bottom of the grid. The first page uses
`?order=random` so SQLite samples from the full pool on each visit (different
photos on each session open). Subsequent pages use chronological order. A
`generation` counter cancels stale fetches when the user switches people quickly.

**Startup people cache.** The people list is written to `localStorage`
(`faces_h_people_cache`) after every successful load. On next launch the sidebar
renders from cache instantly while the sidecar starts, then updates in place.

**Theme switching.** A native Tauri menu under View → Light Mode / Dark Mode /
Follow System writes a `data-theme` attribute to `<html>` and persists the
choice to `localStorage` (`faces_h_theme`). The CSS token file has three
selector blocks: `:root` (light defaults), `@media (prefers-color-scheme: dark)
:root:not([data-theme="light"])` (OS dark, unless user explicitly chose light),
and `:root[data-theme="dark"]` (explicit dark override).

### 3. Python Sidecar

#### 3a. Scanner Service

- Walks the selected root folder recursively
- Reads image files (JPG, PNG, HEIC, TIFF, RAW)
- Skips corrupt/unreadable files gracefully (logs, continues)
- Sends progress events over WebSocket: `{ scanned, total, eta_seconds, current_file }`
- Persists scan state to SQLite on each batch so progress survives app restarts
- Detects new files on subsequent runs (incremental: compares file path + mtime to DB)

**Network / UNC folder support** (issue #89):
- `is_network_path()` detects UNC paths (`\\server\share`) and mapped network drives via Win32 `GetDriveTypeW`
- `check_reachable()` tests `os.path.isdir()` before starting a walk — offline shares get a `drive_offline` WS event immediately, no hang
- Per-directory errors during `os.walk` are logged and skipped; the walk continues through the rest of the tree
- Mid-scan disconnection: after 5 consecutive per-file OS errors on a network path, the scanner pauses, retries up to 3× with 5 s delay, then broadcasts `drive_offline` and stops cleanly without DB corruption
- On rescan: each root is checked for reachability first; offline roots emit `drive_offline` and are skipped while online roots continue normally
- The scanner **never writes, moves, or deletes** any file — network or local
- The ONLY file-modifying action in the product is the explicit, user-confirmed delete (#154/#158): local files go to the Recycle Bin via send2trash (never a permanent erase); network shares have no Recycle Bin, so files there are permanently removed ONLY when the request carries `allow_permanent_on_network` — which the UI sets after the confirmation dialog has listed those files with an explicit permanent-delete warning. The DB row is marked `missing` (#105) so restoring a file + rescanning revives it with its faces intact
- `scan_roots` table gains `is_network` (INTEGER) and `last_seen_at` (INTEGER) columns; applied via idempotent `ALTER TABLE` migrations

Throughput target: ≥500 photos/min on mid-range CPU (i5/Ryzen 5). Network scans may be 10–100× slower; progress bar reflects real counts.

#### 3b. ML Engine (Swappable Model Layer)

The face recognition model is hidden behind an abstract interface. The active model will be set in `config.json` in the app data directory (**planned — #107**; today the factory defaults to buffalo_l and the thresholds are code constants).

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

- Computes cosine similarity between a new embedding and cluster centroids — candidates shortlisted via the FAISS face index, re-checked exactly against live centroids, with an exhaustive fallback below the auto-assign gate (#106)
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

**Post-naming / post-merge sweep** (`sweep_for_person`): triggered automatically
after `set_name` and after any cluster merge. Three-pass background job:
1. Uncertain faces with `suggested_person_id = person_id`, cosine ≥ threshold → promote to assigned
2. Unreviewed faces across all unnamed clusters → compare embedding to centroid, assign if ≥ threshold
3. Faces in **unnamed** clusters → move if this person scores higher AND ≥ threshold. Faces in *named* clusters are never moved automatically — taking a face from a cluster the user has explicitly named requires user confirmation (Rule 6 spirit)
Centroid is rebuilt from scratch after all moves. Emits `sweep_complete { person_id, moved }` over WebSocket.

#### 3e. Query Service

- `GET /people` — list all named people with medallion face and photo count
- `GET /people/{id}/photos?offset=N&limit=N&order=date|random` — paginated photos for a person. Returns all assigned faces per photo (not just the selected person's face) so multi-person photos show everyone. `order=random` uses `RANDOM()` on the inner photo-ID subquery so each visit surfaces a different mix; subsequent pages use chronological order.
- `POST /search` — multi-person query with optional date range. `match` selects the semantics:
  - `"contains"` (default) — every selected person appears in the photo (others allowed). AND logic via one indexed subquery per `person_id`.
  - `"exact"` — the photo's set of **assigned** people equals exactly the selection; a photo with any additional named person is excluded. Uncertain/unassigned faces don't count, so they never disqualify a match. (Reliability Rule 5 preserved — only `assigned` faces are considered.)
- `GET /photos/{id}` — photo detail with face assignments
- `GET /queue/uncertain` — faces pending user confirmation
- `POST /photos/{id}/correct` — submit a correction

#### 3f. Image Serving

The webview cannot load `C:\…` file paths directly, so all imagery is served as JPEG over the sidecar HTTP API from the original files (opened **read-only** — never modified, moved, or deleted):

- `GET /photos/{id}/thumbnail?size=N` — downscaled JPEG of a photo for the gallery and search grids (EXIF-orientation aware; `size` bounded 16–1024, default 256). The frontend builds the absolute URL via `photoThumbUrl(id)` against the sidecar origin.
- `GET /faces/{id}/crop` — bounding-box crop of a single face, used for person medallions/avatars and the uncertain-review queue. Frontend helper: `faceCropUrl(id)`.

#### 3g. Library Import/Export

Names and their face-embedding centroids can be carried between libraries (a new photo folder, or another machine) so identities don't have to be re-named from scratch. The bundle contains **no image files or paths** — only named identities and centroids — preserving the on-device rule.

- `GET /export` — returns a portable JSON bundle `{ version, exported_at, people: [{ name, centroid_b64 }] }` for every **named** person that has a centroid. The frontend downloads it as `faces-h-library.json`.
- `POST /import` — accepts a bundle and, for each imported name, matches its centroid against the current library's clusters by cosine similarity. The name is applied to the best-matching **unnamed** cluster above `match_threshold` (defaults to the auto-assign threshold, 0.68). A best match that is already named a *different* name is reported as a **conflict** and never overwritten; no match above threshold is reported as **unmatched**. Returns `{ applied, unmatched, conflicts, total }`.
- Import only sets `people.name`; it never changes `assign_status`/`assign_conf`, so the reliability rules are untouched.

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

The Tauri shell allocates an ephemeral local port, generates a per-session auth token (D-11), and launches the sidecar with both:

```
faces-sidecar.exe --port {ephemeral} --data-dir "%APPDATA%\com.faces-h.app" --token {random} --parent-pid {shell-pid}
```

The frontend obtains the base URL and token via the `get_sidecar_url` / `get_sidecar_token` Tauri commands and the `sidecar-ready` event payload — nothing is hardcoded. Requests carry the token as an `X-Faces-Token` header, or as `?token=` for `<img>` src and WebSocket URLs (which cannot set headers); only `/health` is exempt, and `/ws` validates the token itself (close code 4401 on mismatch). The shell supervises the sidecar (restart-once watchdog) and the sidecar exits when the shell's PID disappears, so the pair behaves as one application (#119).

**WebSocket event types:**
```json
{ "type": "scan_progress",          "scanned": 1200, "total": 45000, "eta_seconds": 3600 }
{ "type": "model_download_progress","progress": 0.42 }
{ "type": "reeval_complete",        "moved": 5, "newly_uncertain": 3, "person": "Mom" }
{ "type": "scan_complete",          "scanned": 1200, "total": 45000 }
{ "type": "sweep_complete",         "person_id": 7, "moved": 12 }
{ "type": "drive_offline",          "path": "\\\\NAS\\Photos" }
```

`scan_progress` is broadcast every 10 processed files (face detection is
seconds-per-photo, so a coarser interval would leave the UI without an update
for minutes). The frontend refreshes the people sidebar on **every**
`scan_progress` — not only on `scan_complete` — so clusters appear live as the
scan runs rather than all at once at the end.

---

## Face Recognition Model Layer

### Default: InsightFace buffalo_l

- Detection: SCRFD (`det_10g`, part of buffalo_l pack) — bbox + 5-point keypoints
- Recognition: ArcFace (`w600k_r50`) — 512-dim L2-normalized embeddings
- Runtime: ONNX Runtime (CPU execution provider)
- Model files: **downloaded on first run** (~300 MB zip → `{data_dir}/models/buffalo_l/`), not bundled in the executable. Onboarding shows a download progress bar driven by the bytes landing under `models/`.

**Only the detection + recognition models are loaded** via
`FaceAnalysis(allowed_modules=["detection", "recognition"])`. The buffalo_l pack
also ships 3D-landmark (`1k3d68`), 2D-landmark (`2d106det`), and gender-age
models that we never read. Loading them is wasteful and, critically, the
3D-landmark model's `mean_lmk` data loads as `None` in a frozen (PyInstaller)
build — crashing detection on every face with `'NoneType' object has no
attribute 'shape'`. Restricting `allowed_modules` skips those models entirely.

### Packaging notes (frozen / PyInstaller build)

- InsightFace aligns faces with `skimage.transform`, and scikit-image uses
  `lazy_loader`, so its submodules are invisible to PyInstaller's static
  analysis. The spec must `collect_submodules("skimage")` (+ its `scipy`
  backend) and `collect_data_files("skimage")`. Do **not** `collect_all` the
  whole scientific stack — it bloats the onefile bundle enough that extraction
  exceeds the sidecar's startup timeout, and the app appears to crash on launch.
- The Rust shell waits up to 180 s for the sidecar to bind its port; onefile
  extraction + first-run Defender scan must finish within that window.
- `faces-sidecar.exe --selftest <image> --data-dir <dir>` runs detection on one
  image and logs the result (+ a full traceback on failure) — use it to verify a
  frozen build's ML stack without a full library scan.

### Upgrade & user-data location

- All user data lives in the Tauri per-user app-data directory,
  `%APPDATA%\com.faces-h.app\` (`faces.db`, `models/`, `logs/`). This path is
  derived from the app **identifier** (`com.faces-h.app`), not the version, so it
  is stable across upgrades — the library and named people survive reinstalls.
- The NSIS installer hooks (`src-tauri/nsis/hooks.nsi`) terminate a running
  `faces-h.exe` **and** `faces-sidecar.exe` before copying files, so an in-place
  upgrade isn't blocked by a locked sidecar binary. Tauri's own running-app check
  only covers `faces-h.exe`; the Python sidecar is a separate process we must kill
  explicitly.
- Uninstall removes only the install directory and the Defender exclusion; it
  **never** deletes `%APPDATA%\com.faces-h.app`, so uninstall/reinstall preserves
  the library. To fully reset, delete that folder manually.
- On startup the Rust shell kills any orphaned `faces-sidecar.exe` from a prior
  crash before spawning a fresh one, so a stale sidecar can't hold the SQLite WAL
  or shadow the new instance.

### Alternative: DeepFace + FaceNet512

- Detection: MTCNN or RetinaFace (configurable)
- Recognition: FaceNet512 — 512-dim embeddings
- Runtime: TensorFlow Lite (CPU)
- Model files: bundled inside sidecar (~250MB)

### Runtime configuration (`config.json`, #107)

Optional file at `%APPDATA%\com.faces-h.app\config.json`. All keys optional;
invalid values fall back to defaults with a logged warning. Defaults:

```json
{
  "face_model": "insightface_buffalo_l",
  "auto_assign_threshold": 0.68,
  "uncertain_threshold": 0.50,
  "min_face_px": 20,
  "min_detection_confidence": 0.5,
  "ui_log_level": "info",
  "blur_threshold": 60
}
```

- `face_model` selects the recognizer via `ml/factory.py`; unknown names fail loudly at startup
- the two thresholds gate Reliability Rules 1/3 (validated: 0 < uncertain < auto_assign <= 1)
- `min_face_px` / `min_detection_confidence` implement OD-04's tiny/low-confidence detection skip (#111)
- `ui_log_level` (`warning`|`info`|`debug`) tunes the engine->UI activity-log stream (#143); log files always capture everything
- `blur_threshold` is the default sharpness cutoff for the blurry-photos view (#154); the UI slider overrides it per request

Generated artifacts live alongside it: `cache/thumbs/` and `cache/faces/` (image disk cache, #114 — 2 GB LRU)
and `faces.index` (the FAISS candidate index, #106); all rebuildable, safe to delete.

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
