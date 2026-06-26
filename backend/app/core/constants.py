"""Shared constants used across the application."""

from datetime import datetime, timezone, timedelta

# China Standard Time (UTC+8)
CST = timezone(timedelta(hours=8))


def now_cst() -> datetime:
    """Return current time in China Standard Time."""
    return datetime.now(CST)
