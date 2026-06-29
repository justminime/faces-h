---
name: build-release
description: Build the Windows installer locally or trigger a GitHub Release. Use when the user wants to create a release, test the installer build, or publish a new version.
disable-model-invocation: true
---

Build the faces-h Windows installer. Arguments: `$ARGUMENTS`

## Local build (no tag)

If `$ARGUMENTS` is empty or "local", build the installer locally:

1. Build the Python sidecar:
   ```
   cd sidecar
   .venv/Scripts/pip install pyinstaller
   .venv/Scripts/pyinstaller faces-sidecar.spec
   ```
   Output: `sidecar/dist/faces-sidecar.exe`

2. Build the Tauri app:
   ```
   npm ci
   npm run tauri build
   ```
   Output: `src-tauri/target/release/bundle/nsis/faces-h-setup-*.exe`

3. Report the installer path and file size.

## GitHub Release (with version tag)

If `$ARGUMENTS` is a version like `v1.0.0`:

1. Verify `main` branch is clean (`git status` shows no uncommitted changes).
2. Verify all CI checks are passing on `main` (check via `gh run list --branch main --limit 3`).
3. Confirm with the user before pushing the tag: "Push tag v1.0.0 and trigger a GitHub Release?"
4. On confirmation:
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
5. Watch the `release.yml` workflow: `gh run watch`
6. When complete, print the release URL from `gh release view v1.0.0 --json url`.

## Notes

- Never push a tag without explicit user confirmation.
- Never build a release from a branch other than `main`.
- If PyInstaller triggers antivirus warnings during local build, note this and recommend testing on a clean VM.
