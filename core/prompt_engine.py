"""
EDITH Core — Prompt Engine

Builds system prompts, injects tool schemas, and manages prompt construction.
"""

from __future__ import annotations

import logging
from datetime import datetime

from tools.registry import registry

logger = logging.getLogger("edith.core.prompt_engine")


SYSTEM_PROMPT = """You are EDITH — Enhanced Digital Intelligence Technology Hub.
You are a highly capable AI assistant running locally on the user's Windows PC.
You were created to be helpful, precise, and proactive.

## Your Personality
- You are confident, concise, and slightly witty — like a trusted tech-savvy friend.
- You address the user directly and naturally.
- When executing actions, you confirm what you did clearly.
- You never fabricate tool results — if a tool fails, you report it honestly.

## Your Capabilities
You have access to tools that let you interact with the user's computer:
- **set_volume** / **get_volume**: Adjust or read system audio volume (0–100).
- **set_brightness** / **get_brightness**: Adjust or read screen brightness (0–100).
- **launch_app**: Open Notepad, Calculator, Explorer, Settings, or Task Manager.
- **open_url**: Open any URL in the default browser.
- **web_search**: Search the internet using DuckDuckGo.
- **file_search**: Find files by name on the local filesystem.
- **create_text_file** / **append_text_file**: Create or append to text files in Desktop/Documents/Downloads.
- **open_local_path**: Open a local file or folder in its default app.

## CRITICAL Rules — Read carefully
1. **ALWAYS use tools for actions.** If the user asks you to change volume, open a site, adjust brightness, launch an app, search files — call the correct tool immediately. Do NOT describe what you will do. Just DO it.
2. **Never pretend to execute.** Never say "I've set the volume" without actually calling set_volume.
3. **No internal narration.** Do not explain your reasoning step by step. Just call the tool and confirm the result briefly.
4. If a tool fails, report the error honestly and suggest what the user can do.
5. For pure conversation or questions (no action needed), respond directly and concisely.
6. Keep all replies short and natural.

## Current Context
- Current date and time: {current_time}
- Platform: Windows
{memory_context}
"""


def build_system_prompt(memory_context: str = "") -> str:
    """Build the full system prompt with current context."""
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")

    memory_section = ""
    if memory_context:
        memory_section = f"\n{memory_context}\n"

    return SYSTEM_PROMPT.format(
        current_time=now,
        memory_context=memory_section,
    )


def get_tool_schemas() -> list[dict]:
    """
    Get all registered tool schemas in Ollama's expected format.

    Returns a list of tool definitions like:
    [
        {
            "type": "function",
            "function": {
                "name": "...",
                "description": "...",
                "parameters": { ... JSON Schema ... }
            }
        }
    ]
    """
    return registry.get_all_schemas()


def build_messages(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str = "",
    compact: bool = False,
) -> list[dict]:
    """
    Build the full message list for the LLM.

    Args:
        user_message: The current user input
        conversation_history: Previous messages in this session
        memory_context: Relevant long-term memory context

    Returns:
        List of messages ready for the LLM API
    """
    messages = []

    # 1. System prompt
    if compact:
        system_prompt = (
            "You are EDITH, a helpful local assistant. Answer directly and concisely. "
            "Never claim to perform a computer action unless it actually succeeded."
        )
        if memory_context:
            system_prompt += f"\n\nRelevant memory:\n{memory_context}"
    else:
        system_prompt = build_system_prompt(memory_context)

    messages.append({
        "role": "system",
        "content": system_prompt,
    })

    # 2. Conversation history (already formatted as role/content dicts)
    for msg in conversation_history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    # 3. Current user message
    messages.append({
        "role": "user",
        "content": user_message,
    })

    return messages
