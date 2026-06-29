"""FastAPI sidecar entry point. Full implementation in issue #3 (P1-01)."""
import argparse

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="faces-h sidecar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=51423)
    parser.add_argument("--data-dir", type=str, required=True)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
