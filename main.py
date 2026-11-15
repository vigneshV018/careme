from pathlib import Path
from dotenv import load_dotenv

# 1. Load .env at the very top using absolute path before any other imports that read environment variables
env_file_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_file_path)

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from database import engine, Base, SessionLocal
from models import User
from seed import seed
from services.scheduler import start_scheduler, shutdown_scheduler

from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.medicines import router as medicines_router
from routes.appointments import router as appointments_router
from routes.alerts import router as alerts_router
from routes.circle import router as circle_router
from routes.notifications import router as notifications_router
from routes.api import router as api_router
from routes.demo import router as demo_router
from routes.assistant import router as assistant_router
from routes.settings import router as settings_router
from services.csrf import CSRFMiddleware
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("careme")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Requirement 5: Print one line on startup
    from services.email_service import get_smtp_credentials
    smtp_user_val, smtp_pass_val = get_smtp_credentials()
    if smtp_user_val and smtp_pass_val:
        print(f"Email: Gmail SMTP configured for {smtp_user_val}", flush=True)
        logger.info(f"Email: Gmail SMTP configured for {smtp_user_val}")
    else:
        print("Email: NOT configured, using Console mode", flush=True)
        logger.info("Email: NOT configured, using Console mode")

    # Startup: ensure tables exist
    logger.info("Initializing CareMe database...")
    Base.metadata.create_all(bind=engine)
    
    # Auto-seed if database is empty ONLY when DEMO_MODE is true
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        if user_count == 0:
            if config.DEMO_MODE:
                logger.info("Empty database detected and DEMO_MODE=true. Auto-seeding initial CareMe demo data...")
                seed()
            else:
                logger.info("Empty database detected with DEMO_MODE=false. Fresh production database initialized without demo users.")
    except Exception as e:
        logger.error(f"Error checking/seeding database: {e}")
    finally:
        db.close()

    # Start background scheduler for dose reminders and escalations
    try:
        start_scheduler()
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    yield

    # Shutdown
    try:
        shutdown_scheduler()
    except Exception as e:
        logger.error(f"Error shutting down scheduler: {e}")

app = FastAPI(
    title="CareMe",
    description="Care from anywhere. Connected by CareMe.",
    lifespan=lifespan
)

# Ensure static and templates folders exist
os.makedirs("static/css", exist_ok=True)
os.makedirs("static/js", exist_ok=True)
os.makedirs("templates", exist_ok=True)

from fastapi.responses import JSONResponse, FileResponse

@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")

@app.get("/service-worker.js", include_in_schema=False)
async def get_service_worker():
    return FileResponse("static/service-worker.js", media_type="application/javascript")

app.mount("/static", StaticFiles(directory="static"), name="static")

# CSRF Protection Middleware
app.add_middleware(CSRFMiddleware)

# Include Routers
app.include_router(dashboard_router)
app.include_router(auth_router)
app.include_router(medicines_router)
app.include_router(appointments_router)
app.include_router(alerts_router)
app.include_router(circle_router)
app.include_router(notifications_router)
app.include_router(settings_router)
app.include_router(api_router)
app.include_router(demo_router)
app.include_router(assistant_router)

# Friendly Error Handlers (Requirement 3)
from template_config import templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse, RedirectResponse

@app.exception_handler(404)
def not_found_handler(request: Request, exc):
    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

@app.exception_handler(500)
def server_error_handler(request: Request, exc):
    logger.error(f"Internal server error on {request.url.path}: {exc}", exc_info=True)
    if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
    return templates.TemplateResponse("500.html", {"request": request}, status_code=500)

@app.exception_handler(StarletteHTTPException)
def http_exception_handler(request: Request, exc: StarletteHTTPException):
    # 1. Real RedirectResponse for any 3xx status (Requirement 3)
    if 300 <= exc.status_code < 400:
        location = exc.headers.get("Location") if exc.headers else None
        if not location:
            location = "/login"
        return RedirectResponse(url=location, status_code=exc.status_code)

    # 2. Redirect unauthenticated browser requests to /login
    if exc.status_code in (401, 403):
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return RedirectResponse(url="/login?error=Please+log+in+to+continue", status_code=302)

    # 3. Only show friendly 404 page for real not found errors
    if exc.status_code == 404:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        return templates.TemplateResponse("404.html", {"request": request}, status_code=404)

    # 4. Only show friendly 500 page for real server errors
    if exc.status_code >= 500:
        if request.url.path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        return templates.TemplateResponse("500.html", {"request": request}, status_code=exc.status_code)

    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

