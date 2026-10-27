"""
EDITH API — REST Routes

Standard REST endpoints for health checks, session management,
voice transcription, TTS, and settings.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from brain.llm_client import llm_client
from config import get_settings
from memory.short_term import (
    create_session,
    list_sessions,
    get_session,
    delete_session,
    get_messages,
)
from memory.long_term import get_all_facts, store_fact, delete_fact

logger = logging.getLogger("edith.api.routes")
router = APIRouter()


# ════════════════════════════════════════════════
#  Voice — Transcription
# ════════════════════════════════════════════════

@router.post("/voice/transcribe")
async def api_transcribe_voice(
    request: Request,
    audio: UploadFile | None = File(None),
    mime_type: str | None = Form(None),
):
    """
    Transcribe browser microphone audio using local Whisper.

    Accepts two request formats:
      1. multipart/form-data  — 'audio' file + optional 'mime_type' field
      2. application/octet-stream — raw bytes in body, MIME type in
         X-Audio-Mime-Type header

    The MIME type is critical for choosing the correct temp-file extension
    so faster-whisper / FFmpeg can decode the audio correctly.
    """
    from voice.stt import transcribe

    audio_bytes: bytes
    resolved_mime: str | None = None

    content_type = request.headers.get("content-type", "")

    if audio is not None:
        # ── Path 1: multipart/form-data ──
        audio_bytes = await audio.read()
        resolved_mime = mime_type or audio.content_type
        logger.info(
            f"Voice transcribe: received multipart upload, "
            f"{len(audio_bytes)} bytes, MIME={resolved_mime}"
        )
    elif "octet-stream" in content_type:
        # ── Path 2: raw binary body ──
        audio_bytes = await request.body()
        resolved_mime = request.headers.get("x-audio-mime-type")
        logger.info(
            f"Voice transcribe: received raw body, "
            f"{len(audio_bytes)} bytes, MIME={resolved_mime}"
        )
    else:
        # ── Path 3: try to read body anyway (legacy compat) ──
        audio_bytes = await request.body()
        resolved_mime = request.headers.get("x-audio-mime-type")
        logger.info(
            f"Voice transcribe: fallback body read, "
            f"{len(audio_bytes)} bytes, MIME={resolved_mime}"
        )

    if not audio_bytes or len(audio_bytes) < 100:
        logger.warning("Voice transcribe: empty or too-short audio")
        raise HTTPException(status_code=400, detail="No audio received or recording too short")

    text = await transcribe(audio_bytes, mime_type=resolved_mime)

    if not text or text.startswith("["):
        logger.warning(f"Voice transcribe: STT returned error — {text}")
        raise HTTPException(status_code=503, detail=text or "Speech recognition unavailable")

    logger.info(f"Voice transcribe: success — '{text[:80]}'")
    return {"text": text}


# ════════════════════════════════════════════════
#  Voice — Text-to-Speech
# ════════════════════════════════════════════════

class SpeakRequest(BaseModel):
    text: str


@router.post("/voice/speak")
async def api_speak_voice(req: SpeakRequest):
    """Generate assistant speech for browser playback."""
    from voice.tts import speak
    audio = await speak(req.text[:4000])
    if not audio:
        raise HTTPException(status_code=503, detail="Text-to-speech unavailable")
    media_type = "audio/mpeg" if get_settings().tts_engine.lower() == "edge-tts" else "audio/wav"
    return Response(content=audio, media_type=media_type)


# ════════════════════════════════════════════════
#  Health Check
# ════════════════════════════════════════════════

@router.get("/health")
async def health_check():
    """
    Check the health of all EDITH subsystems.

    Reports actionable readiness for: Ollama, Whisper, FFmpeg, TTS, Database.
    Does NOT expose .env values or secrets.
    """
    from voice.stt import is_available as stt_available, check_ffmpeg
    from voice.tts import is_available as tts_available

    settings = get_settings()
    ollama_ok = await llm_client.health_check()

    return {
        "status": "online",
        "subsystems": {
            "ollama": {
                "status": "connected" if ollama_ok else "disconnected",
                "model": settings.ollama_model,
            },
            "whisper": {
                "status": "ready" if stt_available() else "unavailable",
                "model_size": settings.stt_model_size,
            },
            "ffmpeg": {
                "status": "available" if check_ffmpeg() else "missing",
            },
            "tts": {
                "status": "available" if tts_available() else "unavailable",
                "engine": settings.tts_engine,
            },
            "database": {"status": "connected"},
        },
    }


# ════════════════════════════════════════════════
#  Sessions
# ════════════════════════════════════════════════

@router.get("/sessions")
async def api_list_sessions():
    """List all conversation sessions."""
    sessions = await list_sessions()
    return {"sessions": sessions}


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


@router.post("/sessions")
async def api_create_session(req: CreateSessionRequest):
    """Create a new conversation session."""
    session_id = await create_session(req.title)
    return {"session_id": session_id, "title": req.title}


@router.get("/sessions/{session_id}")
async def api_get_session(session_id: str):
    """Get session details."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages")
async def api_get_messages(session_id: str):
    """Get all messages in a session."""
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    messages = await get_messages(session_id)
    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}")
async def api_delete_session(session_id: str):
    """Delete a session and all its messages."""
    deleted = await delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"deleted": True}


# ════════════════════════════════════════════════
#  Facts / Memory
# ════════════════════════════════════════════════

@router.get("/facts")
async def api_list_facts():
    """List all stored facts/preferences."""
    facts = await get_all_facts()
    return {"facts": facts}


class StoreFactRequest(BaseModel):
    content: str
    category: str = "general"
    importance: float = 0.5


@router.post("/facts")
async def api_store_fact(req: StoreFactRequest):
    """Store a new fact or preference."""
    fact_id = await store_fact(req.content, req.category, req.importance)
    return {"fact_id": fact_id}


@router.delete("/facts/{fact_id}")
async def api_delete_fact(fact_id: int):
    """Delete a fact."""
    deleted = await delete_fact(fact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Fact not found")
    return {"deleted": True}


# ════════════════════════════════════════════════
#  Settings
# ════════════════════════════════════════════════

@router.get("/settings")
async def api_get_settings():
    """Get current configuration (no secrets exposed)."""
    settings = get_settings()
    return {
        "ollama_model": settings.ollama_model,
        "ollama_base_url": settings.ollama_base_url,
        "tts_engine": settings.tts_engine,
        "stt_model_size": settings.stt_model_size,
    }
