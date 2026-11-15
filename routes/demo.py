from datetime import datetime, timedelta, date, time
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

import os
import config
from database import get_db
from models import User, CareCircle, Medicine, DoseLog, Appointment, Notification, Membership
from seed import seed
from services.auth_service import get_current_user_optional
from services.email_service import send_email, recent_emails, get_smtp_credentials
from services.notification_service import get_user_circle
from services.scheduler import check_dose_escalations, check_appointment_reminders
from template_config import templates

def require_demo_mode():
    if not config.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo mode is disabled. Set DEMO_MODE=true in .env to enable."
        )

router = APIRouter(prefix="/demo", tags=["demo"], dependencies=[Depends(require_demo_mode)])

# Store the last action report to display prominently on the demo page
last_action_result = None

@router.get("", response_class=HTMLResponse)
def demo_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_optional)
):
    if not config.DEMO_MODE:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Demo page is disabled. Set DEMO_MODE=true in .env to enable."
        )

    circle = db.query(CareCircle).first()
    elder = circle.elder if circle else None
    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count() if user else 0

    # SMTP configuration status - read dynamically at runtime
    smtp_user, smtp_pass = get_smtp_credentials()
    has_smtp = bool(smtp_user and smtp_pass)
    smtp_status = {
        "user": smtp_user or "(Not configured in .env)",
        "has_pass": bool(smtp_pass),
        "is_active": has_smtp,
        "mode_label": "Gmail SMTP" if has_smtp else "Console Mode",
        "detail": f"Configured for {smtp_user}" if has_smtp else "SMTP_USER or SMTP_PASS is empty in .env (emails logged to terminal)"
    }

    # Suggested target email for test
    suggested_email = os.getenv("TEST_EMAIL", "").strip().strip("'\"") or "vignesh.vgm9363@gmail.com"

    return templates.TemplateResponse(
        name="demo.html",
        context={
            "request": request,
            "user": user,
            "circle": circle,
            "elder": elder,
            "demo_users": demo_users,
            "unread_notifs": unread_notifs,
            "smtp_status": smtp_status,
            "suggested_email": suggested_email,
            "escalate_1_min": config.ESCALATE_1_MIN,
            "escalate_2_min": config.ESCALATE_2_MIN,
            "last_action": last_action_result,
            "recent_emails": recent_emails
        }
    )

