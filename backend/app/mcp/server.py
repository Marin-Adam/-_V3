"""MCP JSON-RPC 2.0 Server — V3.0 registry-based + admin endpoints.

Endpoints:
  POST /mcp/tools/list     — list enabled tools
  POST /mcp/tools/call     — execute a tool
  POST /mcp/admin/status   — enable/disable tool at runtime
  GET  /mcp/admin/tools    — list all tools (including disabled)
"""

import json

from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel

from app.mcp.registry import MCPRegistry
from app.mcp.tools.context import set_context

mcp_router = APIRouter()


class JSONRPCRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict = {}
    id: int = 1


@mcp_router.post("/tools/list")
async def mcp_list_tools():
    """List all enabled MCP tools (HTTP transport)."""
    tools = MCPRegistry.list_enabled()
    return {
        "jsonrpc": "2.0",
        "result": {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "category": t.category,
                    "tags": t.tags,
                    "inputSchema": t.parameters,
                }
                for t in tools
            ]
        },
        "id": 1,
    }


@mcp_router.post("/tools/call")
async def mcp_call_tool(request: Request, body: JSONRPCRequest):
    """Execute an MCP tool call (HTTP transport)."""
    tool_name = body.params.get("name") or body.params.get("tool_name")
    arguments = body.params.get("arguments") or body.params.get("params") or {}

    if not tool_name:
        raise HTTPException(status_code=400, detail="Missing tool name")

    # Ensure tool context is set from app state
    gen = request.app.state.data_generator if hasattr(request.app.state, "data_generator") else None
    streams = request.app.state.stream_manager if hasattr(request.app.state, "stream_manager") else None
    store = request.app.state.data_store if hasattr(request.app.state, "data_store") else None
    set_context(data_generator=gen, stream_manager=streams, store=store)

    # Execute via registry
    result = await MCPRegistry.execute(tool_name, arguments)

    return {
        "jsonrpc": "2.0",
        "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
        "id": body.id,
    }


# ── V3.0: Admin endpoints for runtime tool management ─────────────

@mcp_router.get("/admin/tools")
async def mcp_admin_list_tools():
    """List ALL tools (including disabled) with their status."""
    all_tools = MCPRegistry.list_all()
    return {
        "total": len(all_tools),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "enabled": t.enabled,
                "tags": t.tags,
            }
            for t in all_tools
        ],
    }


@mcp_router.post("/admin/status")
async def mcp_admin_set_status(tool: str = Query(...), enabled: bool = Query(...)):
    """Enable or disable a tool at runtime.

    Example: POST /mcp/admin/status?tool=query_sales_metrics&enabled=false
    """
    ok = MCPRegistry.set_enabled(tool, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool}")
    return {
        "tool": tool,
        "enabled": enabled,
        "message": f"Tool '{tool}' {'enabled' if enabled else 'disabled'}",
    }


@mcp_router.post("/admin/reload")
async def mcp_admin_reload(request: Request):
    """Reload tool registry (re-scan tools directory).

    In V3.0 subprocess mode, this spawns new workers.
    Currently re-imports tool modules.
    """
    import importlib
    import sys
    from app.mcp.tools import __all__ as tool_modules

    reloaded = []
    for mod_name in tool_modules:
        full_name = f"app.mcp.tools.{mod_name}"
        if full_name in sys.modules:
            try:
                importlib.reload(sys.modules[full_name])
                reloaded.append(mod_name)
            except Exception as e:
                return {"error": f"Failed to reload {mod_name}: {e}", "reloaded": reloaded}

    return {
        "message": f"Reloaded {len(reloaded)} tool modules",
        "reloaded": reloaded,
        "tool_count": len(MCPRegistry.list_all()),
    }
