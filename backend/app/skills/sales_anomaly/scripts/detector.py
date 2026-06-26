"""Statistical anomaly detection algorithms for sales metrics.

Provides:
  - deviation_from_mean: simple percentage deviation
  - zscore_detection: Z-Score based anomaly flagging
  - trend_break: consecutive monotonic change detection
"""

import math


def deviation_from_mean(current: float, historical_mean: float) -> float:
    """Calculate percentage deviation from historical mean."""
    if historical_mean == 0:
        return 0.0
    return (current - historical_mean) / historical_mean


def zscore_detection(current: float, values: list[float]) -> float:
    """Calculate Z-Score of current value against historical series."""
    n = len(values)
    if n < 3:
        return 0.0
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(variance) if variance > 0 else 1.0
    return (current - mean) / std


def trend_break(values: list[float], window: int = 3) -> bool:
    """Detect if the last `window` values are monotonically increasing or decreasing."""
    if len(values) < window:
        return False
    recent = values[-window:]
    increasing = all(recent[i] < recent[i+1] for i in range(window-1))
    decreasing = all(recent[i] > recent[i+1] for i in range(window-1))
    return increasing or decreasing


def classify_anomaly(deviation: float, zscore: float) -> dict:
    """Classify anomaly severity based on deviation and Z-Score."""
    abs_dev = abs(deviation)
    abs_z = abs(zscore)

    if abs_dev > 0.5 or abs_z > 3:
        severity = "P0"
        label = "严重"
    elif abs_dev > 0.3 or abs_z > 2:
        severity = "P1"
        label = "警告"
    elif abs_dev > 0.15:
        severity = "P2"
        label = "提示"
    else:
        severity = None
        label = "正常"

    return {
        "anomaly_detected": severity is not None,
        "severity": severity,
        "label": label,
        "deviation_pct": round(deviation * 100, 1),
        "zscore": round(abs_z, 2),
        "direction": "上升" if deviation > 0 else "下降",
    }
