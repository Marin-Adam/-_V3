"""Analytics MCP tools."""

from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _execute_analytics(params: dict) -> dict:
    metric = params["metric"]
    dimension = params["dimension"]
    top_n = params.get("top_n", 5)
    tr = params.get("time_range", "1h")
    minutes = {"5m": 5, "15m": 15, "1h": 60, "6h": 360, "24h": 1440}.get(tr, 60)

    _gen, _streams, _store = get_context()
    orders = []
    if _store:
        orders = _store.get_recent_orders(minutes)
    elif _gen:
        orders = _gen.get_recent_orders(minutes)

    breakdown = {}
    for o in orders:
        key = o.get(dimension, "unknown")
        val = o.get("total_amount", 0) if metric in ("gmv", "orders") else 1
        if metric == "orders":
            breakdown[key] = breakdown.get(key, 0) + 1
        else:
            breakdown[key] = breakdown.get(key, 0) + val

    sorted_items = sorted(breakdown.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return {
        "metric": metric,
        "dimension": dimension,
        "results": [{"key": k, "value": round(v, 2)} for k, v in sorted_items],
    }


TOOLS.append(BaseMCPTool(
    name="execute_analytics_query",
    description="执行自定义聚合分析查询。用于复杂的、非标准的数据分析请求。Agent 将自然语言需求转化为聚合参数。",
    parameters={
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": ["gmv", "orders", "conversion", "traffic"], "description": "分析指标"},
            "dimension": {"type": "string", "enum": ["channel", "category", "region", "product", "age_group"], "description": "分析维度"},
            "time_range": {"type": "string", "description": "时间范围"},
            "top_n": {"type": "integer", "description": "返回Top N结果"},
        },
        "required": ["metric", "dimension"],
    },
    category="analytics",
    tags=["聚合", "分析", "查询"],
    handler=_execute_analytics,
))

# ── V3.0 NEW: Insights Query ──────────────────────────────────────
async def _query_insights(params: dict) -> dict:
    """Comprehensive insights query for the Insights dashboard page."""
    _gen, _streams, _store = get_context()
    orders = []
    if _store:
        orders = _store.get_recent_orders(60)
    elif _gen:
        orders = _gen.get_recent_orders(60)

    # Category ranking
    cat_gmv = {}
    for o in orders:
        cat = o.get("category", "unknown")
        cat_gmv[cat] = cat_gmv.get(cat, 0) + o.get("total_amount", 0)
    top_categories = sorted(cat_gmv.items(), key=lambda x: x[1], reverse=True)[:10]

    # Age group distribution
    age_gmv = {}
    for o in orders:
        age = o.get("age_group", "unknown")
        age_gmv[age] = age_gmv.get(age, 0) + o.get("total_amount", 0)

    # Region distribution
    region_gmv = {}
    for o in orders:
        region = o.get("region", "unknown")
        region_gmv[region] = region_gmv.get(region, 0) + o.get("total_amount", 0)

    # Repurchase analysis
    user_orders = {}
    for o in orders:
        uid = o.get("user_id", "?")
        user_orders[uid] = user_orders.get(uid, 0) + 1
    repurchase_users = sum(1 for cnt in user_orders.values() if cnt >= 2)
    total_users = len(user_orders) or 1
    repurchase_rate = round(repurchase_users / total_users * 100, 1)

    return {
        "top_categories": [{"name": k, "gmv": round(v, 2)} for k, v in top_categories],
        "age_distribution": {k: round(v, 2) for k, v in age_gmv.items()},
        "region_distribution": {k: round(v, 2) for k, v in region_gmv.items()},
        "repurchase_rate": repurchase_rate,
        "total_users": total_users,
        "repurchase_users": repurchase_users,
        "order_count": len(orders),
    }


TOOLS.append(BaseMCPTool(
    name="query_insights",
    description="查询营销洞察综合数据：品类排行、年龄分布、地区分布、复购率。用于Insights页面。",
    parameters={
        "type": "object",
        "properties": {
            "time_range": {"type": "string", "description": "时间范围"},
            "category": {"type": "string", "description": "筛选品类（可选）"},
        },
        "required": [],
    },
    category="analytics",
    tags=["洞察", "排行", "分布", "复购"],
    handler=_query_insights,
))

for t in TOOLS:
    MCPRegistry.register(t)
