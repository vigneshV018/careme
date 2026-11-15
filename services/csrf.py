"""
services/csrf.py - Cross-Site Request Forgery (CSRF) Protection for CareMe.
Enforces cryptographically strong CSRF tokens across all form submissions and AJAX endpoints.
"""
import secrets
import hmac
from typing import Optional
from fastapi import Request, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware

CSRF_COOKIE_NAME = "careme_csrf"

def generate_csrf_token() -> str:
    """Generates a secure 64-character hex CSRF token."""
    return secrets.token_hex(32)

def get_or_create_csrf_token(request: Request) -> str:
    """Retrieves existing token from cookie, or generates a fresh one."""
    token = request.cookies.get(CSRF_COOKIE_NAME)
    if not token or len(token) < 32:
        token = getattr(request.state, "new_csrf_token", None)
        if not token:
            token = generate_csrf_token()
            request.state.new_csrf_token = token
    return token

async def extract_csrf_token_from_request(request: Request) -> Optional[str]:
    """Extracts CSRF token from headers or form-data."""
    # 1. Check custom headers
    header_token = request.headers.get("x-csrf-token") or request.headers.get("x-csrftoken")
    if header_token:
        return header_token.strip()

    # 2. Check form data (for standard form posts)
    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            form_token = form.get("csrf_token")
            if form_token:
                return str(form_token).strip()
        except Exception:
            pass

    return None

def verify_csrf_token(submitted_token: Optional[str], cookie_token: Optional[str]) -> bool:
    """Safely compares submitted token against cookie token using constant-time comparison."""
    if not submitted_token or not cookie_token:
        return False
    return hmac.compare_digest(submitted_token.strip(), cookie_token.strip())

class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Middleware that:
    1. Attaches/sets the CSRF cookie on all HTTP responses if missing.
    2. Validates CSRF token on unsafe mutating requests (POST, PUT, DELETE, PATCH).
    """
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
        new_token = None

        if not cookie_token:
            new_token = generate_csrf_token()
            request.state.new_csrf_token = new_token
            cookie_token = new_token

        # Unsafe methods require CSRF validation
        if method in {"POST", "PUT", "DELETE", "PATCH"}:
            # Exclude login/logout if desired, but verifying on all POST is even safer!
            # Check submitted token
            submitted_token = request.headers.get("x-csrf-token") or request.headers.get("x-csrftoken")
            
            # If not in header, read from form if possible
            if not submitted_token:
                content_type = request.headers.get("content-type", "")
                if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
                    form = await request.form()
                    submitted_token = form.get("csrf_token")

            # Validate
            if not verify_csrf_token(submitted_token, cookie_token):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="CSRF validation failed. Token invalid or missing. Please reload the page."
                )

        response = await call_next(request)

        # Set cookie if new token was generated or cookie was not present
        if new_token:
            from config import DEMO_MODE
            is_https = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https")
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=new_token,
                httponly=False,  # Allow client JS to read into headers for AJAX
                samesite="lax",
                secure=(not DEMO_MODE and is_https),
                path="/"
            )

        return response

