"""
main.py — FastAPI application entry point.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import auth, extract
from app.telegram.client import disconnect_all

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hooks."""
    # ── Startup ───────────────────────────────────────────────────────────────
    logging.getLogger(__name__).info("TeleGrabber API starting up…")
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    await disconnect_all()
    logging.getLogger(__name__).info("TeleGrabber API shut down cleanly.")


app = FastAPI(
    title="TeleGrabber API",
    description=(
        "Telegram extraction, categorization & management tool. "
        "Authenticates via MTProto as a user client and exports "
        "chat history optimized for Google NotebookLM ingest."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(extract.router)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "version": app.version}
