"""
EDITH Memory — SQLite Database Setup & Schema
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from config import get_settings

logger = logging.getLogger("edith.memory.db")

# Global connection reference
_db: aiosqlite.Connection | None = None


SCHEMA_SQL = """
-- ════════════════════════════════════════════
--  EDITH Database Schema
-- ════════════════════════════════════════════

-- Conversation sessions
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    title       TEXT DEFAULT 'New Chat',
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Individual messages within sessions
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content     TEXT NOT NULL,
    tool_name   TEXT,
    tool_args   TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Long-term facts & user preferences
CREATE TABLE IF NOT EXISTS facts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    category      TEXT DEFAULT 'general',
    content       TEXT NOT NULL,
    importance    REAL DEFAULT 0.5,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed TIMESTAMP
);

-- System settings (key-value)
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ── Indexes ──
CREATE INDEX IF NOT EXISTS idx_messages_session  ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created  ON messages(created_at);
CREATE INDEX IF NOT EXISTS idx_facts_category    ON facts(category);
"""


async def init_db() -> None:
    """Initialize the database: create file, apply schema."""
    global _db
    settings = get_settings()
    db_path = settings.db_path

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row

    # Enable WAL mode for better concurrent read performance
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    # Apply schema
    await _db.executescript(SCHEMA_SQL)
    await _db.commit()

    logger.info(f"Database ready at {db_path}")


async def get_db() -> aiosqlite.Connection:
    """Get the active database connection."""
    global _db
    if _db is None:
        await init_db()
    return _db


async def close_db() -> None:
    """Close the database connection."""
    global _db
    if _db is not None:
        await _db.close()
        _db = None
        logger.info("Database connection closed")
