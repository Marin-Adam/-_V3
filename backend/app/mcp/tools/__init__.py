"""MCP tools package — individual tool files registered via MCPRegistry.

Backward compatibility: provides MCPToolExecutor and get_mcp_tools_json
so existing code (engine.py, workers) works without changes.
"""

from app.mcp.registry import MCPRegistry, BaseMCPTool

# Import all tool modules to trigger registration
from app.mcp.tools import (
    sales_tools,
    traffic_tools,
    inventory_tools,
    competitor_tools,
    order_tools,
    analytics_tools,
    ad_executor,
)

# ── Backward-compatible MCPToolExecutor ───────────────────────────
from app.mcp.tools.context import set_context, get_context


class MCPToolExecutor:
    """Backward-compatible executor that delegates to MCPRegistry.

    Same interface as the old MCPToolExecutor so engine.py and workers
    don't need changes.
    """

    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self._gen = data_generator
        self._streams = stream_manager
        self._store = store
        # Set context for registry tool handlers
        set_context(data_generator=data_generator, stream_manager=stream_manager, store=store)

    async def execute(self, tool_name: str, params: dict) -> dict:
        """Execute a tool via the registry."""
        # Ensure context is fresh
        set_context(data_generator=self._gen, stream_manager=self._streams, store=self._store)
        return await MCPRegistry.execute(tool_name, params)


def get_mcp_tools_json() -> list[dict]:
    """Return enabled tools in OpenAI function-calling format."""
    return MCPRegistry.get_tools_json()


__all__ = [
    "MCPRegistry", "BaseMCPTool",
    "MCPToolExecutor", "get_mcp_tools_json",
]
