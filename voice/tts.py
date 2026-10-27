"""
EDITH Voice — Text-to-Speech (TTS)

Supports two engines:
  - pyttsx3: Instant, offline, robotic voice
  - edge-tts: High-quality Microsoft neural voices (needs internet)
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path

from config import get_settings

logger = logging.getLogger("edith.voice.tts")


async def speak_pyttsx3(text: str) -> bytes | None:
    """
    Generate speech using pyttsx3 (offline).
    Returns WAV audio bytes, or None if unavailable.
    """
    try:
        import pyttsx3

        # pyttsx3 is synchronous, run in thread
        def _generate():
            engine = pyttsx3.init()

            # Configure voice
            voices = engine.getProperty('voices')
            # Prefer a female voice if available
            for voice in voices:
                if 'zira' in voice.name.lower() or 'female' in voice.name.lower():
                    engine.setProperty('voice', voice.id)
                    break

            engine.setProperty('rate', 175)  # Speed
            engine.setProperty('volume', 0.9)

            # Save to temp file
            tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
            tmp_path = tmp.name
            tmp.close()

            engine.save_to_file(text, tmp_path)
            engine.runAndWait()

            # Read the generated audio
            audio_data = Path(tmp_path).read_bytes()
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass

            return audio_data

        audio = await asyncio.to_thread(_generate)
        logger.debug(f"pyttsx3 generated {len(audio)} bytes")
        return audio

    except ImportError:
        logger.warning("pyttsx3 not installed")
        return None
    except Exception as e:
        logger.error(f"pyttsx3 error: {e}")
        return None


async def speak_edge_tts(text: str, voice: str = "en-US-GuyNeural") -> bytes | None:
    """
    Generate speech using edge-tts (Microsoft neural voices).
    Returns MP3 audio bytes, or None if unavailable.

    Popular voices:
      - en-US-GuyNeural (male, natural)
      - en-US-JennyNeural (female, natural)
      - en-US-AriaNeural (female, clear)
      - en-IN-NeerjaNeural (female, Indian English)
    """
    try:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice)

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        audio = b"".join(audio_chunks)
        logger.debug(f"edge-tts generated {len(audio)} bytes ({voice})")
        return audio

    except ImportError:
        logger.warning("edge-tts not installed")
        return None
    except Exception as e:
        logger.error(f"edge-tts error: {e}")
        return None


async def speak(text: str) -> bytes | None:
    """
    Generate speech using the configured engine.
    Falls back gracefully between engines.

    Returns audio bytes (WAV or MP3) or None.
    """
    settings = get_settings()
    engine = settings.tts_engine.lower()

    if engine == "edge-tts":
        return await speak_edge_tts(text)

    elif engine == "pyttsx3":
        return await speak_pyttsx3(text)

    elif engine == "auto":
        # Try edge-tts first (higher quality), fallback to pyttsx3
        audio = await speak_edge_tts(text)
        if audio:
            return audio
        return await speak_pyttsx3(text)

    else:
        logger.warning(f"Unknown TTS engine: {engine}, using pyttsx3")
        return await speak_pyttsx3(text)


def is_available() -> bool:
    """Check if any TTS engine is available."""
    try:
        import pyttsx3
        return True
    except ImportError:
        pass

    try:
        import edge_tts
        return True
    except ImportError:
        pass

    return False
