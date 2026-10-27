"""
EDITH Tools — Tool Registry

Central registry for all EDITH tools. Tools register themselves using
the @register_tool decorator and are automatically discovered on startup.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger("edith.tools.registry")


# ── Type mapping for JSON Schema ──
PYTHON_TO_JSON_SCHEMA = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class Tool:
    """A registered tool with metadata and executor."""

    name: str
    description: str
    parameters: dict  # JSON Schema for parameters
    func: Callable
    required_params: list[str] = field(default_factory=list)

    async def execute(self, **kwargs) -> Any:
        """Execute the tool function (supports both sync and async)."""
        if inspect.iscoroutinefunction(self.func):
            return await self.func(**kwargs)
        else:
            return self.func(**kwargs)

    def to_schema(self) -> dict:
        """Convert to Ollama-compatible tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": self.required_params,
                },
            },
        }


class ToolRegistry:
    """Central registry for all tools."""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        parameters: dict | None = None,
        required: list[str] | None = None,
    ) -> Callable:
        """
        Decorator to register a function as an EDITH tool.

        Usage:
            @registry.register(
                name="set_volume",
                description="Set the system volume level",
                parameters={"level": {"type": "integer", "description": "Volume 0-100"}},
                required=["level"],
            )
            def set_volume(level: int) -> str:
                ...
        """

        def decorator(func: Callable) -> Callable:
            tool = Tool(
                name=name,
                description=description,
                parameters=parameters or {},
                func=func,
                required_params=required or [],
            )
            self._tools[name] = tool
            logger.debug(f"Registered tool: {name}")
            return func

        return decorator

    def get_tool(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tool_names(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all_schemas(self) -> list[dict]:
        """Get all tool schemas for the LLM."""
        return [tool.to_schema() for tool in self._tools.values()]

    def discover_tools(self) -> None:
        """
        Import all tool modules to trigger their @register decorators.
        """
        # Import each tool module — the decorators auto-register
        try:
            import tools.windows_control
            logger.debug("Loaded: windows_control")
        except ImportError as e:
            logger.warning(f"Could not load windows_control: {e}")

        try:
            import tools.browser_control
            logger.debug("Loaded: browser_control")
        except ImportError as e:
            logger.warning(f"Could not load browser_control: {e}")

        try:
            import tools.file_search
            logger.debug("Loaded: file_search")
        except ImportError as e:
            logger.warning(f"Could not load file_search: {e}")

        try:
            import tools.local_actions
            logger.debug("Loaded: local_actions")
        except ImportError as e:
            logger.warning(f"Could not load local_actions: {e}")

        try:
            import tools.web_search
            logger.debug("Loaded: web_search")
        except ImportError as e:
            logger.warning(f"Could not load web_search: {e}")

    def __len__(self) -> int:
        return len(self._tools)


# ── Singleton Instance ──
registry = ToolRegistry()
