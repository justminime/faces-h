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
| M6 — Ship (onboarding, installer, security hardening) | ✅ Done |
| Code signing (SignPath Foundation) | 🔲 Pending approval |

---

## What It Does

- **Scan** folders of any size (tested to 5TB / ~1M photos) in the background — local drives, network shares, and NAS included
- **Detect and cluster** faces automatically — each cluster represents one likely person; FAISS-backed matching stays fast as the library grows
- **Name people** by clicking a cluster; all their photos are labeled instantly (duplicate names offer a merge)
- **Review uncertain faces** — anything below the confidence threshold waits in a queue for your confirmation; the app never silently guesses
- **Search** by one or more people together, with date ranges and an "exactly these people" mode
- **Correct mistakes** — mark a face wrong and the whole cluster re-evaluates automatically
- **Carry recognition across libraries** — export/import named identities as a small file (no photos inside)
- **See what it's doing** — live activity log with engine and app streams, adjustable verbosity
- **Find blurry photos** — a live cutoff slider surfaces them worst-first so you see exactly what each level captures
- **Find duplicates** — exact copies and the same shot saved at different sizes, each copy listed with its folder, filename, and size; "keep one per group" in one click
- **Delete with full detail** — the confirmation shows every file's thumbnail, name, folder, and size plus the total space freed; local files go to the Windows Recycle Bin (recoverable), and network files — which have no Recycle Bin — are clearly marked before their permanent delete
- **Never touches your files otherwise** — scanning and browsing are strictly read-only; the ONLY file-modifying action is that explicit, confirmed Recycle-Bin delete (always recoverable); photos removed from disk hide themselves and revive if restored

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
python sidecar/main.py --port 51423 --data-dir "%APPDATA%\com.faces-h.app"

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

## Configuration

Optional `config.json` in `%APPDATA%\com.faces-h.app\` (all keys optional; defaults shown):

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

Invalid values fall back to defaults with a logged warning. Logs: `%APPDATA%\com.faces-h.app\logs\`.

## Security

- IPC between Tauri and the sidecar is authenticated with a 256-bit per-session token from the OS CSPRNG (generated at startup, never reused)
- Strict Content Security Policy — no external script or font sources
- All third-party GitHub Actions pinned to immutable commit SHAs
- Installer code-signed via [SignPath Foundation](https://signpath.org) (pending approval)
- Scanning and browsing never write, move, or delete any photo file; the single file-modifying action is the explicit, user-confirmed "Move to Recycle Bin" delete — never a permanent erase

## Privacy

No data ever leaves your machine. See [`landing/privacy.html`](landing/privacy.html) or [shifth.com/faces-h/privacy.html](https://shifth.com/faces-h/privacy.html).

## Docs

- [`docs/PRD.md`](docs/PRD.md) — product requirements
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — technical decisions and data model
- [`docs/DESIGN.md`](docs/DESIGN.md) — visual design direction
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — implementation issues and dependency graph
