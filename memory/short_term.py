"""
EDITH Memory — Short-Term Memory (Session Message Buffer)

Manages the sliding window of recent messages within a conversation session.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from memory.database import get_db

logger = logging.getLogger("edith.memory.short_term")

# Maximum messages to keep in context window
MAX_CONTEXT_MESSAGES = 20


async def create_session(title: str = "New Chat") -> str:
    """Create a new conversation session. Returns the session ID."""
    db = await get_db()
    session_id = str(uuid.uuid4())
    await db.execute(
        "INSERT INTO sessions (id, title) VALUES (?, ?)",
        (session_id, title),
    )
    await db.commit()
    logger.debug(f"Created session: {session_id}")
    return session_id


async def list_sessions() -> list[dict]:
    """List all sessions, newest first."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_session(session_id: str) -> dict | None:
    """Get a single session by ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, title, created_at, updated_at FROM sessions WHERE id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def delete_session(session_id: str) -> bool:
    """Delete a session and all its messages."""
    db = await get_db()
    await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await db.commit()
    return cursor.rowcount > 0


async def add_message(
    session_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_args: str | None = None,
) -> int:
    """Add a message to a session. Returns the message ID."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO messages (session_id, role, content, tool_name, tool_args)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, role, content, tool_name, tool_args),
    )
    # Update session timestamp
    await db.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )
    await db.commit()
    return cursor.lastrowid


async def get_messages(session_id: str, limit: int | None = None) -> list[dict]:
    """Get messages for a session, oldest first."""
    db = await get_db()
    if limit:
        cursor = await db.execute(
            """SELECT id, role, content, tool_name, tool_args, created_at
               FROM messages WHERE session_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in reversed(rows)]
    else:
        cursor = await db.execute(
            """SELECT id, role, content, tool_name, tool_args, created_at
               FROM messages WHERE session_id = ?
               ORDER BY created_at ASC""",
            (session_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_context_messages(session_id: str) -> list[dict]:
    """
    Get the most recent messages for LLM context.
    Returns up to MAX_CONTEXT_MESSAGES messages.
    """
    return await get_messages(session_id, limit=MAX_CONTEXT_MESSAGES)


async def auto_title_session(session_id: str, first_message: str) -> str:
    """
    Generate a title from the first user message.
    Truncates to a reasonable length.
    """
    title = first_message.strip()
    if len(title) > 60:
        title = title[:57] + "…"
    if not title:
        title = "New Chat"

    db = await get_db()
    await db.execute(
        "UPDATE sessions SET title = ? WHERE id = ?",
        (title, session_id),
    )
    await db.commit()
    return title
