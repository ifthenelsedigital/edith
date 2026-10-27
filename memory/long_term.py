"""
EDITH Memory — Long-Term Memory (Facts & Preferences)

Stores persistent facts, user preferences, and important context
that should survive across sessions.
"""

from __future__ import annotations

import logging
from datetime import datetime

from memory.database import get_db

logger = logging.getLogger("edith.memory.long_term")


async def store_fact(
    content: str,
    category: str = "general",
    importance: float = 0.5,
) -> int:
    """
    Store a new fact or user preference.

    Categories: 'preference', 'fact', 'entity', 'general'
    Importance: 0.0 (trivial) to 1.0 (critical)
    """
    db = await get_db()

    # Check for duplicate
    cursor = await db.execute(
        "SELECT id FROM facts WHERE content = ? AND category = ?",
        (content, category),
    )
    existing = await cursor.fetchone()
    if existing:
        # Update last_accessed instead of duplicating
        await db.execute(
            "UPDATE facts SET last_accessed = CURRENT_TIMESTAMP, importance = MAX(importance, ?) WHERE id = ?",
            (importance, existing["id"]),
        )
        await db.commit()
        return existing["id"]

    cursor = await db.execute(
        """INSERT INTO facts (content, category, importance, last_accessed)
           VALUES (?, ?, ?, CURRENT_TIMESTAMP)""",
        (content, category, importance),
    )
    await db.commit()
    logger.debug(f"Stored fact [{category}]: {content[:50]}…")
    return cursor.lastrowid


async def search_facts(query: str, limit: int = 10) -> list[dict]:
    """
    Search facts by keyword match.
    Returns facts ordered by importance, then recency.
    """
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, category, content, importance, created_at, last_accessed
           FROM facts
           WHERE content LIKE ?
           ORDER BY importance DESC, last_accessed DESC
           LIMIT ?""",
        (f"%{query}%", limit),
    )
    rows = await cursor.fetchall()

    # Update last_accessed for retrieved facts
    fact_ids = [row["id"] for row in rows]
    if fact_ids:
        placeholders = ",".join("?" * len(fact_ids))
        await db.execute(
            f"UPDATE facts SET last_accessed = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
            fact_ids,
        )
        await db.commit()

    return [dict(row) for row in rows]


async def get_all_facts(limit: int = 50) -> list[dict]:
    """Get all facts, ordered by importance."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT id, category, content, importance, created_at, last_accessed
           FROM facts
           ORDER BY importance DESC, last_accessed DESC
           LIMIT ?""",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_relevant_context(user_message: str, limit: int = 5) -> str:
    """
    Retrieve facts relevant to the current user message.
    Returns a formatted string to inject into the LLM prompt.
    """
    # Simple keyword-based relevance (can be upgraded to vector search later)
    words = user_message.lower().split()
    # Filter out short/common words
    keywords = [w for w in words if len(w) > 3]

    if not keywords:
        # Return top facts by importance
        facts = await get_all_facts(limit=limit)
    else:
        all_facts = []
        seen_ids = set()
        for keyword in keywords[:5]:  # Limit keyword searches
            results = await search_facts(keyword, limit=limit)
            for fact in results:
                if fact["id"] not in seen_ids:
                    all_facts.append(fact)
                    seen_ids.add(fact["id"])
        facts = sorted(all_facts, key=lambda f: f["importance"], reverse=True)[:limit]

    if not facts:
        return ""

    lines = ["## Things I remember about you:"]
    for fact in facts:
        lines.append(f"- [{fact['category']}] {fact['content']}")

    return "\n".join(lines)


async def delete_fact(fact_id: int) -> bool:
    """Delete a specific fact."""
    db = await get_db()
    cursor = await db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
    await db.commit()
    return cursor.rowcount > 0


async def prune_old_facts(max_age_days: int = 90, min_importance: float = 0.3) -> int:
    """
    Remove old, low-importance facts.
    Returns the number of facts pruned.
    """
    db = await get_db()
    cursor = await db.execute(
        """DELETE FROM facts
           WHERE importance < ?
           AND last_accessed < datetime('now', ? || ' days')""",
        (min_importance, f"-{max_age_days}"),
    )
    await db.commit()
    pruned = cursor.rowcount
    if pruned > 0:
        logger.info(f"Pruned {pruned} old facts")
    return pruned
