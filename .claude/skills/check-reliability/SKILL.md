---
name: check-reliability
description: Audit any code change for violations of the faces-h reliability rules — the six rules in ARCHITECTURE.md that govern face assignment confidence. Run before merging any PR that touches the ML pipeline, clustering, or correction flow.
---

Audit the current diff (or a specified file) against the faces-h reliability rules.

## The six reliability rules (from ARCHITECTURE.md)

1. A face is never written to `assign_status = 'assigned'` unless `assign_conf >= config.threshold`.
2. `assign_conf` is always cosine similarity to the cluster centroid at assignment time, stored in the `faces` table.
3. Any face with `assign_conf < config.threshold` goes to `assign_status = 'uncertain'`.
4. The uncertain queue count is always visible in the sidebar (badge).
5. No face appears in search results until it has `assign_status = 'assigned'`.
6. Re-evaluation does not auto-promote uncertain faces — user confirmation is always required.

## Steps

1. Get the diff to review. If `$ARGUMENTS` is a PR number: `gh pr diff {N}`. Otherwise use `git diff main`.

2. For each changed Python file in `sidecar/`:
   - Search for any place where `assign_status` is set to `'assigned'` — verify rule 1 is enforced (threshold check present before the write)
   - Search for any SQL query on `faces` or `photos` without a `WHERE assign_status = 'assigned'` filter — flag as a possible rule 5 violation
   - Search for any code path in `reeval.py` that sets `assign_status = 'assigned'` without user confirmation — flag as rule 6 violation

3. For each changed TypeScript file in `src/`:
   - Verify that search result queries include the `assign_status` filter (not displaying uncertain faces)
   - Verify that the uncertain queue badge is still wired to the live count

4. Report findings as a table:

| Rule | Status | Finding |
|------|--------|---------|
| 1 — threshold gate | ✅ / ❌ | … |
| 2 — conf stored | ✅ / ❌ | … |
| 3 — uncertain routing | ✅ / ❌ | … |
| 4 — badge visible | ✅ / ❌ | … |
| 5 — search filter | ✅ / ❌ | … |
| 6 — no auto-promote | ✅ / ❌ | … |

If any rule is violated, describe the exact line and what the fix should be. Do not auto-fix — report and let the developer fix.
