"""Competitor price analysis utilities.

In production, this would call external scraping APIs or browser automation.
For the MVP, it analyzes the in-memory competitor data stream.
"""


def compare_prices(our_price: float, competitor_prices: list[dict]) -> dict:
    """Compare our price against competitors and return insights."""
    if not competitor_prices:
        return {"status": "no_data", "message": "暂无竞品价格数据"}

    lowest_comp = min(competitor_prices, key=lambda x: x["price"])
    highest_comp = max(competitor_prices, key=lambda x: x["price"])
    avg_comp = sum(c["price"] for c in competitor_prices) / len(competitor_prices)

    price_diff_pct = round((lowest_comp["price"] - our_price) / our_price * 100, 1)

    # Determine competitiveness
    if price_diff_pct > 10:
        competitiveness = "有价格优势"
        advice = "可维持当前定价或考虑提价"
    elif price_diff_pct < -10:
        competitiveness = "价格劣势"
        advice = f"建议降价至 ¥{lowest_comp['price'] * 0.95:.2f} 以下以恢复竞争力"
    else:
        competitiveness = "价格持平"
        advice = "持续监控竞品价格变化"

    return {
        "our_price": our_price,
        "lowest_competitor": lowest_comp,
        "highest_competitor": highest_comp,
        "avg_competitor_price": round(avg_comp, 2),
        "price_diff_pct": price_diff_pct,
        "competitiveness": competitiveness,
        "advice": advice,
        "competitor_count": len(competitor_prices),
    }


def detect_promotion(competitor_prices_history: list[dict], threshold_pct: float = 15.0) -> list[dict]:
    """Detect promotion activities from price history."""
    promotions = []
    for item in competitor_prices_history:
        # Check for significant price drops
        price_changes = item.get("price_changes", [])
        for change in price_changes:
            if abs(change["pct"]) > threshold_pct and change["pct"] < 0:
                promotions.append({
                    "competitor": item.get("competitor"),
                    "product": item.get("product_name"),
                    "old_price": change["old"],
                    "new_price": change["new"],
                    "drop_pct": abs(change["pct"]),
                    "detected_at": item.get("timestamp"),
                    "type": "大幅降价" if abs(change["pct"]) > 25 else "常规促销",
                })
    return promotions
