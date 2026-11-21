"""
Rate limiting as FastAPI dependencies (built on the `limits` library, the same
engine slowapi uses).

Three layers:
  1. global_ip_limit      every endpoint, per IP, generous. Runs BEFORE auth, so a
                          flood of unauthenticated requests is cut off cheaply.
  2. rate_limit_ip        per IP, for /auth/login and /auth/register (brute force).
  3. rate_limit_user      per logged-in user, for /predict, /future, /compare, /chat.

Limit strings look like "60/minute" or "10/minute;100/day" (all must pass).
Counters live in memory, per server process. With several workers each has its
own counters; moving to Redis later means swapping `storage` below.

These dependencies are `async def` on purpose: they only do quick in-memory work,
and running them on the event loop means a rate limit can still answer even when
the worker threadpool is busy with slow /chat requests.
"""

import math
import time

from fastapi import Depends, HTTPException, Request, Response, status
from limits import parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

import config
from db_models import User
from dependencies import get_current_user

storage = MemoryStorage()
limiter = MovingWindowRateLimiter(storage)

# Health checks from a load balancer shouldn't eat the global budget
EXEMPT_PATHS = {"/", "/health", "/ready"}

_GLOBAL_ITEMS = parse_many(config.RATE_LIMIT_GLOBAL_IP)


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy this is the proxy's address unless uvicorn is started
    # with --proxy-headers and --forwarded-allow-ips set to the proxy.
    return request.client.host if request.client else "unknown"


def _enforce(items, scope: str, identifier: str, response: Response = None) -> None:
    """Count one request against every limit; raise 429 if any is exhausted."""
    if not config.RATE_LIMIT_ENABLED:
        return

    for item in items:
        if not limiter.hit(item, scope, identifier):
            stats = limiter.get_window_stats(item, scope, identifier)
            wait = max(1, math.ceil(stats.reset_time - time.time()))
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded ({item}). Try again in {wait}s.",
                headers={
                    "Retry-After": str(wait),
                    "X-RateLimit-Limit": str(item.amount),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(wait),
                },
            )

    if response is not None:
        # Report the tightest limit so clients can slow down before hitting 429
        tightest_stats, tightest_item = min(
            ((limiter.get_window_stats(i, scope, identifier), i) for i in items),
            key=lambda pair: pair[0].remaining,
        )
        response.headers["X-RateLimit-Limit"] = str(tightest_item.amount)
        response.headers["X-RateLimit-Remaining"] = str(tightest_stats.remaining)
        response.headers["X-RateLimit-Reset"] = str(
            max(0, math.ceil(tightest_stats.reset_time - time.time()))
        )


async def global_ip_limit(request: Request) -> None:
    if request.url.path in EXEMPT_PATHS:
        return
    _enforce(_GLOBAL_ITEMS, "global", _client_ip(request))


def rate_limit_ip(scope: str, limit_string: str):
    items = parse_many(limit_string)

    async def dependency(request: Request, response: Response) -> None:
        _enforce(items, scope, _client_ip(request), response)

    return dependency


def rate_limit_user(scope: str, limit_string: str):
    """Needs a valid token; the budget belongs to the user, not the IP."""
    items = parse_many(limit_string)

    async def dependency(response: Response, user: User = Depends(get_current_user)) -> None:
        _enforce(items, scope, user.id, response)

    return dependency