"""
Redis Cache Manager
Async Redis caching with TTL, prefix invalidation, and connection pooling.
"""

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class CacheManager:
    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self.client = None
        self._local: dict = {}  # fallback in-memory cache

    async def connect(self):
        if not REDIS_AVAILABLE:
            logger.warning("⚠️  redis not installed, using in-memory fallback cache")
            return
        try:
            self.client = aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                max_connections=20,
            )
            await self.client.ping()
            logger.info("✅ Redis connected")
        except Exception as e:
            logger.warning(f"⚠️  Redis unavailable ({e}), using in-memory fallback")
            self.client = None

    async def disconnect(self):
        if self.client:
            await self.client.close()

    async def get(self, key: str) -> Optional[Any]:
        try:
            if self.client:
                val = await self.client.get(key)
                return json.loads(val) if val else None
            return self._local.get(key)
        except Exception as e:
            logger.debug(f"Cache GET error: {e}")
            return None

    async def set(self, key: str, value: Any, ttl: int = 60):
        try:
            serialized = json.dumps(value, default=str)
            if self.client:
                await self.client.setex(key, ttl, serialized)
            else:
                self._local[key] = json.loads(serialized)
        except Exception as e:
            logger.debug(f"Cache SET error: {e}")

    async def delete(self, key: str):
        try:
            if self.client:
                await self.client.delete(key)
            else:
                self._local.pop(key, None)
        except Exception as e:
            logger.debug(f"Cache DELETE error: {e}")

    async def invalidate_prefix(self, prefix: str):
        """Delete all keys starting with prefix."""
        try:
            if self.client:
                keys = await self.client.keys(f"{prefix}*")
                if keys:
                    await self.client.delete(*keys)
            else:
                to_del = [k for k in self._local if k.startswith(prefix)]
                for k in to_del:
                    del self._local[k]
        except Exception as e:
            logger.debug(f"Cache INVALIDATE error: {e}")

    async def get_info(self) -> dict:
        try:
            if self.client:
                info = await self.client.info("stats")
                return {
                    "backend": "redis",
                    "hits": info.get("keyspace_hits", 0),
                    "misses": info.get("keyspace_misses", 0),
                    "connected": True,
                }
            return {"backend": "in-memory", "keys": len(self._local), "connected": False}
        except Exception:
            return {"backend": "unknown", "connected": False}