@router.post("/send-test-email")
def send_test_email(
    target_email: str = Form(...),
    custom_subject: str = Form(None),
    custom_note: str = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user_optional)
):
    global last_action_result

    target = target_email.strip()
    subj = custom_subject.strip() if custom_subject else "CareMe: Live System Test Email"
    headline = "CareMe Live Notification Verified"
    msg = custom_note.strip() if custom_note else "This is a real test email generated from the CareMe elderly healthcare platform. Email delivery, in-app notifications, and alert escalation pathways are fully operational."

    # Execute synchronously so the demo page immediately displays the live delivery result or exact error
    res = send_email(
        to_email=target,
        subject=subj,
        headline=headline,
        message=msg,
        details={
            "Platform": "CareMe (Remote Elderly Care)",
            "Protected Elder": "Lakshmi Devi (Coimbatore)",
            "Notification Type": "Live Verification Probe",
            "SMTP Server": "smtp.gmail.com:587 (STARTTLS)",
            "Timestamp": datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")
        },
        badge_text="Live Test Probe",
        badge_color="#14B8A6",
        action_url="http://127.0.0.1:8000/dashboard",
        action_text="Open CareMe Dashboard",
        user_id=user.id if user else None,
        notif_type="family",
        db=db,
        sync=True
    )

    is_error = not res.get("success", False)
    mode = res.get("mode")

    last_action_result = {
        "title": "Send Test Email Executed",
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "target": target,
        "is_error": is_error,
        "mode": mode,
        "error": res.get("error"),
        "error_message": res.get("error_message") or (f"Email failed: {res.get('error')}. Check SMTP_USER and SMTP_PASS (use a Gmail App Password)." if is_error else None),
        "status_text": res.get("status_text"),
        "description": f"Test email dispatched to <strong>{target}</strong>",
        "events": [
            {
                "recipient": target,
                "email": target,
                "subject": subj,
                "message": msg,
                "mode": mode,
                "is_error": is_error,
                "status": "Delivered via Gmail SMTP" if mode == "real_smtp" else ("Failed: " + str(res.get("error")) if is_error else "Console Mode (Logged to Terminal)")
            }
        ]
    }

    if is_error:
        return RedirectResponse(url="/demo?error=Email+delivery+failed", status_code=status.HTTP_302_FOUND)
    if mode == "real_smtp":
        return RedirectResponse(url="/demo?success=Test+email+delivered+via+Gmail+SMTP", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/demo?info=Email+logged+to+terminal+(Console+mode)", status_code=status.HTTP_302_FOUND)

@router.post("/test-email")
def test_email_api(db: Session = Depends(get_db), user: User = Depends(get_current_user_optional)):
    smtp_user, _ = get_smtp_credentials()
    target = os.getenv("TEST_EMAIL", "").strip().strip("'\"") or (user.email if user else (smtp_user or "vignesh.vgm9363@gmail.com"))
    res = send_email(
        to_email=target,
        subject="CareMe: Verification Test",
        headline="CareMe Live Test Email",
        message="This is a live test email sent from CareMe.",
        user_id=user.id if user else None,
        db=db,
        sync=True
    )
    return res

@router.post("/simulate-30min")
def simulate_30min_dose(
    db: Session = Depends(get_db)
):
    global last_action_result

    circle = db.query(CareCircle).first()
    if not circle:
        seed()
        circle = db.query(CareCircle).first()
    med = db.query(Medicine).filter(Medicine.circle_id == circle.id, Medicine.name == "Metformin").first()
    if not med:
        med = db.query(Medicine).filter(Medicine.circle_id == circle.id).first()

    # Create a dose scheduled 32 minutes ago (over ESCALATE_1_MIN=30)
    sched_time = datetime.now() - timedelta(minutes=config.ESCALATE_1_MIN + 2)
    test_dose = DoseLog(
        medicine_id=med.id,
        scheduled_at=sched_time,
        status="pending",
        reminded=True,  # already had initial dose-time reminder
        escalated_30=False,
        escalated_120=False
    )
    db.add(test_dose)
    db.commit()

    # Trigger scheduler logic
    events = check_dose_escalations(db)

    last_action_result = {
        "title": f"Simulated 30-Minute Unconfirmed Dose for {med.name}",
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "description": f"Created pending dose scheduled at {sched_time.strftime('%I:%M %p')} ({ESCALATE_1_MIN + 2} minutes ago). Evaluated escalation rules.",
        "note": "Notice: Alert sent ONLY to circle members with 'can_receive_alerts' (Arun & Priya). Tone is non-alarmist and never says 'missed for sure'.",
        "events": events
    }

    return RedirectResponse(url="/demo?success=30-min+escalation+simulated", status_code=status.HTTP_302_FOUND)

@router.post("/simulate-120min")
def simulate_120min_dose(
    db: Session = Depends(get_db)
):
    global last_action_result

    circle = db.query(CareCircle).first()
    if not circle:
        seed()
        circle = db.query(CareCircle).first()
    med = db.query(Medicine).filter(Medicine.circle_id == circle.id, Medicine.name == "Amlodipine").first()
    if not med:
        med = db.query(Medicine).filter(Medicine.circle_id == circle.id).first()

    # Create a dose scheduled 125 minutes ago (over ESCALATE_2_MIN=120)
    sched_time = datetime.now() - timedelta(minutes=config.ESCALATE_2_MIN + 5)
    test_dose = DoseLog(
        medicine_id=med.id,
        scheduled_at=sched_time,
        status="pending",
        reminded=True,
        escalated_30=True,
        escalated_120=False
    )
    db.add(test_dose)
    db.commit()

    # Trigger scheduler logic
    events = check_dose_escalations(db)

    last_action_result = {
        "title": f"Triggered 2-Hour Escalation for {med.name}",
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "description": f"Dose scheduled at {sched_time.strftime('%I:%M %p')} exceeded 120 minutes unconfirmed. Automatically marked as NOT CONFIRMED and escalated to the entire care circle (including caregiver Meena and elder Lakshmi).",
        "events": events
    }

    return RedirectResponse(url="/demo?success=2-hour+critical+escalation+triggered", status_code=status.HTTP_302_FOUND)

@router.post("/reset-data")
def reset_demo_data(db: Session = Depends(get_db)):
    global last_action_result

    db.close()
    from database import engine
    engine.dispose()
    seed()
    recent_emails.clear()

    last_action_result = {
        "title": "Demo Data Reset",
        "timestamp": datetime.now().strftime("%I:%M:%S %p"),
        "description": "Database reset to initial hackathon state: Lakshmi (PIN 1234), Arun, Priya, Meena, circle 482915, Metformin, Amlodipine, Atorvastatin, ~86% adherence, Dr. Ramesh appointment.",
        "events": []
    }

    return RedirectResponse(url="/demo?success=Demo+data+successfully+reset", status_code=status.HTTP_302_FOUND)
