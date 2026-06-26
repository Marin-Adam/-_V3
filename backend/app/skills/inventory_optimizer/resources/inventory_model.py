"""Simplified inventory optimization model.

Calculates safety stock, reorder points, and generates replenishment recommendations.
"""

import math


def calculate_safety_stock(avg_daily_demand: float, demand_std: float,
                           lead_time_days: int = 3, service_level: float = 0.95) -> float:
    """Calculate safety stock using the standard formula.

    safety_stock = z * σ * sqrt(LT)
    where z = service level z-score, σ = demand std dev, LT = lead time
    """
    # Z-score for service level (95% -> 1.65, 99% -> 2.33)
    z_scores = {0.90: 1.28, 0.95: 1.65, 0.99: 2.33}
    z = z_scores.get(service_level, 1.65)
    safety_stock = z * demand_std * math.sqrt(lead_time_days)
    return max(safety_stock, avg_daily_demand)  # at least 1 day


def calculate_reorder_point(avg_daily_demand: float, lead_time_days: int,
                            safety_stock: float) -> float:
    """Calculate the reorder point: ROP = d * LT + SS."""
    return avg_daily_demand * lead_time_days + safety_stock


def analyze_inventory(product_name: str, current_stock: int, avg_daily_sales: float,
                      lead_time_days: int = 3, demand_std: float = None) -> dict:
    """Generate inventory optimization recommendation for a single product."""
    if demand_std is None:
        demand_std = avg_daily_sales * 0.3  # assume 30% CV

    safety_stock = calculate_safety_stock(avg_daily_sales, demand_std, lead_time_days)
    reorder_point = calculate_reorder_point(avg_daily_sales, lead_time_days, safety_stock)

    if avg_daily_sales > 0:
        days_remaining = current_stock / avg_daily_sales
    else:
        days_remaining = float('inf')

    # Classify inventory health
    if days_remaining < 3:
        status = "urgent"
        label = "🚨 紧急补货"
        reorder_qty = int((7 - days_remaining) * avg_daily_sales)  # replenish to 7 days
    elif days_remaining < 7:
        status = "reorder"
        label = "⚠️ 建议补货"
        reorder_qty = int((14 - days_remaining) * avg_daily_sales)
    elif days_remaining <= 30:
        status = "healthy"
        label = "✅ 库存健康"
        reorder_qty = 0
    else:
        status = "excess"
        label = "📦 库存过剩"
        excess_days = days_remaining - 30
        recommended_discount = min(30, int(excess_days * 0.5))  # suggest discount %
        reorder_qty = 0

    return {
        "product_name": product_name,
        "current_stock": current_stock,
        "avg_daily_sales": round(avg_daily_sales, 1),
        "days_remaining": round(days_remaining, 1) if days_remaining != float('inf') else "N/A",
        "safety_stock": round(safety_stock, 0),
        "reorder_point": round(reorder_point, 0),
        "status": status,
        "label": label,
        "recommended_action": {
            "urgent": f"立即补货 {reorder_qty} 件，预计缺货风险高",
            "reorder": f"建议 3 天内补货 {reorder_qty} 件",
            "healthy": "库存水位正常，无需操作",
            "excess": f"建议 {recommended_discount}% 折扣清仓，已超过安全库存 {excess_days:.0f} 天",
        }.get(status, ""),
        "reorder_quantity": reorder_qty,
    }
