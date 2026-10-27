"""
EDITH Tools — File Search

Search for files by name pattern on the user's computer.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

from tools.registry import registry

logger = logging.getLogger("edith.tools.files")


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def _format_time(timestamp: float) -> str:
    """Format a timestamp to readable date string."""
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


@registry.register(
    name="search_files",
    description="Search for files by name pattern on the computer. Supports glob patterns like '*.py', 'report*', '*.pdf'. Use this when the user asks to find or search for files.",
    parameters={
        "query": {
            "type": "string",
            "description": "The file name pattern to search for (e.g., '*.py', 'report*', 'homework.docx')",
        },
        "path": {
            "type": "string",
            "description": "The directory to search in (e.g., 'C:\\Users' or 'Desktop'). Defaults to user's home directory.",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results to return. Defaults to 20.",
        },
    },
    required=["query"],
)
def search_files(
    query: str,
    path: str = "",
    max_results: int = 20,
) -> str:
    """Search for files matching a pattern."""
    # Determine search root
    if not path:
        search_root = Path.home()
    elif path.lower() in ("desktop", "~/desktop"):
        search_root = Path.home() / "Desktop"
    elif path.lower() in ("documents", "~/documents"):
        search_root = Path.home() / "Documents"
    elif path.lower() in ("downloads", "~/downloads"):
        search_root = Path.home() / "Downloads"
    else:
        search_root = Path(path)

    if not search_root.exists():
        return f"Error: Directory '{search_root}' does not exist."

    if not search_root.is_dir():
        return f"Error: '{search_root}' is not a directory."

    # Ensure the query is a glob pattern
    if "*" not in query and "?" not in query:
        query = f"*{query}*"

    # Search
    results = []
    try:
        for match in search_root.rglob(query):
            if len(results) >= max_results:
                break

            # Skip hidden and system directories
            parts = match.parts
            if any(p.startswith(".") or p.startswith("$") for p in parts):
                continue
            # Skip common large directories
            skip_dirs = {"node_modules", "__pycache__", ".git", "AppData", "venv"}
            if any(p in skip_dirs for p in parts):
                continue

            try:
                stat = match.stat()
                results.append({
                    "path": str(match),
                    "name": match.name,
                    "size": _format_size(stat.st_size),
                    "modified": _format_time(stat.st_mtime),
                    "is_dir": match.is_dir(),
                })
            except (PermissionError, OSError):
                continue

    except PermissionError:
        return f"Error: Permission denied when searching '{search_root}'."

    if not results:
        return f"No files matching '{query}' found in {search_root}"

    # Format output
    lines = [f"Found {len(results)} file(s) matching '{query}' in {search_root}:\n"]
    for r in results:
        icon = "📁" if r["is_dir"] else "📄"
        lines.append(f"  {icon} {r['name']}")
        lines.append(f"     Path: {r['path']}")
        lines.append(f"     Size: {r['size']}  |  Modified: {r['modified']}")
        lines.append("")

    if len(results) >= max_results:
        lines.append(f"  ⚠ Showing first {max_results} results. Narrow your search for more specific results.")

    return "\n".join(lines)
