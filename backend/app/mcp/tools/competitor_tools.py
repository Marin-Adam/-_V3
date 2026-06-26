"""Competitor MCP tools."""

from app.mcp.registry import BaseMCPTool, MCPRegistry
from app.mcp.tools.context import get_context

TOOLS = []


async def _query_competitor(params: dict) -> dict:
    pid = params.get("product_id")
    _gen, _streams, _store = get_context()

    snapshots = []
    if _store:
        snapshots = _store.get_recent_competitor_snapshots(20)
    if not snapshots and _streams:
        snapshots = _streams.get_window("competitor", 20)

    if pid:
        snapshots = [s for s in snapshots if s.get("product_id") == pid]

    return {"competitor_data": snapshots[-10:], "count": len(snapshots)}


TOOLS.append(BaseMCPTool(
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
    category="competitor",
    tags=["竞品", "价格", "对比"],
    handler=_query_competitor,
))

# ── V3.0 NEW: Competitor Sentiment Tool ───────────────────────────
async def _query_competitor_sentiment(params: dict) -> dict:
    """Simple sentiment analysis on competitor data (placeholder for RoBERTa)."""
    _gen, _streams, _store = get_context()
    snapshots = []
    if _store:
        snapshots = _store.get_recent_competitor_snapshots(50)
    if not snapshots and _streams:
        snapshots = _streams.get_window("competitor", 50)

    # Simple heuristic sentiment based on price advantage
    sentiment_data = []
    for s in snapshots[-20:]:
        our_price = s.get("our_price", 0)
        comp_prices = [cp.get("price", 0) for cp in s.get("competitor_prices", [])]
        min_comp = min(comp_prices) if comp_prices else our_price
        diff_pct = (min_comp - our_price) / our_price * 100 if our_price > 0 else 0
        sentiment_data.append({
            "product_id": s.get("product_id"),
            "product_name": s.get("product_name", ""),
            "our_price": our_price,
            "min_competitor_price": min_comp,
            "price_advantage_pct": round(-diff_pct, 1),
            "sentiment": "positive" if diff_pct > 5 else ("negative" if diff_pct < -10 else "neutral"),
        })

    return {"sentiment_data": sentiment_data, "count": len(sentiment_data)}


TOOLS.append(BaseMCPTool(
    name="query_competitor_sentiment",
    description="分析竞品情感/价格竞争力。返回价格优势分析和竞争力评分。",
    parameters={
        "type": "object",
        "properties": {
            "threshold": {"type": "number", "description": "价格差异阈值(%)"},
        },
        "required": [],
    },
    category="competitor",
    tags=["竞品", "情感", "竞争力"],
    handler=_query_competitor_sentiment,
))

for t in TOOLS:
    MCPRegistry.register(t)
