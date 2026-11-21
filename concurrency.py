"""
Concurrency primitives. Nothing here ever makes a request wait: if there is no
free slot the caller is rejected at once (HTTP 503 or 429), so a traffic spike
can't pile up threads or memory.

Slots       fixed number of simultaneous tasks (global cap, ML pool, chat pool)
KeyedSlots  per-key cap, used for "at most N requests in flight per user"

Counters are per server process (same limitation as the cache and rate limits).
"""

import threading
from contextlib import contextmanager

from fastapi import HTTPException

import config


class Overloaded(HTTPException):
    """No free slot right now. 503 + Retry-After."""

    def __init__(self, what: str):
        super().__init__(
            status_code=503,
            detail=f"Server is busy ({what}). Please retry in a moment.",
            headers={"Retry-After": "1"},
        )


class BudgetExceeded(HTTPException):
    """A quota (e.g. the Groq budget) is used up. 429 + Retry-After."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(
            status_code=429,
            detail=f"{message} Try again in {retry_after}s.",
            headers={"Retry-After": str(max(1, int(retry_after)))},
        )


class Slots:
    def __init__(self, name: str, limit: int):
        self.name = name
        self.limit = limit
        self._lock = threading.Lock()
        self._in_use = 0
        self.rejected = 0

    def try_acquire(self) -> bool:
        with self._lock:
            if self._in_use >= self.limit:
                self.rejected += 1
                return False
            self._in_use += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._in_use = max(0, self._in_use - 1)

    @contextmanager
    def hold(self):
        """Take a slot for the duration of the block, or raise Overloaded."""
        if not config.CONCURRENCY_ENABLED:
            yield
            return
        if not self.try_acquire():
            raise Overloaded(self.name)
        try:
            yield
        finally:
            self.release()

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "limit": self.limit,
                    "in_use": self._in_use, "rejected": self.rejected}


class KeyedSlots:
    def __init__(self, name: str, limit: int):
        self.name = name
        self.limit = limit
        self._lock = threading.Lock()
        self._counts: dict = {}
        self.rejected = 0

    def try_acquire(self, key) -> bool:
        with self._lock:
            n = self._counts.get(key, 0)
            if n >= self.limit:
                self.rejected += 1
                return False
            self._counts[key] = n + 1
            return True

    def release(self, key) -> None:
        with self._lock:
            n = self._counts.get(key, 0) - 1
            if n <= 0:
                self._counts.pop(key, None)   # don't leak one entry per user forever
            else:
                self._counts[key] = n

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "limit": self.limit,
                    "in_use": sum(self._counts.values()),
                    "users_active": len(self._counts), "rejected": self.rejected}


global_slots = Slots("all requests", config.MAX_INFLIGHT_GLOBAL)
ml_pool = Slots("ML compute", config.MAX_COMPUTE_ML)
chat_pool = Slots("chat compute", config.MAX_COMPUTE_CHAT)
user_ml = KeyedSlots("ML per user", config.MAX_INFLIGHT_PER_USER_ML)
user_chat = KeyedSlots("chat per user", config.MAX_INFLIGHT_PER_USER_CHAT)


def stats() -> list:
    return [s.stats() for s in (global_slots, ml_pool, chat_pool, user_ml, user_chat)]