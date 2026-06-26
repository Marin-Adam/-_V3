"""Inventory MCP tools."""

from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _query_inventory(params: dict) -> dict:
    pid = params.get("product_id")
    alert_only = params.get("alert_only", False)

    _gen, _streams, _store = get_context()
    inventory = {}
    if _store:
        inventory = _store.get_current_inventory()
    elif _gen and hasattr(_gen, "inventory"):
        inventory = dict(_gen.inventory)

    result = []
    for sku, qty in inventory.items():
        if pid and sku != pid:
            continue
        item = {
            "product_id": sku,
            "quantity": qty,
            "alert": "low_stock" if qty < 20 else ("warning" if qty < 50 else None),
        }
        if alert_only and not item["alert"]:
            continue
        result.append(item)

    return {"inventory": result, "total_skus": len(result)}


TOOLS.append(BaseMCPTool(
    name="query_inventory",
    description="查询商品库存水位、预警状态。",
    parameters={
        "type": "object",
        "properties": {
            "product_id": {"type": "string", "description": "商品ID（可选）"},
            "alert_only": {"type": "boolean", "description": "仅返回库存预警的商品"},
        },
        "required": [],
    },
    category="inventory",
    tags=["库存", "补货", "预警"],
    handler=_query_inventory,
))

for t in TOOLS:
    MCPRegistry.register(t)
