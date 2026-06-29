---
name: impl-issue
description: Implement a faces-h GitHub Issue end-to-end as a specialist subagent. Reads the issue, identifies the agent role (Python/Rust/Frontend/Infra), implements the work, runs tests, and opens a PR. Use when the user says "implement issue #N" or "work on P1-03".
disable-model-invocation: true
---

Implement a faces-h GitHub Issue. Arguments: `$ARGUMENTS` (issue number or plan ID like P1-03)

## Preparation

1. If given a GitHub issue number: `gh issue view {N}` — read the full body including acceptance criteria and DoD.
   If given a plan ID (e.g. P1-03): read `docs/IMPLEMENTATION_PLAN.md` and find that issue.

2. Read the relevant sections of `docs/ARCHITECTURE.md` and `docs/PRD.md` for context.

3. Identify the agent role from the issue labels:
   - `python` → Python specialist: FastAPI, SQLite, FAISS, ML
   - `rust` → Rust specialist: Tauri shell, IPC, OS commands
   - `ui` → Frontend specialist: React, TypeScript, CSS tokens
   - `infra` → Infra specialist: GitHub Actions, packaging, config

4. Check all listed dependencies are merged to `main` before starting.

## Implementation

5. Create a feature branch:
   ```
   git checkout -b feat/{issue-number}-{short-slug}
   ```

6. Implement exactly what the issue specifies. Do not add unrequested features. Do not refactor surrounding code unless the issue requires it.

7. Write tests as specified in the issue. Every issue must have at least one test. Tests must be in the correct location:
   - Python: `sidecar/tests/test_{module}.py`
   - Frontend: `src/tests/{Component}.test.tsx`
   - Rust: inline `#[cfg(test)]` module in the relevant `.rs` file

8. Run `/run-tests` to verify all tests pass before opening a PR.

## Definition of Done (DoD)

Before opening the PR, verify every item:

- [ ] All acceptance criteria from the issue are met (binary: yes or no)
- [ ] Tests written and passing (`/run-tests` shows green)
- [ ] `ruff check` passes (Python files)
- [ ] `mypy` passes (Python files)
- [ ] `tsc --noEmit` passes (TypeScript files)
- [ ] `cargo clippy` passes (Rust files)
- [ ] No photo files are read/written/moved/deleted by this change
- [ ] No hardcoded ports, paths, or credentials
- [ ] New public functions/classes have a single-line docstring explaining the why (not the what)

## PR

9. Open a PR against `main`:
   ```
   gh pr create \
     --title "[Label] Short description (closes #{N})" \
     --body "$(cat <<'EOF'
   ## Summary
   <!-- one paragraph -->

   ## Closes
   Closes #{issue_number}

   ## Definition of Done
   - [ ] All acceptance criteria met
   - [ ] Tests written and passing
   - [ ] ruff / mypy / tsc / clippy all pass
   - [ ] No photo files modified
   - [ ] No hardcoded values

   ## Test plan
   <!-- what to verify manually if needed -->
   EOF
   )"
   ```

10. Print the PR URL.
