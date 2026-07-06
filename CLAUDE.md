# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project

**faces-h** is a local Windows desktop application that organizes personal photo libraries by face recognition. All processing is on-device. No data leaves the machine.

Key docs (read before making changes):
- `docs/PRD.md` — product requirements and user stories
- `docs/ARCHITECTURE.md` — all technical decisions and data model
- `docs/DESIGN.md` — visual design direction and color tokens
- `docs/IMPLEMENTATION_PLAN.md` — the 20 GitHub issues, their DoD, and dependency graph

---

## How We Work

**All work is tracked as GitHub Issues** at `https://github.com/justminime/faces-h/issues`. Every code change must close a numbered issue. No ad-hoc changes.

**To start a ticket:** use `/impl-issue {N}` — creates a branch, implements the issue, runs tests, opens a PR.  
**To file a new ticket:** use `/new-issue`.  
**To run tests:** use `/run-tests`.  
**To build a release:** use `/build-release v{version}`.  
**Before merging ML-touching PRs:** run `/check-reliability`.

**Branch naming:** `feat/{issue-number}-{short-slug}` · `fix/{issue-number}-{short-slug}` · `chore/{slug}`

**`main` is protected.** PR required. CI must pass. No direct push.

---

## Stack

| Layer | Technology |
|-------|-----------|
| App shell | Tauri 2.x (Rust) |
| Frontend | React 18 + TypeScript 5 + Vite |
| ML backend | Python 3.11+ sidecar (FastAPI + uvicorn) |
| IPC | Local HTTP + WebSocket (`127.0.0.1:{dynamic-port}`) |
| Face model | InsightFace buffalo_l via ONNX Runtime (swappable) |
| Vector index | FAISS (auto-promotes: Flat → IVFFlat → IVFPQ) |
| Database | SQLite via aiosqlite |
| Installer | PyInstaller (sidecar) + Tauri NSIS |
| CI/CD | GitHub Actions (`ci.yml`, `build.yml`, `release.yml`) |

---

## Repository Layout

```
src-tauri/      Tauri/Rust shell
src/            React + TypeScript frontend
sidecar/
  api/          FastAPI routes
  ml/           FaceRecognizer implementations (swappable)
  db/           SQLite schema and connection
  index/        FAISS index manager
  services/     Scanner, clustering, re-evaluation
  tests/        pytest tests
.github/
  workflows/    ci.yml · build.yml · release.yml
  ISSUE_TEMPLATE/
.claude/skills/ Project-specific Claude Code skills
docs/           PRD · ARCHITECTURE · DESIGN · IMPLEMENTATION_PLAN
```

---

## Definition of Done (every PR)

- [ ] All issue acceptance criteria met (binary pass/fail)
- [ ] Tests written and passing
- [ ] `ruff check sidecar/` passes
- [ ] `mypy sidecar/ --ignore-missing-imports` passes
- [ ] `npm run type-check` passes
- [ ] `npm run lint` passes
- [ ] `cargo clippy -- -D warnings` passes
- [ ] CI green on the PR branch
- [ ] No photo files written, moved, or deleted — the only exceptions are the explicit, user-confirmed "delete" (#154) and "rotate" (#160) actions, which behave identically on local and network folders (#164): every original is backed up in the app first (structure-mirrored, #161), then goes to the Recycle Bin when possible or a safe fallback removal otherwise — nothing is ever silently lost
- [ ] No hardcoded ports, paths, or credentials

---

## Reliability Rules (enforced in code — never bypass)

These six rules appear in `docs/ARCHITECTURE.md § Reliability Rules`. Any PR touching `sidecar/ml/`, `sidecar/services/clustering.py`, or `sidecar/services/reeval.py` must pass `/check-reliability` before merge.

1. A face is never set to `assign_status = 'assigned'` unless `assign_conf >= config.threshold`
2. `assign_conf` is always cosine similarity to cluster centroid, stored at assignment time
3. Faces below `auto_assign_threshold` → `assign_status = 'uncertain'`
4. Uncertain queue count badge always visible in sidebar
5. Search results only include `assign_status = 'assigned'` faces
6. Re-evaluation never auto-promotes uncertain faces — user confirmation required

---

## Commands

```bash
# Python sidecar (local dev)
python -m venv sidecar/.venv
sidecar/.venv/Scripts/pip install -r sidecar/requirements.txt
python sidecar/main.py --port 51423 --data-dir "%APPDATA%\faces-h"

# Python tests
cd sidecar && pytest tests/ --cov=. -q
cd sidecar && ruff check . && mypy . --ignore-missing-imports

# Frontend
npm install
npm run dev          # dev server at localhost:5173
npm test             # vitest
npm run type-check   # tsc --noEmit
npm run lint         # eslint

# Tauri
npm run tauri dev    # full app in dev mode
npm run tauri build  # production build (Windows only)

# Slow perf benchmarks (not in CI)
pytest -m slow sidecar/tests/test_performance.py
```

---

## GitHub Issues Map

| # | Plan ID | Title |
|---|---------|-------|
| #1 | P0-01 | Scaffold repository structure |
| #2 | P0-02 | GitHub Actions workflows and issue templates |
| #3 | P1-01 | FastAPI sidecar scaffold and PyInstaller spec |
| #4 | P1-02 | SQLite schema and migrations |
| #5 | P1-03 | File scanner service |
| #6 | P1-04 | FAISS index manager with auto-promotion |
| #7 | P1-05 | ML engine — InsightFace buffalo_l |
| #8 | P1-06 | Clustering service with reliability rules |
| #9 | P2-01 | Tauri 2.0 app shell scaffold |
| #10 | P2-02 | Sidecar lifecycle and IPC bridge |
| #11 | P3-01 | React + TypeScript scaffold |
| #12 | P3-02 | Design system tokens and Medallion component |
| #13 | P4-01 | Gallery view — three-panel layout |
| #14 | P4-02 | API client, naming workflow, merge flow |
| #15 | P4-03 | Uncertain face review queue |
| #16 | P5-01 | Multi-person AND search with date filter |
| #17 | P5-02 | Corrections and re-evaluation pipeline |
| #18 | P6-01 | Onboarding flow |
| #19 | P6-02 | Performance profiling and 5TB validation |
| #20 | P6-03 | Windows release build validation (v0.1.0) |
