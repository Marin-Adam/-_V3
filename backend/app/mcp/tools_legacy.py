"""MCP tool definitions for the e-commerce dashboard.

Six standardized tools for the Agent to query data and trigger actions.
"""

import json
from dataclasses import dataclass


@dataclass
class MCPTool:
    name: str
    description: str
    parameters: dict  # JSON Schema


MCP_TOOLS = [
    MCPTool(
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
    ),
    MCPTool(
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
    ),
    MCPTool(
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
    ),
    MCPTool(
        name="query_competitor_prices",
        description="查询竞品价格对比数据。输入商品名称或ID，返回我方价格与竞品价格的对比。",
        parameters={
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "商品名称关键词"},
                "product_id": {"type": "string", "description": "商品ID"},
            },
            "required": [],
        },
    ),
    MCPTool(
        name="query_order_detail",
        description="查询指定订单的详细信息。",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单ID"},
            },
            "required": ["order_id"],
        },
    ),
    MCPTool(
        name="execute_analytics_query",
        description="执行自定义聚合分析查询。用于复杂的、非标准的数据分析请求。Agent 将自然语言需求转化为聚合参数。",
        parameters={
            "type": "object",
            "properties": {
                "metric": {"type": "string", "enum": ["gmv", "orders", "conversion", "traffic"], "description": "分析指标"},
                "dimension": {"type": "string", "enum": ["channel", "category", "region", "product"], "description": "分析维度"},
                "time_range": {"type": "string", "description": "时间范围"},
                "top_n": {"type": "integer", "description": "返回Top N结果"},
            },
            "required": ["metric", "dimension"],
        },
    ),
]


def get_mcp_tools_json() -> list[dict]:
    """Return tools in OpenAI function-calling format."""
    return [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}} for t in MCP_TOOLS]


class MCPToolExecutor:
    """Executes MCP tool calls against the data layer.

    Data source priority: EcomDataStore (shared) → DataGenerator (fallback).
    Both Kafka consumers and DataGenerator write to EcomDataStore,
    so MCP tools work identically regardless of which data source is active.
    """

    def __init__(self, data_generator=None, stream_manager=None, store=None):
        self._gen = data_generator    # DataGenerator (fallback / backward compat)
        self._streams = stream_manager
        self._store = store           # EcomDataStore (primary, shared with Kafka consumers)
        self._executors = {
            "query_sales_metrics": self._query_sales,
            "query_traffic_data": self._query_traffic,
            "query_inventory": self._query_inventory,
            "query_competitor_prices": self._query_competitor,
            "query_order_detail": self._query_order,
            "execute_analytics_query": self._execute_analytics,
        }

    # ── Data access helpers ──────────────────────────────────────

    def _get_orders(self, minutes: int) -> list[dict]:
        """Get recent orders from store (preferred) or generator (fallback)."""
        if self._store:
            return self._store.get_recent_orders(minutes)
        if self._gen:
            return self._gen.get_recent_orders(minutes)
        return []

    def _get_traffic(self) -> dict:
        if self._store:
            return self._store.get_current_traffic()
        if self._gen:
            return self._gen.get_current_traffic()
        return {}

    def _get_inventory(self) -> dict:
        if self._store:
            return self._store.get_current_inventory()
        if self._gen and hasattr(self._gen, "inventory"):
            return dict(self._gen.inventory)
        return {}

    def _get_all_orders(self) -> list[dict]:
        if self._store:
            return self._store.orders
        if self._gen:
            return self._gen.orders
        return []

    def _get_competitor_snapshots(self, limit: int = 20) -> list[dict]:
        # Prefer store, fall back to stream window
        if self._store:
            return self._store.get_recent_competitor_snapshots(limit)
        if self._streams:
            return self._streams.get_window("competitor", limit)
        return []

    async def execute(self, tool_name: str, params: dict) -> dict:
        executor = self._executors.get(tool_name)
        if not executor:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return await executor(params)
        except Exception as e:
            return {"error": str(e)}

    async def _query_sales(self, params: dict) -> dict:
        tr = params.get("time_range", "1h")
        category = params.get("category")
        minutes = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}[tr]
        orders = self._get_orders(minutes)
        if category:
            orders = [o for o in orders if o["category"] == category]
        gmv = sum(o["total_amount"] for o in orders)
        avg_order_value = gmv / len(orders) if orders else 0
        channel_breakdown = {}
        for o in orders:
            ch = o["channel"]
            channel_breakdown[ch] = channel_breakdown.get(ch, 0) + o["total_amount"]
        return {"time_range": tr, "gmv": round(gmv, 2), "order_count": len(orders),
                "avg_order_value": round(avg_order_value, 2), "channel_breakdown": channel_breakdown, "category": category}

    async def _query_traffic(self, params: dict) -> dict:
        pid = params.get("product_id")
        traffic = self._get_traffic()
        if pid and pid in traffic:
            return {"product_id": pid, "traffic": traffic[pid]}
        total_uv = sum(t["uv"] for t in traffic.values())
        total_pv = sum(t["pv"] for t in traffic.values())
        total_cart = sum(t["add_cart"] for t in traffic.values())
        return {"total_uv": total_uv, "total_pv": total_pv, "total_add_cart": total_cart, "by_product": traffic}

    async def _query_inventory(self, params: dict) -> dict:
        pid = params.get("product_id")
        alert_only = params.get("alert_only", False)
        inventory = self._get_inventory()
        result = []
        for sku, qty in inventory.items():
            if pid and sku != pid:
                continue
            item = {"product_id": sku, "quantity": qty,
                    "alert": "low_stock" if qty < 20 else ("warning" if qty < 50 else None)}
            if alert_only and not item["alert"]:
                continue
            result.append(item)
        return {"inventory": result, "total_skus": len(result)}

    async def _query_competitor(self, params: dict) -> dict:
        # Prefer store snapshots, fall back to stream window
        snapshots = self._get_competitor_snapshots(20)
        if not snapshots and self._streams:
            snapshots = self._streams.get_window("competitor", 20)
        pid = params.get("product_id")
        if pid:
            snapshots = [s for s in snapshots if s.get("product_id") == pid]
        return {"competitor_data": snapshots[-10:], "count": len(snapshots)}

    async def _query_order(self, params: dict) -> dict:
        oid = params["order_id"]
        orders = self._get_all_orders()
        for o in orders:
            if o.get("order_id") == oid:
                return {"found": True, "order": o}
        return {"found": False, "order_id": oid}

    async def _execute_analytics(self, params: dict) -> dict:
        metric = params["metric"]
        dimension = params["dimension"]
        top_n = params.get("top_n", 5)
        tr = params.get("time_range", "1h")
        minutes = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}.get(tr, 60)
        orders = self._get_orders(minutes)
        breakdown = {}
        for o in orders:
            key = o.get(dimension, "unknown")
            val = o["total_amount"] if metric in ("gmv", "orders") else 1
            if metric == "orders":
                breakdown[key] = breakdown.get(key, 0) + 1
            else:
                breakdown[key] = breakdown.get(key, 0) + val
        sorted_items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:top_n]
        return {"metric": metric, "dimension": dimension,
                "results": [{"key": k, "value": round(v, 2)} for k, v in sorted_items]}
