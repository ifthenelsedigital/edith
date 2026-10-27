"""
EDITH Configuration — Typed settings loaded from .env
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root is the directory containing this file
PROJECT_ROOT = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Application-wide settings, auto-loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Ollama ──
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "phi3:mini"

    # ── Server ──
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Database ──
    database_path: str = "./data/edith.db"

    # ── TTS ──
    tts_engine: str = "pyttsx3"  # "pyttsx3" | "edge-tts" | "auto"

    # ── STT ──
    stt_model_size: str = "base"  # "tiny" | "base" | "small" | "medium"

    # ── Logging ──
    log_level: str = "INFO"

    # ── Browser ──
    browser_headless: bool = False

    @property
    def db_path(self) -> Path:
        """Resolve the database path relative to project root."""
        p = Path(self.database_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return p


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance (cached)."""
    return Settings()
