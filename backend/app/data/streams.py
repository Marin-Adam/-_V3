"""Real-time data stream manager with SSE broadcasting.

Each data channel maintains a sliding window of recent events, with both
count-based and time-based eviction.  In production with high-throughput
Kafka streams this keeps the in-memory footprint bounded.
"""

import asyncio
import json
import time
from collections import defaultdict

from app.core.events import sse_manager


class StreamManager:
    """Manages real-time data streams and broadcasts to subscribers via SSE."""

    def __init__(self, window_seconds: int = 600):
        self._windows: dict[str, list[dict]] = defaultdict(list)  # channel → recent events
        self._max_count = 10_000          # hard ceiling (count)
        self._window_seconds = window_seconds  # soft ceiling (time, default 10 min)

    async def publish(self, channel: str, data: str):
        """Publish data to channel (stored in window + broadcast via SSE)."""
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = {"raw": data}

        self._windows[channel].append(parsed)

        # Time-based eviction — drop events older than window_seconds
        self._evict(channel)

        # Count-based eviction — hard ceiling, drop oldest half when breached
        if len(self._windows[channel]) > self._max_count:
            self._windows[channel] = self._windows[channel][-self._max_count // 2:]

        await sse_manager.publish(f"stream_{channel}", json.dumps(parsed, ensure_ascii=False))

    def _evict(self, channel: str):
        """Remove events older than _window_seconds based on their 'timestamp' field."""
        cutoff = time.time() - self._window_seconds
        window = self._windows[channel]
        # Walk from the beginning; once we hit a recent enough event, the rest
        # are newer (events are append-only and roughly time-ordered).
        for i, event in enumerate(window):
            ts = _parse_event_epoch(event)
            if ts >= cutoff:
                if i > 0:
                    self._windows[channel] = window[i:]
                return
        # All events are stale
        self._windows[channel] = []

    def get_window(self, channel: str, limit: int = 50) -> list[dict]:
        return self._windows.get(channel, [])[-limit:]

    def get_all_windows(self) -> dict[str, list[dict]]:
        return {ch: events[-50:] for ch, events in self._windows.items()}


def _parse_event_epoch(event: dict) -> float:
    """Extract a Unix timestamp from an event dict. Returns 0 on failure."""
    ts = event.get("timestamp")
    if ts is None:
        return 0
    if isinstance(ts, (int, float)):
        # Could be epoch seconds or epoch milliseconds
        return ts if ts < 1e12 else ts / 1000
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts)).timestamp()
    except Exception:
        return 0
