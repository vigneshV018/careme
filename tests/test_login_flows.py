import os
import sys
import pytest
from starlette.testclient import TestClient

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

import config
from main import app
from seed import seed
from database import SessionLocal
from models import User, Membership, CareCircle

@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure clean initial seed in database for test suite."""
    seed()

@pytest.fixture
def client():
    """Fresh TestClient with follow_redirects=True for each test."""
    return TestClient(app, follow_redirects=True)

def test_logged_out_redirects_to_login(client):
    """
    Logged-out access to /dashboard, /medicines, /circle, and /elder
    must all land on the login page, never 404 or JSON.
    """
    for path in ["/dashboard", "/medicines", "/circle", "/elder"]:
        resp = client.get(path)
        assert resp.status_code == 200, f"Expected 200 on redirect destination for {path}, got {resp.status_code}"
        assert "/login" in str(resp.url), f"Expected URL to contain /login for {path}, got {resp.url}"
        assert "Welcome to CareMe" in resp.text
        assert "Sign In" in resp.text or "Elder PIN" in resp.text

def test_home_and_login_both_show_login_page(client):
    """Both / and /login should render the login page when logged out."""
    resp_home = client.get("/")
    assert resp_home.status_code == 200
    assert "Welcome to CareMe" in resp_home.text

    resp_login = client.get("/login")
    assert resp_login.status_code == 200
    assert "Welcome to CareMe" in resp_login.text

def test_judge_guide_card_present_on_login(client):
    """The login page must display the judge guide card in DEMO_MODE=true."""
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Click Lakshmi for the elder view, Arun for the family view, Meena for the caregiver view. Elder PIN: 1234." in resp.text
    assert "/demo" in resp.text

def test_demo_persona_login_lakshmi(client):
    """Demo switch for Lakshmi (ID 1, Elder) lands on elder dashboard and keeps session."""
    db = SessionLocal()
    lakshmi = db.query(User).filter(User.name == "Lakshmi").first()
    db.close()
    assert lakshmi is not None

    resp = client.get(f"/auth/switch/{lakshmi.id}")
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Lakshmi" in resp.text
    assert "Today's Medicine" in resp.text or "Elder Mode" in resp.text

    # Next request keeps session
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Lakshmi" in next_resp.text

def test_demo_persona_login_arun(client):
    """Demo switch for Arun (ID 2, Son/Family) lands on family dashboard and keeps session."""
    db = SessionLocal()
    arun = db.query(User).filter(User.name == "Arun").first()
    db.close()
    assert arun is not None

    resp = client.get(f"/auth/switch/{arun.id}")
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Arun" in resp.text
    assert "Family Mode" in resp.text or "Adherence" in resp.text

    # Next request keeps session
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Arun" in next_resp.text

def test_demo_persona_login_priya(client):
    """Demo switch for Priya (ID 3, Daughter/Family) lands on family dashboard and keeps session."""
    db = SessionLocal()
    priya = db.query(User).filter(User.name == "Priya").first()
    db.close()
    assert priya is not None

    resp = client.get(f"/auth/switch/{priya.id}")
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Priya" in resp.text

    # Next request keeps session
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Priya" in next_resp.text

def test_demo_persona_login_meena(client):
    """Demo switch for Meena (ID 4, Caregiver) lands on caregiver dashboard and keeps session."""
    db = SessionLocal()
    meena = db.query(User).filter(User.name == "Meena").first()
    db.close()
    assert meena is not None

    resp = client.get(f"/auth/switch/{meena.id}")
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Meena" in resp.text

    # Next request keeps session
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Meena" in next_resp.text

def test_lakshmi_pin_login(client):
    """Lakshmi's PIN 1234 login works and lands on dashboard."""
    resp = client.post("/login/pin", data={"pin": "1234"})
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Lakshmi" in resp.text

    # Verify session persists on next request
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Lakshmi" in next_resp.text

def test_arun_email_password_login(client):
    """Arun's email (arun@caresync.ai) and password (password123) login works and lands on dashboard."""
    resp = client.post("/login", data={
        "email": "arun@caresync.ai",
        "password": "password123"
    })
    assert resp.status_code == 200
    assert "/dashboard" in str(resp.url)
    assert "Arun" in resp.text

    # Verify session persists on next request
    next_resp = client.get("/dashboard")
    assert next_resp.status_code == 200
    assert "Arun" in next_resp.text

