"""
FastAPI dependencies that hold a concurrency slot for the length of a request.
They are generators: the slot is taken before the endpoint runs and given back
in `finally`, even if the endpoint raises.
"""

from fastapi import Depends, HTTPException, Request

import config
from concurrency import KeyedSlots, Overloaded, global_slots
from db_models import User
from dependencies import get_current_user

EXEMPT_PATHS = {"/", "/health", "/ready"}


async def global_inflight(request: Request):
    """App-wide cap on requests in progress. Health checks are exempt."""
    if not config.CONCURRENCY_ENABLED or request.url.path in EXEMPT_PATHS:
        yield
        return
    if not global_slots.try_acquire():
        raise Overloaded("too many requests in progress")
    try:
        yield
    finally:
        global_slots.release()


def user_concurrency(slots: KeyedSlots):
    """At most `slots.limit` requests in progress per user."""

    async def dependency(user: User = Depends(get_current_user)):
        if not config.CONCURRENCY_ENABLED:
            yield
            return
        if not slots.try_acquire(user.id):
            raise HTTPException(
                status_code=429,
                detail="You already have requests in progress. Wait for one to finish.",
                headers={"Retry-After": "1"},
            )
        try:
            yield
        finally:
            slots.release(user.id)

    return dependency