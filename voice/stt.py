"""
EDITH Voice — Speech-to-Text (STT)

Uses faster-whisper for high-performance local speech recognition.
The model is loaded once on first use and cached in memory.

IMPORTANT: faster-whisper relies on FFmpeg for decoding non-WAV formats.
Ensure FFmpeg is on your system PATH. The check_ffmpeg() function reports
availability for the /api/health endpoint and startup diagnostics.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from config import get_settings

logger = logging.getLogger("edith.voice.stt")

# ── MIME type → file extension mapping ──────────────────────
# The browser MediaRecorder produces WebM/Opus in most browsers.
# faster-whisper uses the file extension to pick the decoder,
# so we MUST use the correct extension — never blindly use .wav.

MIME_TO_EXT: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/webm; codecs=opus": ".webm",
    "audio/ogg": ".ogg",
    "audio/ogg;codecs=opus": ".ogg",
    "audio/ogg; codecs=opus": ".ogg",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
}

# Default extension when MIME type is unknown — browsers almost always
# produce WebM/Opus, so .webm is the safest bet.
DEFAULT_EXT = ".webm"

# ── Lazy-loaded model ───────────────────────────────────────
_model = None


def _get_model():
    """Lazily load the Whisper model."""
    global _model
    if _model is not None:
        return _model

    try:
        from faster_whisper import WhisperModel

        settings = get_settings()
        model_size = settings.stt_model_size

        logger.info(f"Loading Whisper model: {model_size} (this may take a moment)…")

        # Try GPU first, fallback to CPU
        try:
            _model = WhisperModel(model_size, device="cuda", compute_type="float16")
            logger.info(f"✓ Whisper model loaded on GPU (CUDA)")
        except Exception:
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
            logger.info(f"✓ Whisper model loaded on CPU (int8)")

        return _model

    except ImportError:
        logger.error("faster-whisper not installed. Run: pip install faster-whisper")
        return None


def _resolve_extension(mime_type: str | None) -> str:
    """Map a MIME type string to a file extension."""
    if not mime_type:
        return DEFAULT_EXT
    # Normalise: lowercase, strip whitespace
    key = mime_type.strip().lower()
    ext = MIME_TO_EXT.get(key)
    if ext:
        return ext
    # Try without codec parameters  (e.g. "audio/webm;codecs=opus" → "audio/webm")
    base = key.split(";")[0].strip()
    ext = MIME_TO_EXT.get(base)
    if ext:
        return ext
    logger.warning(f"Unknown audio MIME type '{mime_type}', defaulting to {DEFAULT_EXT}")
    return DEFAULT_EXT


async def transcribe(audio_bytes: bytes, mime_type: str | None = None) -> str:
    """
    Transcribe English audio bytes to text.

    Args:
        audio_bytes: Raw audio data (WebM, OGG, WAV, etc.)
        mime_type:   The MIME type reported by the browser MediaRecorder.
                     Used to choose the correct temp-file extension so
                     faster-whisper / FFmpeg can decode it properly.

    Returns:
        Transcribed text string, or an error string starting with '['.
    """
    logger.info(
        f"STT: received {len(audio_bytes)} bytes, MIME={mime_type or 'unknown'}"
    )

    # ── Validate input ──────────────────────────────────────
    if not audio_bytes or len(audio_bytes) < 100:
        logger.warning("STT: audio too short, likely empty/silence")
        return "[No speech detected — recording was empty]"

    # ── Check FFmpeg ────────────────────────────────────────
    if not check_ffmpeg():
        logger.error("STT: FFmpeg not found on PATH — cannot decode audio")
        return "[FFmpeg not found. Install FFmpeg and add it to your PATH]"

    # ── Load model ──────────────────────────────────────────
    model = _get_model()
    if model is None:
        return "[STT unavailable — faster-whisper not installed]"

    # ── Write to temp file with correct extension ───────────
    ext = _resolve_extension(mime_type)
    logger.info(f"STT: writing temp file with extension '{ext}'")

    try:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        logger.info(f"STT: starting transcription ({Path(tmp_path).stat().st_size} bytes on disk)")

        segments, info = model.transcribe(
            tmp_path,
            beam_size=5,
            language="en",
            vad_filter=True,  # Filter out non-speech
        )

        text = " ".join(segment.text.strip() for segment in segments)

        logger.info(
            f"STT: transcribed ({info.language}, {info.duration:.1f}s): "
            f"{text[:120]}{'…' if len(text) > 120 else ''}"
        )

        # Clean up temp file
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass

        return text.strip()

    except Exception as e:
        logger.error(f"STT: transcription failed: {e}", exc_info=True)
        return f"[Transcription error: {e}]"


# ── Availability checks ────────────────────────────────────

def is_available() -> bool:
    """Check if faster-whisper is installed."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def check_ffmpeg() -> bool:
    """Check if FFmpeg is available on the system PATH."""
    return shutil.which("ffmpeg") is not None
