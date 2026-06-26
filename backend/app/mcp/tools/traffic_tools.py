"""Traffic MCP tools."""

from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _query_traffic(params: dict) -> dict:
    pid = params.get("product_id")
    _gen, _streams, _store = get_context()

    traffic = {}
    if _store:
        traffic = _store.get_current_traffic()
    elif _gen:
        traffic = _gen.get_current_traffic()

    if pid and pid in traffic:
        return {"product_id": pid, "traffic": traffic[pid]}

    total_uv = sum(t.get("uv", 0) for t in traffic.values())
    total_pv = sum(t.get("pv", 0) for t in traffic.values())
    total_cart = sum(t.get("add_cart", 0) for t in traffic.values())

    return {
        "total_uv": total_uv,
        "total_pv": total_pv,
        "total_add_cart": total_cart,
        "by_product": traffic,
    }


TOOLS.append(BaseMCPTool(
    name="query_traffic_data",
    description="查询用户行为数据：UV、PV、加购数。可按商品或时间范围筛选。",
    parameters={
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "商品ID（可选，不传则返回全部）"},
            "time_range": {"type": "string", "enum": ["5m", "15m", "1h", "6h"]},
        },
        "required": ["time_range"],
    },
    category="traffic",
    tags=["UV", "PV", "流量", "加购"],
    handler=_query_traffic,
))

for t in TOOLS:
    MCPRegistry.register(t)
