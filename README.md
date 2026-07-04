# faces-h

A local Windows desktop application that organizes personal photo libraries by face recognition. Point it at your photo folder — it finds every face, lets you name people, and makes every photo of Mom or Grandpa instantly searchable.

**All processing runs on your machine. No cloud. No account. No data leaves your drive.**

---

## Status

Active development — core features complete. See [GitHub Issues](https://github.com/justminime/faces-h/issues) for current work.

| Milestone | Status |
|-----------|--------|
| M1 — Foundation (repo, CI/CD, sidecar, DB, scanner, FAISS, Tauri shell, React scaffold) | ✅ Done |
| M2 — Core ML (face detection, clustering, uncertain queue) | ✅ Done |
| M3 — Gallery UI (three-panel layout, naming, merge, corrections) | ✅ Done |
| M4 — Search (multi-person AND, date filter, exact-people mode) | ✅ Done |
| M5 — Corrections (mark wrong, re-evaluation pipeline) | ✅ Done |
| M6 — Ship (onboarding, installer, security hardening, code signing) | 🔲 In progress |

---

## What It Does

- **Scan** a folder of any size (tested to 5TB / ~1M photos) in the background while you use your computer
- **Detect and cluster** faces automatically — each cluster represents one likely person
- **Name people** by clicking a cluster; all their photos are labeled instantly
- **Search** by one or more people — find every photo where Mom and Dad appear together
- **Correct mistakes** — mark a face wrong, and the app re-evaluates the whole cluster automatically
- **Never touches your files** — read-only; no moves, renames, or copies

---

## Stack

| Layer | Technology |
|-------|-----------|
| App shell | Tauri 2.x (Rust) |
| Frontend | React 18 + TypeScript + Vite |
| ML backend | Python 3.11 sidecar (FastAPI) |
| Face model | InsightFace buffalo_l (ONNX Runtime, CPU-only) |
| Vector index | FAISS (auto-scales to 1M+ embeddings) |
| Database | SQLite (local, portable, in `%APPDATA%\faces-h\`) |
| Installer | Single `.exe` — no Python, Node, or Rust required |
| Code signing | [SignPath Foundation](https://signpath.org) (free OSS certificate) |

---

## Development

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full technical design.  
See [`CLAUDE.md`](CLAUDE.md) for how to work on this project with Claude Code.

### Prerequisites

- Windows 10/11
- Python 3.11+
- Node.js 20+
- Rust (stable)

### Run locally

```bash
# Python sidecar
python -m venv sidecar/.venv
sidecar/.venv/Scripts/pip install -r sidecar/requirements.txt
python sidecar/main.py --port 51423 --data-dir "%APPDATA%\faces-h"

# Frontend + Tauri (in a second terminal)
npm install
npm run tauri dev
```

### Tests

```bash
cd sidecar && pytest tests/ -q     # Python
npm test                           # Frontend
cargo test --manifest-path src-tauri/Cargo.toml  # Rust
```

---

## Security

- IPC between Tauri and the sidecar is authenticated with a per-session token (generated at startup, never reused)
- Strict Content Security Policy — no external script or font sources
- All third-party GitHub Actions pinned to immutable commit SHAs
- Installer code-signed via [SignPath Foundation](https://signpath.org) (pending approval)
- The app never writes, moves, or deletes any photo file — scanner is strictly read-only

## Privacy

No data ever leaves your machine. See [`landing/privacy.html`](landing/privacy.html) or [shifth.com/faces-h/privacy.html](https://shifth.com/faces-h/privacy.html).

## Docs

- [`docs/PRD.md`](docs/PRD.md) — product requirements
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — technical decisions and data model
- [`docs/DESIGN.md`](docs/DESIGN.md) — visual design direction
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — implementation issues and dependency graph
