"""
tests/conftest.py - Pytest fixtures and mock configuration for CareMe test suite.

Configures:
1. Isolated temporary SQLite database.
2. Complete mocks for external calls (SMTP/Gmail and Google Gemini).
3. TestClient instances with and without redirects.
4. Auto-seeding of demo users and circle data.
"""
import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

# Enforce test environment variables BEFORE importing application modules
TEST_DB_PATH = os.path.abspath("./test_careme.db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ["DEMO_MODE"] = "true"
os.environ["SECRET_KEY"] = "careme-test-secret-key-32-chars-long-secure-and-safe"
os.environ["GEMINI_API_KEY"] = "test-mock-gemini-api-key"
os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
os.environ["SMTP_USER"] = "testcareme@gmail.com"
os.environ["SMTP_PASS"] = "testapppass1234"

# -----------------------------------------------------------------------------
# Mock external services before app load: SMTP & Gemini & Background Scheduler
# -----------------------------------------------------------------------------

# Mock SMTP instance
mock_smtp_instance = MagicMock()
mock_smtp_instance.ehlo.return_value = (250, b"ok")
mock_smtp_instance.starttls.return_value = (220, b"ready")
mock_smtp_instance.login.return_value = (235, b"authenticated")
mock_smtp_instance.send_message.return_value = {}
mock_smtp_instance.quit.return_value = (221, b"bye")
mock_smtp_instance.close.return_value = None

# Mock Gemini response
DEFAULT_GEMINI_MEDS_JSON = json.dumps([
    {
        "name": "Metformin",
        "dosage": "500mg",
        "times": ["morning", "night"],
        "duration_days": 30,
        "instructions": "Take after meals with water"
    },
    {
        "name": "Amlodipine",
        "dosage": "5mg",
        "times": ["morning"],
        "duration_days": 30,
        "instructions": "Take once daily in the morning"
    }
])

mock_gemini_response = MagicMock()
mock_gemini_response.text = DEFAULT_GEMINI_MEDS_JSON

mock_gemini_client = MagicMock()
mock_gemini_client.models.generate_content.return_value = mock_gemini_response

# Patch smtplib and genai globally for all tests
patch_smtp = patch("smtplib.SMTP", return_value=mock_smtp_instance)
patch_smtp.start()

# Patch scheduler start so tests don't run background threads
patch_scheduler_start = patch("services.scheduler.start_scheduler", return_value=None)
patch_scheduler_start.start()

patch_scheduler_shutdown = patch("services.scheduler.shutdown_scheduler", return_value=None)
patch_scheduler_shutdown.start()

try:
    import google.genai
    patch_genai = patch("google.genai.Client", return_value=mock_gemini_client)
    patch_genai.start()
except ImportError:
    pass

# Import application components after mocks are in place
import config
from database import engine, SessionLocal, Base, get_db
from main import app
from seed import seed
from starlette.testclient import TestClient

@pytest.fixture(scope="session", autouse=True)
def setup_test_suite():
    """
    Sets up the test SQLite database, seeds it with initial demo data,
    and handles session teardown.
    """
    # Create tables and seed data
    seed()
    yield
    # Cleanup after test suite
    try:
        engine.dispose()
    except Exception:
        pass
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass

@pytest.fixture
def db():
    """Provides a fresh database session for direct model queries in tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def client():
    """TestClient that automatically follows 3xx redirects."""
    return TestClient(app, follow_redirects=True)

@pytest.fixture
def raw_client():
    """TestClient that does NOT follow redirects (for testing redirect codes & cookie headers)."""
    return TestClient(app, follow_redirects=False)

@pytest.fixture
def csrf_token(client):
    """
    Helper fixture that hits /login to receive a CSRF cookie and returns the token string.
    """
    resp = client.get("/login")
    token = client.cookies.get("careme_csrf")
    if not token:
        # Fallback to generating one matching cookie
        import secrets
        token = secrets.token_hex(32)
        client.cookies.set("careme_csrf", token)
    return token

@pytest.fixture
def mock_gemini():
    """Helper to customize mock Gemini responses within specific tests."""
    return mock_gemini_client

