"""Insights API — V3.0 营销洞察（销量为最高级枢轴）

5 modules:
  ① 品类销量排行 Top 10
  ② 年龄分段购买力 (18-24 / 25-30 / 31-40 / 40+)
  ③ 地区热力排行
  ④ 复购率分析
  ⑤ 好评/差评分布

Cross-module linkage: click product → refresh other 4 modules with product_id context.
"""

from fastapi import APIRouter, Request, Query
from typing import Optional

from app.mcp.registry import MCPRegistry
from app.mcp.tools.context import set_context

router = APIRouter()


def _setup_context(request: Request):
    """Ensure MCP tool context is set from app state."""
    gen = request.app.state.data_generator if hasattr(request.app.state, "data_generator") else None
    streams = request.app.state.stream_manager if hasattr(request.app.state, "stream_manager") else None
    store = request.app.state.data_store if hasattr(request.app.state, "data_store") else None
    set_context(data_generator=gen, stream_manager=streams, store=store)


@router.get("/overview")
async def insights_overview(
    request: Request,
    time_range: str = Query("1h", description="时间范围: 5m/15m/1h/6h/24h"),
    product_id: Optional[str] = Query(None, description="联动筛选: 商品ID"),
    category: Optional[str] = Query(None, description="品类筛选"),
):
    """Get comprehensive insights data for the Insights dashboard page."""
    _setup_context(request)

    # Use the new query_insights tool via registry
    result = await MCPRegistry.execute("query_insights", {
        "time_range": time_range,
        "category": category,
    })

    if "error" in result:
        # Fallback: build from individual tools
        result = await _build_insights_fallback(time_range, category)

    # Add product drill-down data if product_id specified
    if product_id:
        order_detail = await MCPRegistry.execute("query_order_detail", {"order_id": product_id})
        result["product_detail"] = order_detail

    return result


async def _build_insights_fallback(time_range: str, category: str = None) -> dict:
    """Build insights data from individual MCP tools if query_insights unavailable."""
    sales = await MCPRegistry.execute("query_sales_metrics", {"time_range": time_range})
    traffic = await MCPRegistry.execute("query_traffic_data", {"time_range": "1h"})
    inventory = await MCPRegistry.execute("query_inventory", {"alert_only": True})
    competitor = await MCPRegistry.execute("query_competitor_sentiment", {})

    # Category ranking from channel breakdown
    ch = sales.get("channel_breakdown", {})
    top_categories = [{"name": k, "gmv": v} for k, v in
                      sorted(ch.items(), key=lambda x: x[1], reverse=True)[:10]]

    return {
        "top_categories": top_categories,
        "age_distribution": {"18-24": 0, "25-30": 0, "31-40": 0, "40+": 0},
        "region_distribution": {},
        "repurchase_rate": 0,
        "total_users": 0,
        "repurchase_users": 0,
        "order_count": sales.get("order_count", 0),
        "gmv": sales.get("gmv", 0),
        "traffic": traffic,
        "inventory_alerts": inventory.get("inventory", []),
        "competitor_sentiment": competitor.get("sentiment_data", []),
    }


@router.get("/categories")
async def category_ranking(
    request: Request,
    time_range: str = Query("1h"),
    top_n: int = Query(10),
):
    """Module ①: Category sales ranking Top N."""
    _setup_context(request)
    result = await MCPRegistry.execute("execute_analytics_query", {
        "metric": "gmv",
        "dimension": "category",
        "time_range": time_range,
        "top_n": top_n,
    })
    return result


@router.get("/age-groups")
async def age_group_distribution(
    request: Request,
    time_range: str = Query("1h"),
):
    """Module ②: Age group purchasing power distribution."""
    _setup_context(request)
    result = await MCPRegistry.execute("execute_analytics_query", {
        "metric": "gmv",
        "dimension": "age_group",
        "time_range": time_range,
        "top_n": 10,
    })
    return result


@router.get("/regions")
async def region_distribution(
    request: Request,
    time_range: str = Query("1h"),
):
    """Module ③: Regional sales heatmap data."""
    _setup_context(request)
    result = await MCPRegistry.execute("execute_analytics_query", {
        "metric": "gmv",
        "dimension": "region",
        "time_range": time_range,
        "top_n": 20,
    })
    return result


@router.get("/repurchase")
async def repurchase_analysis(request: Request):
    """Module ④: Repurchase rate analysis."""
    _setup_context(request)

    # Query sales data and compute repurchase rate
    sales = await MCPRegistry.execute("query_sales_metrics", {"time_range": "6h"})
    insights = await MCPRegistry.execute("query_insights", {"time_range": "6h"})

    return {
        "repurchase_rate": insights.get("repurchase_rate", 0),
        "total_users": insights.get("total_users", 0),
        "repurchase_users": insights.get("repurchase_users", 0),
        "total_orders": sales.get("order_count", 0),
    }


@router.get("/sentiment")
async def sentiment_distribution(request: Request):
    """Module ⑤: Positive/negative review distribution + word cloud data."""
    _setup_context(request)

    sentiment = await MCPRegistry.execute("query_competitor_sentiment", {})

    # Aggregate sentiment distribution
    sentiment_data = sentiment.get("sentiment_data", [])
    pos = sum(1 for s in sentiment_data if s.get("sentiment") == "positive")
    neg = sum(1 for s in sentiment_data if s.get("sentiment") == "negative")
    neu = sum(1 for s in sentiment_data if s.get("sentiment") == "neutral")
    total = len(sentiment_data) or 1

    # Keywords for word cloud
    keywords = []
    for s in sentiment_data[:10]:
        keywords.append({
            "name": s.get("product_name", "?"),
            "value": abs(s.get("price_advantage_pct", 0)),
        })

    return {
        "distribution": {
            "positive": round(pos / total * 100, 1),
            "negative": round(neg / total * 100, 1),
            "neutral": round(neu / total * 100, 1),
        },
        "total_analyzed": total,
        "word_cloud": keywords,
        "detail": sentiment_data[:20],
    }
