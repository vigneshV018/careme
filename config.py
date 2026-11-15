import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env using absolute path from project root
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

APP_NAME = os.getenv("APP_NAME", "CareMe")
APP_TAGLINE = os.getenv("APP_TAGLINE", "Care from anywhere. Connected by CareMe.")
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")

raw_secret = os.getenv("SECRET_KEY", "").strip()
if not DEMO_MODE and not raw_secret:
    raise RuntimeError(
        "CRITICAL STARTUP ERROR: SECRET_KEY environment variable is missing in production (DEMO_MODE=false). "
        "Please provide a strong, unpredictable SECRET_KEY in your production environment."
    )
SECRET_KEY = raw_secret or "careme-secret-key-hackathon-2026"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./caresync.db")
PORT = int(os.getenv("PORT", "8000"))
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
ESCALATE_1_MIN = int(os.getenv("ESCALATE_1_MIN", "30"))
ESCALATE_2_MIN = int(os.getenv("ESCALATE_2_MIN", "120"))

SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
TEST_EMAIL = os.getenv("TEST_EMAIL", "").strip()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

