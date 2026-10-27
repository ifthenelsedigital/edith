"""
EDITH Brain — Tool Caller

Parses tool-call requests from the LLM, executes them via the tool registry,
and feeds results back into the conversation loop.
"""

from __future__ import annotations

import json
import logging

from tools.registry import registry

logger = logging.getLogger("edith.brain.tool_caller")

# Maximum tool-call iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 5


def parse_tool_calls(response: dict) -> list[dict]:
    """
    Extract tool calls from an Ollama response.

    Returns a list of:
        {"name": "tool_name", "arguments": {arg: value, ...}}
    """
    message = response.get("message", {})
    tool_calls = message.get("tool_calls", [])

    parsed = []
    for tc in tool_calls:
        func = tc.get("function", {})
        name = func.get("name", "")
        args = func.get("arguments", {})

        # Arguments might be a string (JSON) or already a dict
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw_input": args}

        if name:
            parsed.append({"name": name, "arguments": args})

    return parsed


async def execute_tool(name: str, arguments: dict) -> str:
    """
    Execute a single tool by name with the given arguments.

    Returns the tool's output as a string.
    """
    tool = registry.get_tool(name)
    if tool is None:
        error_msg = f"Unknown tool: '{name}'. Available tools: {registry.list_tool_names()}"
        logger.warning(error_msg)
        return error_msg

    try:
        logger.info(f"⚙ Executing tool: {name}({json.dumps(arguments, default=str)})")
        result = await tool.execute(**arguments)
        result_str = str(result)
        logger.info(f"✓ Tool result: {result_str[:200]}")
        return result_str
    except TypeError as e:
        error_msg = f"Tool '{name}' argument error: {e}"
        logger.error(error_msg)
        return error_msg
    except Exception as e:
        error_msg = f"Tool '{name}' execution failed: {type(e).__name__}: {e}"
        logger.error(error_msg)
        return error_msg


async def execute_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """
    Execute a batch of tool calls and return the results.

    Returns a list of:
        {"role": "tool", "content": "result", "name": "tool_name"}
    """
    results = []
    for tc in tool_calls:
        name = tc["name"]
        args = tc["arguments"]
        result = await execute_tool(name, args)
        results.append({
            "role": "tool",
            "content": result,
            "name": name,
        })
    return results
