"""
services/timezone.py - Explicit Asia/Kolkata Timezone Engine for CareMe.
Render and production cloud servers run in UTC. This module standardizes all
scheduler triggers, database calculations, and user-facing timestamps to Asia/Kolkata (IST).
"""
import zoneinfo
from datetime import datetime, timezone
from typing import Optional

KOLKATA_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")

def now_kolkata() -> datetime:
    """Returns the current datetime in Asia/Kolkata timezone."""
    return datetime.now(KOLKATA_TZ)

def to_kolkata(dt: Optional[datetime]) -> Optional[datetime]:
    """Converts a naive or aware datetime to Asia/Kolkata."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        # Naive datetime from SQLite/PostgreSQL: localize to Kolkata
        return dt.replace(tzinfo=KOLKATA_TZ)
    return dt.astimezone(KOLKATA_TZ)

def format_kolkata(dt: Optional[datetime], fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Formats a datetime in Asia/Kolkata timezone."""
    if dt is None:
        return ""
    kt = to_kolkata(dt)
    return kt.strftime(fmt)

def current_time_str() -> str:
    """Returns current HH:MM in Asia/Kolkata."""
    return now_kolkata().strftime("%H:%M")

def current_date_str() -> str:
    """Returns current YYYY-MM-DD in Asia/Kolkata."""
    return now_kolkata().strftime("%Y-%m-%d")