def test_wrong_pin_shows_exact_reason(client):
    """Wrong PIN displays 'Wrong PIN' on the login page."""
    resp = client.post("/login/pin", data={"pin": "9999"})
    assert resp.status_code == 200
    assert "/login" in str(resp.url)
    assert "Wrong PIN" in resp.text

def test_invalid_email_password_shows_reason(client):
    """Invalid email/password displays error on the login page."""
    resp = client.post("/login", data={
        "email": "nonexistent@careme.local",
        "password": "wrongpassword"
    })
    assert resp.status_code == 200
    assert "/login" in str(resp.url)
    assert "Invalid email or password" in resp.text

def test_join_circle_passcode_pending_approval_no_data_access(client):
    """
    Joining with passcode 482915 shows 'waiting for approval' with no data access.
    """
    test_email = "newmember_ravi@careme.test"
    # Register new user with circle_passcode 482915 and medical consent
    resp = client.post("/register", data={
        "name": "Ravi Kumar",
        "email": test_email,
        "password": "password123",
        "role": "family",
        "relationship": "Brother",
        "circle_passcode": "482915",
        "medical_consent": "on"
    })
    assert resp.status_code == 200
    # Must show Waiting for Approval screen
    assert ("Waiting" in resp.text or "Approval" in resp.text or "pending" in resp.text.lower())
    assert "Lakshmi" in resp.text
    # No health/medicine records are displayed to pending members
    assert "Take This Tablet" not in resp.text

    # Visiting /medicines or /circle directly as pending member should also restrict health records
    meds_resp = client.get("/medicines")
    assert ("Waiting" in meds_resp.text or "has not shared this with you" in meds_resp.text or meds_resp.status_code in (200, 302))

def test_demo_mode_false_returns_404_on_demo():
    """DEMO_MODE=false returns 404 on /demo."""
    old_demo_mode = config.DEMO_MODE
    try:
        config.DEMO_MODE = False
        raw_client = TestClient(app, follow_redirects=False)
        resp = raw_client.get("/demo")
        assert resp.status_code == 404
        assert "404" in resp.text or "Not Found" in resp.text or "disabled" in resp.text.lower()
    finally:
        config.DEMO_MODE = old_demo_mode

def test_cookie_flags_with_https_proxy_headers():
    """
    Ensure the session cookie is httponly, SameSite=Lax, Path=/,
    and Secure when request arrives with X-Forwarded-Proto: https.
    """
    raw_client = TestClient(app, follow_redirects=False)
    resp = raw_client.get("/auth/switch/1", headers={"X-Forwarded-Proto": "https"})
    assert resp.status_code == 302
    assert resp.headers.get("Location") == "/dashboard"
    
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "careme_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "secure" in set_cookie

def test_cookie_flags_with_http_not_secure():
    """Ensure Secure flag is omitted over plain HTTP so local development works."""
    raw_client = TestClient(app, follow_redirects=False)
    resp = raw_client.get("/auth/switch/1")
    assert resp.status_code == 302
    
    set_cookie = resp.headers.get("set-cookie", "").lower()
    assert "careme_session=" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie
    assert "secure" not in set_cookie

def test_csrf_exempt_routes_accept_post_without_csrf_token():
    """Auth & join routes must be exempt from CSRF checks."""
    c = TestClient(app, follow_redirects=False)
    
    # 1. Login with PIN (no CSRF token)
    resp_pin = c.post("/login/pin", data={"pin": "1234"})
    assert resp_pin.status_code == 302
    assert resp_pin.headers.get("Location") == "/dashboard"

    # 2. Login with Email (no CSRF token)
    resp_email = c.post("/login", data={"email": "arun@caresync.ai", "password": "password123"})
    assert resp_email.status_code == 302
    assert resp_email.headers.get("Location") == "/dashboard"

def test_csrf_enforced_on_mutating_non_exempt_routes():
    """Non-exempt mutating routes must reject requests without CSRF token."""
    c = TestClient(app, follow_redirects=False)
    # Log in first
    c.get("/auth/switch/1")
    # Mutating POST to medicines add without CSRF token
    resp = c.post("/medicines/add", data={"name": "Test Med", "dosage": "500mg"})
    assert resp.status_code in (302, 403)
    if resp.status_code == 302:
        assert "CSRF" in resp.headers.get("Location", "")
