import time
import base64
import hmac
import hashlib
from passlib.context import CryptContext
from fastapi import Request, Response, Depends, HTTPException, status
from sqlalchemy.orm import Session
from database import get_db
from models import User
from config import DEMO_MODE, SECRET_KEY

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "careme_session"
LEGACY_COOKIE_NAME = "caresync_session"

def hash_password(password: str) -> str:
    if not password:
        return ""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False

def hash_pin(pin: str) -> str:
    if not pin:
        return ""
    return pwd_context.hash(str(pin).strip())

def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    if not hashed_pin:
        return False
    try:
        return pwd_context.verify(str(plain_pin).strip(), hashed_pin)
    except Exception:
        return False

def login_user(response: Response, user_id: int, request: Request = None):
    is_https = False
    if request:
        is_https = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
    # Secure flag only when DEMO_MODE=false and request is HTTPS, so http://127.0.0.1 still works locally
    is_secure = (not DEMO_MODE and is_https)

    response.set_cookie(
        key=COOKIE_NAME,
        value=str(user_id),
        httponly=True,
        max_age=86400 * 7,
        samesite="lax",
        secure=is_secure
    )

def logout_user(response: Response):
    response.delete_cookie(key=COOKIE_NAME)
    response.delete_cookie(key=LEGACY_COOKIE_NAME)

def generate_password_reset_token(user: User) -> str:
    """
    Generates a time-limited (30 min), single-use reset token.
    Combines user ID, timestamp, and an HMAC hash of the current password_hash.
    When the password changes, any existing tokens instantly become invalid.
    """
    timestamp = int(time.time())
    payload = f"{user.id}:{timestamp}"
    key = f"{SECRET_KEY}:{user.password_hash}".encode("utf-8")
    sig = hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")

def verify_password_reset_token(token: str, db: Session) -> User | None:
    """
    Verifies a password reset token.
    Must be under 30 minutes old and have a valid signature matching user's current password.
    """
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        parts = raw.split(":")
        if len(parts) != 3:
            return None
        user_id = int(parts[0])
        timestamp = int(parts[1])
        signature = parts[2]

        # 30-minute expiration check (1800 seconds)
        if time.time() - timestamp > 1800 or timestamp > time.time() + 60:
            return None

        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            return None

        key = f"{SECRET_KEY}:{user.password_hash}".encode("utf-8")
        expected_sig = hmac.new(key, f"{user_id}:{timestamp}".encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None

        return user
    except Exception:
        return None

def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id_str = request.cookies.get(COOKIE_NAME) or request.cookies.get(LEGACY_COOKIE_NAME)
    if not user_id_str:
        return None
    try:
        user_id = int(user_id_str)
        user = db.query(User).filter(User.id == user_id).first()
        return user
    except Exception:
        return None

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"}
        )
    return user

