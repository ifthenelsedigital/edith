"""
EDITH Core — Deterministic Command Router

Pattern-matches explicit user commands and maps them to registered tools,
bypassing the LLM tool-calling API for models that do not support it.

Only handles commands that can be *fully* parsed from the user's text.
Ambiguous requests fall through (return None) so the LLM can respond
conversationally.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("edith.core.command_router")


# ── Route Definition ─────────────────────────────────────


@dataclass(frozen=True)
class CommandMatch:
    """Result of a successful pattern match."""

    tool_name: str
    arguments: dict[str, Any]
    description: str          # Human-readable summary for the approval card
    requires_approval: bool   # True for state-changing actions


# ── Pattern Table ─────────────────────────────────────────
#
# Each entry is (compiled_regex, tool_name, requires_approval, arg_extractor).
# arg_extractor receives the regex Match object and returns
#   (arguments_dict, human_description).
# The list is evaluated in order; first match wins.

_ROUTES: list[tuple[re.Pattern, str, bool, Any]] = []


def _register(
    pattern: str,
    tool_name: str,
    requires_approval: bool,
    arg_extractor,
):
    """Internal helper to add a route to the table."""
    _ROUTES.append((
        re.compile(pattern, re.IGNORECASE),
        tool_name,
        requires_approval,
        arg_extractor,
    ))


# ─── Volume ───────────────────────────────────────────────

def _extract_set_volume(m: re.Match) -> tuple[dict, str]:
    level = int(m.group("level"))
    level = max(0, min(100, level))
    return {"level": level}, f"Set system volume to {level}%"

_register(
    r"(?:^|.*\b)(?:set\s+(?:the\s+)?volume\s+(?:to\s+)?|volume\s+(?:to\s+)?|change\s+(?:the\s+)?volume\s+(?:to\s+)?)(?P<level>\d{1,3})\s*%?",
    "set_volume",
    True,
    _extract_set_volume,
)

def _extract_get_volume(m: re.Match) -> tuple[dict, str]:
    return {}, "Check current system volume"

_register(
    r"(?:^|.*\b)(?:what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?volume|get\s+(?:the\s+)?volume|current\s+volume)",
    "get_volume",
    False,
    _extract_get_volume,
)

# ─── Brightness ───────────────────────────────────────────

def _extract_set_brightness(m: re.Match) -> tuple[dict, str]:
    level = int(m.group("level"))
    level = max(0, min(100, level))
    return {"level": level}, f"Set screen brightness to {level}%"

_register(
    r"(?:^|.*\b)(?:set\s+(?:the\s+)?brightness\s+(?:to\s+)?|brightness\s+(?:to\s+)?|change\s+(?:the\s+)?brightness\s+(?:to\s+)?)(?P<level>\d{1,3})\s*%?",
    "set_brightness",
    True,
    _extract_set_brightness,
)

def _extract_get_brightness(m: re.Match) -> tuple[dict, str]:
    return {}, "Check current screen brightness"

_register(
    r"(?:^|.*\b)(?:what(?:'s| is)\s+(?:the\s+)?(?:current\s+)?brightness|get\s+(?:the\s+)?brightness|current\s+brightness)",
    "get_brightness",
    False,
    _extract_get_brightness,
)

# ─── App Launch ───────────────────────────────────────────

_SUPPORTED_APPS = {"notepad", "calculator", "explorer", "settings", "task manager"}

def _extract_launch_app(m: re.Match) -> tuple[dict, str]:
    app = m.group("app").strip().lower()
    return {"app": app}, f"Launch {app.title()}"

# Build alternation from the supported app names
_app_alts = "|".join(re.escape(a) for a in _SUPPORTED_APPS)
_register(
    rf"(?:^|.*\b)(?:open|launch|start|run)\s+(?:the\s+)?(?P<app>{_app_alts})\b",
    "launch_app",
    True,
    _extract_launch_app,
)

# ─── Create Text File ────────────────────────────────────

def _extract_create_file(m: re.Match) -> tuple[dict, str]:
    filename = m.group("filename").strip()
    location = m.group("location").strip() if m.group("location") else "Documents"
    # Ensure the filename has an extension
    if "." not in filename:
        filename += ".txt"
    path = f"{location}/{filename}" if location else filename
    return {"path": path, "content": ""}, f"Create file '{filename}' in {location}"

_register(
    r"(?:^|.*\b)create\s+(?:a\s+)?(?:file\s+)?(?:named?\s+)?(?P<filename>[\w.\-]+(?:\.\w+)?)\s+(?:in|on|at|inside)\s+(?P<location>Desktop|Documents|Downloads)",
    "create_text_file",
    True,
    _extract_create_file,
)

# Also match: "create notes.txt" without a location (defaults to Documents)
_register(
    r"(?:^|.*\b)create\s+(?:a\s+)?(?:file\s+)?(?:named?\s+)?(?P<filename>[\w.\-]+\.\w+)\s*$",
    "create_text_file",
    True,
    lambda m: (
        {"path": m.group("filename").strip(), "content": ""},
        f"Create file '{m.group('filename').strip()}' in Documents",
    ),
)

# ─── Open URL ─────────────────────────────────────────────

def _extract_open_url(m: re.Match) -> tuple[dict, str]:
    url = m.group("url").strip()
    if not url.startswith(("http://", "https://")):
        display = url
    else:
        display = url
    return {"url": url}, f"Open {display} in browser"

_register(
    r"(?:^|.*\b)(?:open|go\s+to|browse|navigate\s+to|visit)\s+(?P<url>(?:https?://)?[\w][\w.\-]+\.[\w]{2,}(?:/\S*)?)",
    "open_url",
    True,
    _extract_open_url,
)

# ─── Web Search ───────────────────────────────────────────

def _extract_web_search(m: re.Match) -> tuple[dict, str]:
    query = m.group("query").strip()
    return {"query": query}, f"Search the web for '{query}'"

_register(
    r"(?:^|.*\b)(?:search\s+(?:the\s+)?(?:web\s+)?(?:for\s+)?|google\s+|look\s+up\s+)(?P<query>.{3,80}?)(?:\s+(?:on the web|online|on google))?$",
    "web_search",
    False,
    _extract_web_search,
)


# ── Public API ────────────────────────────────────────────


def match_command(user_message: str) -> CommandMatch | None:
    """
    Try to match the user message against all known command patterns.

    Returns a CommandMatch if a confident match is found, else None.
    """
    text = user_message.strip()
    if not text:
        return None

    for regex, tool_name, requires_approval, extractor in _ROUTES:
        m = regex.match(text)
        if m:
            try:
                arguments, description = extractor(m)
                logger.info(
                    f"Command router matched: {tool_name}({arguments}) "
                    f"[approval={'yes' if requires_approval else 'no'}]"
                )
                return CommandMatch(
                    tool_name=tool_name,
                    arguments=arguments,
                    description=description,
                    requires_approval=requires_approval,
                )
            except (ValueError, IndexError, AttributeError) as exc:
                logger.warning(f"Command router extractor failed for {tool_name}: {exc}")
                continue

    return None
