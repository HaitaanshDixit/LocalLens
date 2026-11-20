"""
Small in-memory TTL cache, safe to use from FastAPI's worker threads.

cachetools' TTLCache is not thread-safe (even reads can evict expired entries),
so every operation goes through a lock. The interface is just get/set/clear/stats,
so swapping the backing store for Redis later only touches this file.

Note: each server process has its own cache. With several Gunicorn workers the
caches are separate; Redis would be the fix if that ever matters.
"""

import threading
from typing import Any, Callable, Hashable, Tuple

from cachetools import TTLCache

import config

_MISSING = object()


class TTLStore:
    def __init__(self, name: str, maxsize: int, ttl: float, enabled: bool = True):
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl
        self.enabled = enabled
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> Tuple[bool, Any]:
        """Return (found, value)."""
        with self._lock:
            value = self._cache.get(key, _MISSING) if self.enabled else _MISSING
            if value is _MISSING:
                self.misses += 1
                return False, None
            self.hits += 1
            return True, value

    def set(self, key: Hashable, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._cache[key] = value

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {
                "name": self.name,
                "enabled": self.enabled,
                "size": len(self._cache),
                "maxsize": self.maxsize,
                "ttl_seconds": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }


def get_or_compute(store: TTLStore, key: Hashable, compute: Callable[[], Any]) -> Tuple[Any, bool]:
    """Return (value, was_cache_hit). If compute() raises, nothing is cached."""
    found, value = store.get(key)
    if found:
        return value, True
    value = compute()
    store.set(key, value)
    return value, False


# Raw model predictions: deterministic for a given city + features
predict_store = TTLStore(
    "predict",
    maxsize=config.CACHE_PREDICT_MAXSIZE,
    ttl=config.CACHE_PREDICT_TTL_S,
    enabled=config.CACHE_ENABLED,
)


# Chat answers keyed on (city, normalised question). Shorter TTL: LLM output is
# not strictly repeatable, and we don't want a stale answer to live for hours.
chat_store = TTLStore(
    "chat",
    maxsize=config.CACHE_CHAT_MAXSIZE,
    ttl=config.CACHE_CHAT_TTL_S,
    enabled=config.CACHE_ENABLED,
)

# Locality lists never change while the server is running
localities_store = TTLStore(
    "localities",
    maxsize=16,
    ttl=config.CACHE_LOCALITIES_TTL_S,
    enabled=config.CACHE_ENABLED,
)


def all_stats() -> list:
    return [s.stats() for s in (predict_store, chat_store, localities_store)]