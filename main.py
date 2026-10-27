"""
EDITH — Main Entry Point
Enhanced Digital Intelligence Technology Hub
"""

from __future__ import annotations

import io
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# ── Fix Windows console Unicode encoding ──
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings, PROJECT_ROOT

# ── Logging ──────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)-20s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("edith")


# ── Lifespan ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("=" * 50)
    logger.info("  EDITH is waking up ...")
    logger.info("=" * 50)

    # Ensure data directory exists
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize database
    from memory.database import init_db
    await init_db()
    logger.info("[OK] Database initialized")

    # Initialize tool registry
    from tools.registry import registry
    registry.discover_tools()
    logger.info(f"[OK] {len(registry)} tools registered")

    # Check FFmpeg availability (required for voice pipeline)
    from voice.stt import check_ffmpeg, is_available as stt_available
    if check_ffmpeg():
        logger.info("[OK] FFmpeg found on PATH")
    else:
        logger.warning(
            "[WARN] FFmpeg NOT found on PATH — voice transcription will fail. "
            "Install FFmpeg: https://ffmpeg.org/download.html and add to PATH."
        )

    # Check Whisper/STT availability
    if stt_available():
        logger.info(f"[OK] faster-whisper available (model: {settings.stt_model_size})")
    else:
        logger.warning("[WARN] faster-whisper not installed — STT unavailable")

    # Check TTS availability
    from voice.tts import is_available as tts_available
    if tts_available():
        logger.info(f"[OK] TTS engine available ({settings.tts_engine})")
    else:
        logger.warning("[WARN] No TTS engine available")

    # Initialize LLM client (verify connection)
    from brain.llm_client import llm_client
    model_ok = await llm_client.health_check()
    if model_ok:
        logger.info(f"[OK] Ollama connected - model: {settings.ollama_model}")
        # Probe whether the model supports tool/function calling
        tools_ok = await llm_client.probe_tool_support()
        if tools_ok:
            logger.info("[OK] Model supports tool calling")
        else:
            logger.info("[OK] Model does NOT support tool calling — command router active")
    else:
        logger.warning("[WARN] Ollama not reachable - EDITH will run without LLM")

    logger.info("=" * 50)
    logger.info(f"  EDITH is online -> http://localhost:{settings.port}")
    logger.info("=" * 50)

    yield  # ← App is running

    # Shutdown
    logger.info("EDITH is shutting down...")
    from brain.llm_client import llm_client as _llm
    await _llm.close()

    from tools.browser_control import cleanup_browser
    cleanup_browser()

    logger.info("Goodbye.")


# ── FastAPI App ──────────────────────────────────────────
app = FastAPI(
    title="EDITH",
    description="Enhanced Digital Intelligence Technology Hub",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the frontend (and any local dev tools)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Mount API Routes ─────────────────────────────────────
from api.routes import router as api_router
from api.websocket import router as ws_router

app.include_router(api_router, prefix="/api")
app.include_router(ws_router)

# ── Serve Frontend Static Files ──────────────────────────
frontend_dir = PROJECT_ROOT / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


# ── Run ──────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
