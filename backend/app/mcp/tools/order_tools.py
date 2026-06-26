"""Order MCP tools."""

from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _query_order(params: dict) -> dict:
    oid = params["order_id"]
    _gen, _streams, _store = get_context()

    orders = []
    if _store:
        orders = _store.orders
    elif _gen:
        orders = _gen.orders

    for o in orders:
        if o.get("order_id") == oid:
            return {"found": True, "order": o}
    return {"found": False, "order_id": oid}


TOOLS.append(BaseMCPTool(
    name="query_order_detail",
    description="查询指定订单的详细信息。",
    parameters={
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "订单ID"},
        },
        "required": ["order_id"],
    },
    category="order",
    tags=["订单", "详情"],
    handler=_query_order,
))

for t in TOOLS:
    MCPRegistry.register(t)
