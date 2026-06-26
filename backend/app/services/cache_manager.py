"""CacheManager — L1 (process) + L2 (Redis) two-level hot cache.

Features:
  - L1: process-local dict with logical expiry (expire_timestamp)
  - L2: Redis shared cache across instances
  - Active invalidation broadcast via Redis Pub/Sub
  - Anti-penetration: cache null marker for missing keys
  - Anti-avalanche: logical expiry + async refresh

Usage:
    cache = CacheManager()
    await cache.set("key", data, ttl=30)
    value = await cache.get("key")
    await cache.invalidate("key")
"""

import asyncio
import json
import time
from typing import Optional

from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# ── L1 local cache entry ──────────────────────────────────────────
# (value, expire_timestamp) — expire_timestamp is monotonic time
_L1_CACHE: dict[str, tuple[any, float]] = {}
_L1_NULL_MARKER = "__CACHE_NULL__"

# ── Redis client (lazy-init) ──────────────────────────────────────
_redis = None
_pubsub = None
_invalidation_listener_started = False


def _get_redis():
    """Lazy-init Redis client with error handling."""
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
        logger.info(f"CacheManager: Redis connected ({settings.REDIS_URL})")
    except Exception as e:
        logger.warning(f"CacheManager: Redis unavailable ({e}), L1-only mode")
        _redis = False  # sentinel: tried but failed
    return _redis


async def _start_invalidation_listener():
    """Subscribe to Redis Pub/Sub for cache invalidation events."""
    global _pubsub, _invalidation_listener_started
    if _invalidation_listener_started:
        return
    _invalidation_listener_started = True

    r = _get_redis()
    if not r:
        return
    try:
        _pubsub = r.pubsub()
        await _pubsub.subscribe("cache:invalidate")
        logger.info("CacheManager: subscribed to cache:invalidate channel")

        async def _listen():
            try:
                async for message in _pubsub.listen():
                    if message["type"] == "message":
                        key = message["data"]
                        _L1_CACHE.pop(key, None)
                        logger.debug(f"CacheManager: L1 invalidated '{key}' via Pub/Sub")
            except Exception as e:
                logger.warning(f"CacheManager: Pub/Sub listener error: {e}")

        asyncio.create_task(_listen())
    except Exception as e:
        logger.warning(f"CacheManager: Pub/Sub subscription failed: {e}")


class CacheManager:
    """Two-level cache with active invalidation.

    Read path:  L1 → L2 (Redis) → data source (miss)
    Write path: L1 + L2 + publish invalidation
    """

    CHANNEL = "cache:invalidate"

    def __init__(self):
        self._local = _L1_CACHE  # shared module-level dict
        _ = _get_redis()  # trigger lazy connection

    # ── Public API ─────────────────────────────────────────────────

    async def get(self, key: str) -> Optional[any]:
        """Get value from cache. Returns None on miss."""
        # L1: process-local
        if key in self._local:
            value, expire_at = self._local[key]
            now = time.monotonic()
            if expire_at > now:
                if value == _L1_NULL_MARKER:
                    return None
                return value
            # Logical expiry — return stale but trigger async refresh
            logger.debug(f"CacheManager: L1 logical expiry for '{key}', returning stale + refresh")
            asyncio.create_task(self._refresh_l1(key))
            if value != _L1_NULL_MARKER:
                return value

        # L2: Redis
        r = _get_redis()
        if r:
            try:
                raw = await r.get(f"cache:{key}")
                if raw is not None:
                    if raw == _L1_NULL_MARKER:
                        # Cache null marker in L1 briefly to avoid repeated L2 queries
                        self._local[key] = (_L1_NULL_MARKER, time.monotonic() + 10)
                        return None
                    data = json.loads(raw)
                    # Promote to L1 with 30s local TTL
                    self._local[key] = (data, time.monotonic() + 30)
                    return data
            except Exception as e:
                logger.warning(f"CacheManager: Redis GET failed for '{key}': {e}")

        return None

    async def set(self, key: str, value: any, ttl: int = 60):
        """Set cache value with TTL in seconds."""
        # L1: local with shorter TTL (min(ttl, 120))
        local_ttl = min(ttl, 120)
        self._local[key] = (value, time.monotonic() + local_ttl)

        # L2: Redis
        r = _get_redis()
        if r:
            try:
                raw = json.dumps(value, ensure_ascii=False, default=str)
                await r.setex(f"cache:{key}", max(ttl, 30), raw)
            except Exception as e:
                logger.warning(f"CacheManager: Redis SET failed for '{key}': {e}")

    async def set_null(self, key: str, ttl: int = 30):
        """Cache a null marker to prevent cache penetration for missing keys."""
        self._local[key] = (_L1_NULL_MARKER, time.monotonic() + min(ttl, 60))
        r = _get_redis()
        if r:
            try:
                await r.setex(f"cache:{key}", ttl, _L1_NULL_MARKER)
            except Exception:
                pass

    async def invalidate(self, key: str):
        """Invalidate cache key across all instances."""
        # Clear local
        self._local.pop(key, None)

        # Broadcast via Redis Pub/Sub
        r = _get_redis()
        if r:
            try:
                await r.publish(self.CHANNEL, key)
                await r.delete(f"cache:{key}")
                logger.debug(f"CacheManager: invalidated '{key}' (broadcast)")
            except Exception as e:
                logger.warning(f"CacheManager: invalidate broadcast failed for '{key}': {e}")

    async def delete(self, key: str):
        """Delete key (alias for invalidate)."""
        await self.invalidate(key)

    # ── Internal ───────────────────────────────────────────────────

    async def _refresh_l1(self, key: str):
        """Async refresh L1 from L2 after logical expiry."""
        r = _get_redis()
        if not r:
            return
        try:
            raw = await r.get(f"cache:{key}")
            if raw and raw != _L1_NULL_MARKER:
                data = json.loads(raw)
                self._local[key] = (data, time.monotonic() + 30)
        except Exception:
            pass

    # ── Helpers ────────────────────────────────────────────────────

    async def get_or_set(self, key: str, factory, ttl: int = 60):
        """Get from cache, or compute via factory and cache."""
        cached = await self.get(key)
        if cached is not None:
            return cached

        value = await factory()
        if value is not None:
            await self.set(key, value, ttl)
        else:
            await self.set_null(key, ttl=15)
        return value

    async def flush_pattern(self, pattern: str):
        """Delete all keys matching pattern from Redis."""
        r = _get_redis()
        if not r:
            return
        try:
            keys = await r.keys(f"cache:{pattern}")
            if keys:
                await r.delete(*keys)
                # Also broadcast for each key
                for k in keys:
                    await r.publish(self.CHANNEL, k.replace("cache:", "", 1))
        except Exception as e:
            logger.warning(f"CacheManager: flush_pattern failed: {e}")


# ── Singleton ─────────────────────────────────────────────────────
_cache_instance: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """Get or create the singleton CacheManager instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager()
    return _cache_instance


async def start_cache():
    """Start cache invalidation listener (call during app startup)."""
    await _start_invalidation_listener()
    logger.info("CacheManager: invalidation listener started")
