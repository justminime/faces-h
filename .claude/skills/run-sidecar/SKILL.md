---
name: run-sidecar
description: Start the Python sidecar locally for development. Run when the user wants to test the FastAPI backend, debug an endpoint, or verify the sidecar starts correctly.
---

Start the faces-h Python sidecar for local development.

1. Check that a virtual environment exists at `sidecar/.venv`. If not, create it:
   ```
   python -m venv sidecar/.venv
   sidecar/.venv/Scripts/pip install -r sidecar/requirements.txt
   ```

2. Verify `%APPDATA%\faces-h\` exists; create it if not.

3. Start the sidecar:
   ```
   sidecar/.venv/Scripts/python sidecar/main.py --port 51423 --data-dir "%APPDATA%\faces-h"
   ```

4. Poll `GET http://127.0.0.1:51423/health` until it returns `{"status": "ok"}` or 30 seconds elapse.

5. Report the URL and confirm the sidecar is healthy. If startup fails, show the last 20 lines of stderr.

The sidecar must be running before testing any API endpoints or starting the Tauri frontend in dev mode.
