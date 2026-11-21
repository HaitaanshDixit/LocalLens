"""
Small in-memory TTL cache, safe to use from FastAPI's worker threads, with
"single flight": if several requests ask for the same missing key at once, one
of them (the leader) computes it and the rest wait for that result instead of
repeating the work.

cachetools' TTLCache is not thread-safe (even reads can evict expired entries),
so every operation goes through a lock. The interface is get/set/clear/stats,
so swapping the backing store for Redis later only touches this file.

Note: each server process has its own cache. With several Gunicorn workers the
caches are separate; Redis would be the fix if that ever matters.
"""

import threading
from typing import Any, Callable, Hashable, Optional, Tuple

from cachetools import TTLCache

import config
from concurrency import Overloaded, Slots

_MISSING = object()


class _Flight:
    """One computation in progress that other requests can wait on."""
    __slots__ = ("event", "value", "exc")

    def __init__(self):
        self.event = threading.Event()
        self.value = None
        self.exc = None


class TTLStore:
    def __init__(self, name: str, maxsize: int, ttl: float, enabled: bool = True):
        self.name = name
        self.maxsize = maxsize
        self.ttl = ttl
        self.enabled = enabled
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()
        self._flights: dict = {}
        self._flight_lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.coalesced = 0

    def get(self, key: Hashable) -> Tuple[bool, Any]:
        """Return (found, value)."""
        with self._lock:
            value = self._cache.get(key, _MISSING) if self.enabled else _MISSING
            if value is _MISSING:
                self.misses += 1
                return False, None
            self.hits += 1
            return True, value

    def peek(self, key: Hashable) -> Tuple[bool, Any]:
        """Like get(), but doesn't touch the hit/miss counters."""
        with self._lock:
            value = self._cache.get(key, _MISSING) if self.enabled else _MISSING
            return (False, None) if value is _MISSING else (True, value)

    def set(self, key: Hashable, value: Any) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._cache[key] = value

    def count_coalesced(self) -> None:
        with self._lock:
            self.coalesced += 1

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
            self.coalesced = 0

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
                "coalesced": self.coalesced,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }


def get_or_compute(
    store: TTLStore,
    key: Hashable,
    compute: Callable[[], Any],
    pool: Optional[Slots] = None,
    cacheable: Optional[Callable[[Any], bool]] = None,
) -> Tuple[Any, bool]:
    """
    Return (value, served_without_computing).

      cache hit                       -> (value, True)
      identical request in flight     -> wait for it, share its result -> (value, True)
      otherwise (we are the leader)   -> compute, inside `pool` if given -> (value, False)

    If the leader fails (or the pool is full), the waiting requests get the same
    error. Errors are never cached. `cacheable(value)` can veto storing a result
    (used so failed LLM answers aren't cached); waiting requests still share it.
    """
    found, value = store.get(key)
    if found:
        return value, True

    if not store.enabled:   # caching switched off: no coalescing either
        if pool is not None:
            with pool.hold():
                return compute(), False
        return compute(), False

    with store._flight_lock:
        flight = store._flights.get(key)
        leader = flight is None
        if leader:
            flight = _Flight()
            store._flights[key] = flight

    if not leader:
        if not flight.event.wait(timeout=config.COALESCE_WAIT_TIMEOUT_S):
            raise Overloaded("an identical request is taking too long")
        store.count_coalesced()
        if flight.exc is not None:
            raise flight.exc
        return flight.value, True

    try:
        found, value = store.peek(key)   # someone may have finished just before we became leader
        if found:
            flight.value = value
            return value, True

        if pool is not None:
            with pool.hold():
                value = compute()
        else:
            value = compute()

        if cacheable is None or cacheable(value):
            store.set(key, value)
        flight.value = value
        return value, False
    except BaseException as e:
        flight.exc = e
        raise
    finally:
        with store._flight_lock:
            store._flights.pop(key, None)
        flight.event.set()


# Raw model predictions: deterministic for a given city + features
predict_store = TTLStore(
    "predict",
    maxsize=config.CACHE_PREDICT_MAXSIZE,
    ttl=config.CACHE_PREDICT_TTL_S,
    enabled=config.CACHE_ENABLED,
)

# Chat answers keyed on (city, normalised question)
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