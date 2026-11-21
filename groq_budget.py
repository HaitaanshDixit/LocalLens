"""
Budget for real Groq calls. Cache hits and coalesced requests never reach this,
so it only counts calls that actually spend your Groq quota.

  per minute  in memory (moving window)
  per day     stored in the database, so a restart doesn't hand you a fresh quota
              (the UTC calendar day; Groq's own reset time may differ, so keep the
              cap a bit below your real limit)

Check your real limits in the Groq console (they differ per model) and set
GROQ_MAX_PER_MINUTE / GROQ_MAX_PER_DAY just under them.
"""

import math
import time
from datetime import datetime, timedelta, timezone

from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from sqlalchemy import text

import config
from concurrency import BudgetExceeded
from database import engine

_minute_item = parse(f"{config.GROQ_MAX_PER_MINUTE}/minute")
_limiter = MovingWindowRateLimiter(MemoryStorage())


def ensure_table() -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS groq_usage "
            "(day TEXT PRIMARY KEY, calls INTEGER NOT NULL)"
        ))


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seconds_to_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - now).total_seconds())


def take() -> None:
    """Reserve one Groq call, or raise BudgetExceeded (HTTP 429)."""
    if not config.GROQ_BUDGET_ENABLED:
        return

    # Minute first: if it fails we haven't spent any of the daily budget
    if not _limiter.hit(_minute_item, "groq"):
        stats = _limiter.get_window_stats(_minute_item, "groq")
        wait = max(1, math.ceil(stats.reset_time - time.time()))
        raise BudgetExceeded("The AI assistant is getting too many questions right now.", wait)

    day = _today()
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO groq_usage (day, calls) VALUES (:d, 0) ON CONFLICT(day) DO NOTHING"
        ), {"d": day})
        res = conn.execute(text(
            "UPDATE groq_usage SET calls = calls + 1 WHERE day = :d AND calls < :cap"
        ), {"d": day, "cap": config.GROQ_MAX_PER_DAY})
        allowed = res.rowcount == 1
    if not allowed:
        raise BudgetExceeded("Today's AI chat quota is used up.", _seconds_to_utc_midnight())


def calls_today() -> int:
    with engine.begin() as conn:
        row = conn.execute(text("SELECT calls FROM groq_usage WHERE day = :d"), {"d": _today()}).fetchone()
    return int(row[0]) if row else 0


def status() -> dict:
    return {
        "enabled": config.GROQ_BUDGET_ENABLED,
        "calls_today": calls_today(),
        "daily_cap": config.GROQ_MAX_PER_DAY,
        "per_minute_cap": config.GROQ_MAX_PER_MINUTE,
    }