"""Sales metrics MCP tools."""

import json
from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _query_sales(params: dict) -> dict:
    tr = params.get("time_range", "1h")
    category = params.get("category")
    minutes = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}.get(tr, 60)

    _gen, _streams, _store = get_context()
    orders = []
    if _store:
        orders = _store.get_recent_orders(minutes)
    elif _gen:
        orders = _gen.get_recent_orders(minutes)

    if category:
        orders = [o for o in orders if o.get("category") == category]

    gmv = sum(o.get("total_amount", 0) for o in orders)
    avg_order_value = gmv / len(orders) if orders else 0

    channel_breakdown = {}
    for o in orders:
        ch = o.get("channel", "unknown")
        channel_breakdown[ch] = channel_breakdown.get(ch, 0) + o.get("total_amount", 0)

    return {
        "time_range": tr,
        "gmv": round(gmv, 2),
        "order_count": len(orders),
        "avg_order_value": round(avg_order_value, 2),
        "channel_breakdown": channel_breakdown,
        "category": category,
    }


TOOLS.append(BaseMCPTool(
    name="query_sales_metrics",
    description="查询电商核心销售指标：GMV、订单量、转化率、客单价。可按时间范围和品类筛选。",
    parameters={
        "type": "object",
        "properties": {
            "time_range": {"type": "string", "enum": ["5m", "15m", "1h", "6h", "24h"], "description": "时间范围"},
            "granularity": {"type": "string", "enum": ["1m", "5m", "1h"], "description": "聚合粒度"},
            "category": {"type": "string", "description": "品类筛选（可选）"},
        },
        "required": ["time_range"],
    },
    category="sales",
    tags=["gmv", "订单", "销售"],
    handler=_query_sales,
))

# Register all
for t in TOOLS:
    MCPRegistry.register(t)
