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

def is_request_https(request: Request = None) -> bool:
    """Checks whether the incoming request is HTTPS either directly or via reverse proxy headers."""
    if not request:
        return False
    if getattr(request, "url", None) and request.url.scheme == "https":
        return True
    if hasattr(request, "headers"):
        x_proto = request.headers.get("x-forwarded-proto", "")
        if x_proto:
            first_proto = x_proto.split(",")[0].strip().lower()
            if first_proto == "https":
                return True
        x_ssl = request.headers.get("x-forwarded-ssl", "").strip().lower()
        if x_ssl in ("on", "1"):
            return True
    return False

def create_session_token(user_id: int) -> str:
    """Creates a cryptographically signed session token: {user_id}.{sig}."""
    payload = str(user_id)
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"

def extract_user_id(token: str) -> int | None:
    """Extracts and verifies user ID from signed token or unsigned fallback."""
    if not token:
        return None
    token = str(token).strip()
    if "." in token:
        parts = token.split(".", 1)
        payload, sig = parts[0], parts[1]
        expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected_sig):
            try:
                return int(payload)
            except ValueError:
                return None
    # Fallback to plain integer if unsigned legacy cookie
    try:
        return int(token)
    except ValueError:
        return None

def login_user(response: Response, user_id: int, request: Request = None):
    is_secure = is_request_https(request)
    token = create_session_token(user_id)

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=86400 * 7,
        samesite="lax",
        path="/",
        secure=is_secure
    )

def logout_user(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    response.delete_cookie(key=LEGACY_COOKIE_NAME, path="/")

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
    token_str = request.cookies.get(COOKIE_NAME) or request.cookies.get(LEGACY_COOKIE_NAME)
    if not token_str:
        return None
    user_id = extract_user_id(token_str)
    if not user_id:
        return None
    try:
        user = db.query(User).filter(User.id == user_id).first()
        return user
    except Exception:
        return None

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"}
        )
    return user

