"""
EDITH Core — Orchestrator

The central brain that ties everything together:
User Input → Memory → Prompt → LLM → Tool Execution → Response

When the model lacks tool-calling support, the deterministic command
router intercepts explicit commands and presents an approval card before
executing state-changing actions.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import AsyncIterator

from brain.llm_client import llm_client
from brain.tool_caller import parse_tool_calls, execute_tool_calls, MAX_TOOL_ITERATIONS
from core.command_router import match_command
from core.prompt_engine import build_messages, get_tool_schemas
from memory.short_term import (
    add_message,
    get_context_messages,
    create_session,
    auto_title_session,
    get_messages,
    get_session,
)
from memory.long_term import get_relevant_context

logger = logging.getLogger("edith.core.orchestrator")


# ── qwen3 think-tag stripper ─────────────────────────────

import re as _re
_THINK_RE = _re.compile(r"<think>.*?</think>", _re.DOTALL)

def _strip_think(text: str) -> str:
    """Remove qwen3-style <think>...</think> blocks from LLM output."""
    return _THINK_RE.sub("", text).strip()


async def _resolve_session(session_id: str | None) -> tuple[str, bool]:
    """Return an existing session ID or create a replacement when it is stale."""
    if session_id is not None and await get_session(session_id):
        return session_id, False

    if session_id is not None:
        logger.warning("Session %s no longer exists; starting a new session", session_id)

    return await create_session(), True


# ── Pending approval store ────────────────────────────────
# Maps approval_id → { tool_name, arguments, description, session_id }
_pending_approvals: dict[str, dict] = {}


def create_pending_approval(
    tool_name: str,
    arguments: dict,
    description: str,
    session_id: str,
) -> str:
    """Store a pending approval and return its unique ID."""
    approval_id = str(uuid.uuid4())
    _pending_approvals[approval_id] = {
        "tool_name": tool_name,
        "arguments": arguments,
        "description": description,
        "session_id": session_id,
    }
    return approval_id


def get_pending_approval(approval_id: str) -> dict | None:
    """Retrieve and remove a pending approval by ID."""
    return _pending_approvals.pop(approval_id, None)


async def execute_approved_action(approval_id: str) -> AsyncIterator[dict]:
    """
    Execute a previously-approved action and yield streaming events.

    Yields:
        tool_start, tool_result, token, and done events.
    """
    pending = get_pending_approval(approval_id)
    if pending is None:
        yield {"type": "error", "message": "Approval expired or not found."}
        return

    tool_name = pending["tool_name"]
    arguments = pending["arguments"]
    session_id = pending["session_id"]

    # Execute the tool
    yield {"type": "tool_start", "name": tool_name, "args": arguments}

    from brain.tool_caller import execute_tool
    result = await execute_tool(tool_name, arguments)
    yield {"type": "tool_result", "name": tool_name, "result": result}

    # Save tool execution to memory
    await add_message(
        session_id,
        "tool",
        result,
        tool_name=tool_name,
        tool_args=json.dumps(arguments, default=str),
    )

    # Ask LLM to summarise the action result for a natural reply
    summary_messages = [
        {"role": "system", "content": "You are EDITH, a helpful AI assistant. The user asked you to perform an action and it has been completed. Summarise the result naturally and concisely."},
        {"role": "user", "content": f"I asked to: {pending['description']}"},
        {"role": "assistant", "content": f"Tool result: {result}"},
        {"role": "user", "content": "Please give me a brief, friendly confirmation of what happened."},
    ]

    response = await llm_client.chat(messages=summary_messages)
    final_content = _strip_think(response.get("message", {}).get("content", ""))

    if not final_content:
        final_content = f"Done! {pending['description']} — {result}"

    # Stream the summary
    chunk_size = 4
    for i in range(0, len(final_content), chunk_size):
        yield {"type": "token", "content": final_content[i : i + chunk_size]}

    await add_message(session_id, "assistant", final_content)
    yield {"type": "done", "full_response": final_content}


async def execute_denied_action(approval_id: str) -> AsyncIterator[dict]:
    """Handle a denied approval — clean up and inform the user."""
    pending = get_pending_approval(approval_id)
    if pending is None:
        yield {"type": "error", "message": "Approval expired or not found."}
        return

    msg = f"No worries — I've cancelled the action: {pending['description']}."
    chunk_size = 4
    for i in range(0, len(msg), chunk_size):
        yield {"type": "token", "content": msg[i : i + chunk_size]}

    await add_message(pending["session_id"], "assistant", msg)
    yield {"type": "done", "full_response": msg}


async def process_message(
    user_message: str,
    session_id: str | None = None,
) -> dict:
    """
    Process a user message through the full EDITH pipeline.

    Args:
        user_message: The text input from the user
        session_id: Optional session ID (creates new session if None)

    Returns:
        {
            "session_id": str,
            "response": str,
            "tool_calls": [{"name": str, "args": dict, "result": str}, ...],
        }
    """
    # 1. Session management
    session_id, is_new_session = await _resolve_session(session_id)

    # 2. Save user message
    await add_message(session_id, "user", user_message)

    # Auto-title on first message
    if is_new_session:
        await auto_title_session(session_id, user_message)

    # 3. Retrieve context
    history = await get_context_messages(session_id)
    # Remove the message we just added (it will be in build_messages)
    history = [m for m in history if not (m["role"] == "user" and m["content"] == user_message)]
    # Only keep the last occurrence if duplicated
    if history and history[-1]["role"] == "user" and history[-1]["content"] == user_message:
        history = history[:-1]

    memory_context = await get_relevant_context(user_message)

    # 4. Build prompt
    messages = build_messages(
        user_message,
        history,
        memory_context,
        compact=not llm_client.supports_tools,
    )
    tool_schemas = get_tool_schemas()

    # 5. Agent loop: LLM → Tool Call → LLM → ... → Final Response
    tool_call_log = []
    iteration = 0

    while iteration < MAX_TOOL_ITERATIONS:
        iteration += 1

        # Call LLM
        response = await llm_client.chat(
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
        )

        # Check for tool calls
        tool_calls = parse_tool_calls(response)

        if not tool_calls:
            # No tool calls → final response
            break

        # Execute tools
        tool_results = await execute_tool_calls(tool_calls)

        # Log tool calls
        for tc, tr in zip(tool_calls, tool_results):
            tool_call_log.append({
                "name": tc["name"],
                "args": tc["arguments"],
                "result": tr["content"],
            })

        # Add assistant's tool-call message to conversation
        assistant_msg = response.get("message", {})
        messages.append(assistant_msg)

        # Add tool results to conversation
        for tr in tool_results:
            messages.append({
                "role": "tool",
                "content": tr["content"],
                "tool_name": tr["name"],
            })

        logger.debug(f"Tool iteration {iteration}: {[tc['name'] for tc in tool_calls]}")

    # 6. Extract final response
    final_content = response.get("message", {}).get("content", "")

    if not final_content:
        final_content = "I completed the action but don't have additional commentary."

    # 7. Save assistant response
    await add_message(session_id, "assistant", final_content)

    # Save tool calls to message history
    for tc_log in tool_call_log:
        await add_message(
            session_id,
            "tool",
            tc_log["result"],
            tool_name=tc_log["name"],
            tool_args=json.dumps(tc_log["args"], default=str),
        )

    return {
        "session_id": session_id,
        "response": final_content,
        "tool_calls": tool_call_log,
    }


async def process_message_stream(
    user_message: str,
    session_id: str | None = None,
) -> AsyncIterator[dict]:
    """
    Process a user message and stream the response.

    Yields events:
        {"type": "session", "session_id": str}
        {"type": "tool_start", "name": str, "args": dict}
        {"type": "tool_result", "name": str, "result": str}
        {"type": "pending_approval", "approval_id": str, ...}
        {"type": "token", "content": str}
        {"type": "done", "full_response": str}
    """
    # 1. Session management
    session_id, is_new_session = await _resolve_session(session_id)

    yield {"type": "session", "session_id": session_id}

    # 2. Save user message
    await add_message(session_id, "user", user_message)

    if is_new_session:
        title = await auto_title_session(session_id, user_message)
        yield {"type": "session_title", "title": title}

    # 3. Retrieve context
    history = await get_context_messages(session_id)
    history = [m for m in history if not (m["role"] == "user" and m["content"] == user_message)]
    if history and history[-1]["role"] == "user" and history[-1]["content"] == user_message:
        history = history[:-1]

    memory_context = await get_relevant_context(user_message)

    # 4. Build prompt
    messages = build_messages(
        user_message,
        history,
        memory_context,
        compact=not llm_client.supports_tools,
    )
    tool_schemas = get_tool_schemas()

    # ── Command Router (for models without tool support) ──
    if not llm_client.supports_tools:
        cmd = match_command(user_message)
        if cmd is not None:
            if cmd.requires_approval:
                # Yield approval request and stop — the websocket handler
                # will resume execution when the user approves/denies.
                approval_id = create_pending_approval(
                    tool_name=cmd.tool_name,
                    arguments=cmd.arguments,
                    description=cmd.description,
                    session_id=session_id,
                )
                yield {
                    "type": "pending_approval",
                    "approval_id": approval_id,
                    "tool_name": cmd.tool_name,
                    "args": cmd.arguments,
                    "description": cmd.description,
                }
                return  # ← stop here; execution continues in execute_approved_action

            else:
                # Read-only command: execute immediately, no approval needed
                from brain.tool_caller import execute_tool
                yield {"type": "tool_start", "name": cmd.tool_name, "args": cmd.arguments}
                result = await execute_tool(cmd.tool_name, cmd.arguments)
                yield {"type": "tool_result", "name": cmd.tool_name, "result": result}

                await add_message(
                    session_id, "tool", result,
                    tool_name=cmd.tool_name,
                    tool_args=json.dumps(cmd.arguments, default=str),
                )

                # Ask LLM to give a natural response incorporating the result
                messages.append({"role": "assistant", "content": f"[Tool result: {result}]"})
                messages.append({"role": "user", "content": "Please summarise that result for me briefly."})

                response = await llm_client.chat(messages=messages)
                final_content = _strip_think(response.get("message", {}).get("content", ""))
                if not final_content:
                    final_content = result

                chunk_size = 4
                for i in range(0, len(final_content), chunk_size):
                    yield {"type": "token", "content": final_content[i : i + chunk_size]}

                await add_message(session_id, "assistant", final_content)
                yield {"type": "done", "full_response": final_content}
                return

        # No command match — fall through to normal LLM conversation (no tools)
        tool_schemas = []  # Don't send tool schemas to a non-tool model

        final_content = ""
        async for chunk in llm_client.chat_stream(messages):
            final_content += chunk
            yield {"type": "token", "content": chunk}

        final_content = _strip_think(final_content)
        if not final_content:
            final_content = "I couldn't generate a response. Please try again."

        await add_message(session_id, "assistant", final_content)
        yield {"type": "done", "full_response": final_content}
        return

    # ── Standard LLM + Tool-calling path ──

    # 5. First try non-streaming to handle tool calls properly
    response = await llm_client.chat(
        messages=messages,
        tools=tool_schemas if tool_schemas else None,
    )

    # Handle tool call loop
    tool_call_log = []
    iteration = 0

    while iteration < MAX_TOOL_ITERATIONS:
        tool_calls = parse_tool_calls(response)
        if not tool_calls:
            break

        iteration += 1

        for tc in tool_calls:
            yield {"type": "tool_start", "name": tc["name"], "args": tc["arguments"]}

        tool_results = await execute_tool_calls(tool_calls)

        for tc, tr in zip(tool_calls, tool_results):
            tool_call_log.append({
                "name": tc["name"],
                "args": tc["arguments"],
                "result": tr["content"],
            })
            yield {"type": "tool_result", "name": tc["name"], "result": tr["content"]}

        assistant_msg = response.get("message", {})
        messages.append(assistant_msg)
        for tr in tool_results:
            messages.append({
                "role": "tool",
                "content": tr["content"],
                "tool_name": tr["name"],
            })

        response = await llm_client.chat(
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
        )

    # 6. Stream the final response
    final_content = _strip_think(response.get("message", {}).get("content", ""))

    if final_content:
        # We already have the full response, emit it in chunks for a streaming feel
        chunk_size = 4
        for i in range(0, len(final_content), chunk_size):
            chunk = final_content[i : i + chunk_size]
            yield {"type": "token", "content": chunk}

    if not final_content:
        final_content = "Done! The action was completed."
        yield {"type": "token", "content": final_content}

    # 7. Save to memory
    await add_message(session_id, "assistant", final_content)
    for tc_log in tool_call_log:
        await add_message(
            session_id,
            "tool",
            tc_log["result"],
            tool_name=tc_log["name"],
            tool_args=json.dumps(tc_log["args"], default=str),
        )

    yield {"type": "done", "full_response": final_content}
