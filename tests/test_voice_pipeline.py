"""
EDITH — Voice Pipeline Tests

Tests for the STT audio format handling and the /api/health endpoint.
Run with:  python -m pytest tests/test_voice_pipeline.py -v
"""

from __future__ import annotations

import pytest


class TestMimeTypeMapping:
    """Test that MIME types map to correct file extensions."""

    def test_webm_opus(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/webm;codecs=opus") == ".webm"

    def test_webm_plain(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/webm") == ".webm"

    def test_ogg_opus(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/ogg;codecs=opus") == ".ogg"

    def test_wav(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/wav") == ".wav"

    def test_mp4(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/mp4") == ".mp4"

    def test_none_defaults_to_webm(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension(None) == ".webm"

    def test_unknown_defaults_to_webm(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("video/mp4") == ".webm"

    def test_case_insensitive(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("Audio/WebM") == ".webm"

    def test_with_extra_spaces(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("  audio/webm ; codecs=opus  ") == ".webm"

    def test_mpeg(self):
        from voice.stt import _resolve_extension
        assert _resolve_extension("audio/mpeg") == ".mp3"


class TestFFmpegCheck:
    """Test FFmpeg availability checking."""

    def test_check_ffmpeg_returns_bool(self):
        from voice.stt import check_ffmpeg
        result = check_ffmpeg()
        assert isinstance(result, bool)


class TestSTTAvailability:
    """Test STT availability checking."""

    def test_is_available_returns_bool(self):
        from voice.stt import is_available
        result = is_available()
        assert isinstance(result, bool)


class TestTranscribeValidation:
    """Test transcription input validation."""

    @pytest.mark.asyncio
    async def test_empty_audio_returns_error(self):
        from voice.stt import transcribe
        result = await transcribe(b"", mime_type="audio/webm")
        assert result.startswith("[")

    @pytest.mark.asyncio
    async def test_tiny_audio_returns_error(self):
        from voice.stt import transcribe
        result = await transcribe(b"x" * 50, mime_type="audio/webm")
        assert result.startswith("[")

    @pytest.mark.asyncio
    async def test_transcription_is_restricted_to_english(self, monkeypatch):
        from types import SimpleNamespace
        import voice.stt as stt

        class FakeModel:
            def transcribe(self, audio_path, **options):
                assert options["language"] == "en"
                return [SimpleNamespace(text="Hello there")], SimpleNamespace(
                    language="en", duration=1.0
                )

        monkeypatch.setattr(stt, "check_ffmpeg", lambda: True)
        monkeypatch.setattr(stt, "_get_model", lambda: FakeModel())

        result = await stt.transcribe(b"x" * 100, mime_type="audio/wav")

        assert result == "Hello there"
