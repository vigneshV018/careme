"""
services/rate_limiter.py - Rate Limiting Engine for CareMe Authentication.
Limits failed login attempts to 10 in DEMO_MODE (5 in production), then imposes a 5-minute lockout window.
"""
from datetime import datetime, timedelta
from typing import Dict, Tuple
from config import DEMO_MODE, MAX_FAILED_LOGINS_DEMO, MAX_FAILED_LOGINS_PROD, LOCKOUT_SECONDS

# In-memory tracking: {key: {"count": int, "locked_until": datetime | None}}
_login_attempts: Dict[str, Dict] = {}

def get_max_attempts() -> int:
    """Returns max attempts: 10 for DEMO_MODE, 5 for production."""
    return MAX_FAILED_LOGINS_DEMO if DEMO_MODE else MAX_FAILED_LOGINS_PROD

def check_login_rate_limit(key: str) -> Tuple[bool, int]:
    """
    Checks if a given user/IP is currently locked out from logging in.
    Returns: (is_locked: bool, remaining_seconds: int)
    """
    clean_key = key.strip().lower()
    entry = _login_attempts.get(clean_key)
    if not entry:
        return False, 0

    locked_until = entry.get("locked_until")
    if locked_until:
        now = datetime.now()
        if now < locked_until:
            remaining = int((locked_until - now).total_seconds())
            return True, max(1, remaining)
        else:
            # Lockout expired, clear entry
            _login_attempts.pop(clean_key, None)
            return False, 0

    return False, 0

def record_failed_login(key: str) -> Tuple[int, int]:
    """
    Records a failed login attempt. If attempts reach max_attempts, locks for 5 minutes.
    Returns: (attempts_count: int, remaining_lockout_seconds: int)
    """
    clean_key = key.strip().lower()
    now = datetime.now()
    max_attempts = get_max_attempts()

    entry = _login_attempts.get(clean_key)
    if not entry:
        entry = {"count": 0, "locked_until": None}
        _login_attempts[clean_key] = entry

    entry["count"] += 1
    if entry["count"] >= max_attempts:
        entry["locked_until"] = now + timedelta(seconds=LOCKOUT_SECONDS)
        return entry["count"], LOCKOUT_SECONDS

    return entry["count"], 0

def reset_login_rate_limit(key: str) -> None:
    """Resets failed attempt count upon successful authentication."""
    clean_key = key.strip().lower()
    _login_attempts.pop(clean_key, None)

