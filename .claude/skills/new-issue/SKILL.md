---
name: new-issue
description: Create a new GitHub Issue for faces-h following project conventions. Use when the user wants to file a bug, feature request, or spike.
disable-model-invocation: true
---

Create a GitHub Issue for faces-h. Arguments: `$ARGUMENTS`

Parse `$ARGUMENTS` for:
- Issue type: `bug`, `feature`, or `spike` (default: feature)
- Brief description of the issue

## Steps

1. Read `docs/IMPLEMENTATION_PLAN.md` to understand current milestones and issue numbering conventions.

2. Determine the correct label(s) from ARCHITECTURE.md:
   - `bug`, `feature`, `spike`, `ml`, `ui`, `infra`, `db`, `perf`, `blocked`

3. Determine the correct milestone based on what the issue relates to:
   - M1 Foundation, M2 Core ML, M3 Naming & Gallery (not in plan), M4 Search, M5 Corrections, M6 Ship

4. Draft the issue body:
   - **Summary**: one paragraph describing the problem or feature
   - **Acceptance criteria**: bullet checklist of binary pass/fail checks
   - **Implementation notes**: files to create or modify, commands to run, relevant architecture references (link to ARCHITECTURE.md sections)
   - **Depends on**: list any existing issues this blocks on

5. Show the draft to the user and ask: "Create this issue?"

6. On confirmation, create it:
   ```
   gh issue create \
     --title "..." \
     --body "..." \
     --label "..." \
     --milestone "..."
   ```

7. Print the issue URL.

## Conventions

- Title format: `[Component] Short imperative description` (e.g. `[Python] Add pagination to GET /people/{id}/photos`)
- Branch name to suggest: `feat/{issue-number}-{short-slug}`
- Never create issues for work already tracked in IMPLEMENTATION_PLAN.md unless it's a bug against that work
