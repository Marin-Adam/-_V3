"""MCP Tool Registry — pluggable tool management with runtime enable/disable.

V3.0 evolution: replaces hardcoded MCP_TOOLS list with a registry pattern.
Tools can be enabled/disabled at runtime without restart.

Architecture:
  - Registry: singleton dict of tool_name → BaseMCPTool instance
  - Each tool: independent Python file under mcp/tools/
  - Admin API: POST /mcp/admin/status?tool=xxx&enabled=false
"""

from dataclasses import dataclass, field
from typing import Callable, Optional

from loguru import logger


@dataclass
class BaseMCPTool:
    """Base class for all MCP tools in the registry."""

    name: str
    description: str
    parameters: dict  # JSON Schema
    enabled: bool = True
    category: str = "general"  # sales / traffic / inventory / competitor / action
    handler: Optional[Callable] = None  # async callable(params) → dict
    tags: list[str] = field(default_factory=list)


class MCPRegistry:
    """Singleton registry for all MCP tools.

    Tools register themselves at import time. Admin API can toggle
    enabled/disabled at runtime.
    """

    _tools: dict[str, BaseMCPTool] = {}
    _initialized: bool = False

    @classmethod
    def register(cls, tool: BaseMCPTool):
        """Register a tool. Later registrations with same name overwrite."""
        cls._tools[tool.name] = tool
        logger.debug(f"MCPRegistry: registered '{tool.name}' (enabled={tool.enabled})")

    @classmethod
    def unregister(cls, name: str):
        """Remove a tool from the registry."""
        cls._tools.pop(name, None)

    @classmethod
    def get(cls, name: str) -> Optional[BaseMCPTool]:
        """Get a registered tool by name."""
        return cls._tools.get(name)

    @classmethod
    def list_enabled(cls) -> list[BaseMCPTool]:
        """Return all enabled tools."""
        return [t for t in cls._tools.values() if t.enabled]

    @classmethod
    def list_all(cls) -> list[BaseMCPTool]:
        """Return all tools (including disabled)."""
        return list(cls._tools.values())

    @classmethod
    def set_enabled(cls, name: str, enabled: bool) -> bool:
        """Enable or disable a tool at runtime. Returns True if found."""
        tool = cls._tools.get(name)
        if tool:
            tool.enabled = enabled
            logger.info(f"MCPRegistry: '{name}' {'enabled' if enabled else 'disabled'}")
            return True
        return False

    @classmethod
    def get_tools_json(cls) -> list[dict]:
        """Return enabled tools in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in cls.list_enabled()
        ]

    @classmethod
    async def execute(cls, tool_name: str, params: dict) -> dict:
        """Execute a tool by name. Returns error dict if tool not found or disabled."""
        tool = cls._tools.get(tool_name)
        if not tool:
            return {"error": f"Unknown tool: {tool_name}"}
        if not tool.enabled:
            return {"error": f"Tool disabled: {tool_name}"}
        if not tool.handler:
            return {"error": f"No handler for tool: {tool_name}"}

        try:
            return await tool.handler(params)
        except Exception as e:
            logger.error(f"MCP tool '{tool_name}' failed: {e}")
            return {"error": str(e)}


# ── Singleton accessor ────────────────────────────────────────────
def get_registry() -> MCPRegistry:
    return MCPRegistry


# ── Convenience: register tools from a module ─────────────────────
def register_tools_from_module(module):
    """Scan a module for BaseMCPTool instances and register them."""
    import inspect

    for name, obj in inspect.getmembers(module):
        if isinstance(obj, BaseMCPTool):
            MCPRegistry.register(obj)
