from __future__ import annotations

from functools import lru_cache

import redis.asyncio as redis

from .config import get_settings


@lru_cache(maxsize=1)
def get_redis() -> redis.Redis:
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis() -> bool:
    try:
        client = get_redis()
        await client.ping()
        return True
    except Exception:
        return False
