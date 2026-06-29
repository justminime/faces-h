---
name: run-tests
description: Run the full test suite (Python, frontend, Rust) and report results. Use when the user asks to run tests, check test status, or verify a change didn't break anything.
---

Run all three test suites for faces-h and report a summary.

## Python tests

```
cd sidecar
.venv/Scripts/pytest tests/ --cov=. --cov-report=term-missing -q
```

Report: pass/fail count, coverage %, any failures with the first 20 lines of each traceback.

If `.venv` doesn't exist: `python -m venv .venv && .venv/Scripts/pip install -r requirements.txt`

Also run:
- `ruff check .` — report any lint errors
- `mypy . --ignore-missing-imports` — report any type errors

## Frontend tests

```
npm test
```

Run from the repo root. Report: pass/fail count and any failures.

Also run:
- `npm run type-check` — report TypeScript errors
- `npm run lint` — report ESLint errors

## Rust tests

```
cargo test --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings
```

Report: pass/fail and any clippy warnings treated as errors.

## Summary

After all three suites, print a single summary table:

| Suite | Tests | Pass | Fail | Notes |
|-------|-------|------|------|-------|
| Python | N | N | N | coverage % |
| Frontend | N | N | N | |
| Rust | N | N | N | |

If any suite has failures, list them clearly. Do not mark the run as passing if any test fails.

To run only slow performance benchmarks (excluded from default run):
```
pytest -m slow sidecar/tests/test_performance.py
```
