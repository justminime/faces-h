import argparse
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.faces import router as faces_router
from api.people import router as people_router
from api.queue import router as queue_router
from api.scan import router as scan_router
from api.search import router as search_router

app = FastAPI(title="faces-h sidecar", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    # Restricted to the Tauri WebView origin in production; wildcard is safe
    # because the sidecar only binds to 127.0.0.1 and is not network-accessible.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scan_router)   # owns GET /ws WebSocket
app.include_router(people_router)
app.include_router(queue_router)
app.include_router(faces_router)
app.include_router(search_router)


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
