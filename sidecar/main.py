import argparse
import os

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.people import router as people_router
from api.scan import router as scan_router

app = FastAPI(title="faces-h sidecar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Restricted to the Tauri WebView origin in production; wildcard is safe
    # because the sidecar only binds to 127.0.0.1 and is not network-accessible.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router)
app.include_router(people_router)


class _ConnectionManager:
    """Tracks active WebSocket connections for server-push events."""

    def __init__(self) -> None:
        self._active: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active = [w for w in self._active if w is not ws]

    async def broadcast(self, message: str) -> None:
        for ws in list(self._active):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)


_ws_manager = _ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await _ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket)


@app.get("/health")
async def health() -> dict:  # type: ignore[type-arg]
    return {"status": "ok"}


def main() -> None:
    parser = argparse.ArgumentParser(description="faces-h Python sidecar")
    parser.add_argument("--port", type=int, default=51423, help="Port to listen on")
    parser.add_argument("--data-dir", type=str, required=True, help="App data directory")
    args = parser.parse_args()

    os.environ["FACES_H_DATA_DIR"] = args.data_dir
    os.makedirs(args.data_dir, exist_ok=True)

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
