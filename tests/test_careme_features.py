"""
tests/test_careme_features.py - Comprehensive feature test suite for CareMe.

Covers:
1. Rate-limit lockout after failed attempts.
2. Elder approval of pending circle members.
3. Permission toggles enforced on /medicines and /location.
4. TAKEN marked twice does not create duplicate dose logs.
5. Medicine add, edit, and delete lifecycle.
6. Appointment add, edit, delete, and accompany.
7. Escalation rules at 30 min (alert-authorized only) and 120 min (full circle).
8. Appointment reminder flags preventing duplicate reminder emails.
9. Remote Care Confidence score calculation (0-100, label, tone).
10. AI Assistant medical safety refusal for medication changes.
11. Prescription scan with structured Gemini response and malformed JSON fallback.
12. Prescription scan rejection of non-images and files > 10MB.
13. Emergency SOS trigger and acknowledgement lifecycle.
14. Doctor PDF export format and valid %PDF header.
15. Friendly 404 and 500 error HTML page rendering.
"""
import io
import json
from datetime import datetime, timedelta, date, time
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient
from sqlalchemy.orm import joinedload

import config
from main import app
from database import SessionLocal
from models import (
    User, CareCircle, Membership, Medicine, DoseLog,
    Appointment, EmergencyAlert, ActivityLog, Notification
)
from services.rate_limiter import (
    record_failed_login, check_login_rate_limit, reset_login_rate_limit, get_max_attempts
)
from services.confidence import compute_remote_care_confidence
from services.gemini_service import get_rule_based_assistant_answer
from services.gemini_scanner import scan_prescription_with_gemini
from services.scheduler import check_dose_escalations, check_appointment_reminders
from services.pdf_service import generate_doctor_report_pdf

CSRF_HEADER_TOKEN = "a" * 64

def get_auth_client(persona_id: int = 1) -> TestClient:
    """Helper to return an authenticated TestClient for a given persona ID with CSRF ready."""
    c = TestClient(app, follow_redirects=True)
    c.cookies.set("careme_csrf", CSRF_HEADER_TOKEN)
    c.get(f"/auth/switch/{persona_id}")
    return c

def test_rate_limit_lockout():
    """Consecutive failed login attempts lock out the account; reset unlocks it."""
    test_user_key = "lockout_test_user@example.com"
    reset_login_rate_limit(test_user_key)

    max_att = get_max_attempts()
    for _ in range(max_att - 1):
        attempts, lockout = record_failed_login(test_user_key)
        assert lockout == 0
        is_locked, _ = check_login_rate_limit(test_user_key)
        assert not is_locked

    # Final attempt that hits the limit
    attempts, lockout = record_failed_login(test_user_key)
    assert attempts >= max_att
    assert lockout > 0

    is_locked, remaining_secs = check_login_rate_limit(test_user_key)
    assert is_locked
    assert remaining_secs > 0

    # Test login endpoint recognizes locked account
    client = TestClient(app, follow_redirects=True)
    resp = client.post("/login", data={"email": test_user_key, "password": "any"})
    assert "Too many failed login attempts" in resp.text

    # Reset clears lockout
    reset_login_rate_limit(test_user_key)
    is_locked, _ = check_login_rate_limit(test_user_key)
    assert not is_locked

def test_elder_approval_grants_access(db):
    """Elder approving a pending membership activates access to medicines and circle data."""
    # Create a pending member in Lakshmi's circle
    circle = db.query(CareCircle).first()
    assert circle is not None

    test_user = User(
        name="Sunil Member",
        email="sunil_approval_test@careme.local",
        password_hash="fakehash",
        role="family"
    )
    db.add(test_user)
    db.commit()

    mem = Membership(
        circle_id=circle.id,
        user_id=test_user.id,
        relationship="Nephew",
        status="pending",
        can_view_health=False,
        can_receive_alerts=False
    )
    db.add(mem)
    db.commit()

    # Elder approves member
    elder_client = get_auth_client(persona_id=1)
    resp = elder_client.post(
        f"/circle/member/{mem.id}/approve",
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp.status_code == 200

    db.refresh(mem)
    assert mem.status == "approved"
    assert mem.can_view_health is True
    assert mem.can_receive_alerts is True

def test_permission_toggles_enforce_health_and_location(db):
    """Permissions: can_view_health=False restricts /medicines, can_view_location=False restricts /location."""
    arun = db.query(User).filter(User.name == "Arun").first()
    assert arun is not None

    mem = db.query(Membership).filter(Membership.user_id == arun.id).first()
    assert mem is not None

    arun_client = get_auth_client(persona_id=arun.id)

    # 1. Deny health view
    mem.can_view_health = False
    db.commit()
    meds_denied = arun_client.get("/medicines")
    assert meds_denied.status_code == 200
    assert ("has not shared" in meds_denied.text or "Permission Denied" in meds_denied.text or "waiting" in meds_denied.text.lower())

    # 2. Allow health view
    mem.can_view_health = True
    db.commit()
    meds_allowed = arun_client.get("/medicines")
    assert meds_allowed.status_code == 200
    assert "Medicines" in meds_allowed.text

    # 3. Deny location view
    mem.can_view_location = False
    db.commit()
    loc_denied = arun_client.get("/location")
    assert loc_denied.status_code == 200
    assert ("has not shared location" in loc_denied.text or "Permission Denied" in loc_denied.text)

    # 4. Allow location view
    mem.can_view_location = True
    db.commit()
    loc_allowed = arun_client.get("/location")
    assert loc_allowed.status_code == 200
    assert "Live Location" in loc_allowed.text or "GPS" in loc_allowed.text or "Location" in loc_allowed.text

def test_dose_taken_twice_does_not_duplicate(db):
    """Marking TAKEN twice updates status and timestamp but never creates a duplicate DoseLog."""
    dose = db.query(DoseLog).first()
    assert dose is not None
    dose_id = dose.id

    initial_count = db.query(DoseLog).count()
    elder_client = get_auth_client(persona_id=1)

    # First take
    resp1 = elder_client.post(
        f"/medicines/dose/{dose_id}/take",
        data={"redirect_to": "/dashboard"},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp1.status_code == 200

    db.refresh(dose)
    assert dose.status == "taken"
    assert dose.confirmed_at is not None
    first_confirmed_at = dose.confirmed_at

    count_after_first = db.query(DoseLog).count()
    assert count_after_first == initial_count

    # Second take (simulate double click)
    resp2 = elder_client.post(
        f"/medicines/dose/{dose_id}/take",
        data={"redirect_to": "/dashboard"},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp2.status_code == 200

    count_after_second = db.query(DoseLog).count()
    assert count_after_second == initial_count
    db.refresh(dose)
    assert dose.status == "taken"

def test_medicine_crud_lifecycle(db):
    """Complete lifecycle for adding, editing, and deleting a medicine."""
    elder_client = get_auth_client(persona_id=1)

    # 1. Add Medicine
    add_resp = elder_client.post(
        "/medicines/add",
        data={
            "name": "Atorvastatin Calcium",
            "dosage": "20mg",
            "frequency": "daily",
            "instructions": "Take at bedtime",
            "times": "night",
            "stock_remaining": "30",
            "csrf_token": CSRF_HEADER_TOKEN
        },
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert add_resp.status_code == 200
    med = db.query(Medicine).filter(Medicine.name == "Atorvastatin Calcium").first()
    assert med is not None
    assert med.dosage == "20mg"
    assert med.times == "night"

    # 2. Edit Medicine
    edit_resp = elder_client.post(
        f"/medicines/{med.id}/edit",
        data={
            "name": "Atorvastatin Calcium",
            "dosage": "40mg",
            "frequency": "daily",
            "instructions": "Take at night with water",
            "times": "night",
            "stock_remaining": "45",
            "csrf_token": CSRF_HEADER_TOKEN
        },
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert edit_resp.status_code == 200
    db.refresh(med)
    assert med.dosage == "40mg"
    assert med.stock_remaining == 45

    # 3. Delete Medicine
    del_resp = elder_client.post(
        f"/medicines/{med.id}/delete",
        data={"csrf_token": CSRF_HEADER_TOKEN},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert del_resp.status_code == 200
    deleted_med = db.query(Medicine).filter(Medicine.id == med.id).first()
    assert deleted_med is None

def test_appointment_crud_lifecycle(db):
    """Complete lifecycle for adding, editing, and deleting an appointment."""
    elder_client = get_auth_client(persona_id=1)
    circle = db.query(CareCircle).first()

    # 1. Add Appointment
    appt_dt = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%dT10:30")
    add_resp = elder_client.post(
        "/appointments/add",
        data={
            "title": "Neurology Consultation",
            "doctor": "Dr. Venkatesh",
            "specialty": "Neurologist",
            "hospital": "Ganga Hospital",
            "datetime": appt_dt,
            "notes": "Follow-up on balance assessment",
            "csrf_token": CSRF_HEADER_TOKEN
        },
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert add_resp.status_code == 200

    appt = db.query(Appointment).filter(Appointment.title == "Neurology Consultation").first()
    assert appt is not None
    assert appt.doctor == "Dr. Venkatesh"

    # 2. Edit Appointment
    edit_resp = elder_client.post(
        f"/appointments/edit/{appt.id}",
        data={
            "title": "Neurology Followup",
            "doctor": "Dr. Venkatesh MD",
            "specialty": "Neurology",
            "hospital": "Ganga Specialty Hospital",
            "datetime": appt_dt,
            "notes": "Updated instructions",
            "csrf_token": CSRF_HEADER_TOKEN
        },
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert edit_resp.status_code == 200
    db.refresh(appt)
    assert appt.title == "Neurology Followup"
    assert appt.hospital == "Ganga Specialty Hospital"

    # 3. Delete Appointment
    del_resp = elder_client.post(
        f"/appointments/delete/{appt.id}",
        data={"csrf_token": CSRF_HEADER_TOKEN},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert del_resp.status_code == 200
    deleted = db.query(Appointment).filter(Appointment.id == appt.id).first()
    assert deleted is None

def test_dose_escalation_rules_30_and_120_minutes(db):
    """
    Escalation rules:
    - At 30 minutes unconfirmed: escalates to members with can_receive_alerts=True only.
    - At 120 minutes unconfirmed: marks dose 'not_confirmed' and alerts the entire circle.
    """
    med = db.query(Medicine).first()
    assert med is not None

    # Create dose overdue by 35 minutes
    overdue_35 = datetime.utcnow() - timedelta(minutes=35)
    dose_30 = DoseLog(
        medicine_id=med.id,
        scheduled_at=overdue_35,
        status="pending",
        reminded=True,
        escalated_30=False,
        escalated_120=False
    )
    db.add(dose_30)
    db.commit()

    events = check_dose_escalations(db)
    db.refresh(dose_30)
    assert dose_30.escalated_30 is True
    assert dose_30.escalated_120 is False
    assert dose_30.status == "pending"  # Still pending at 30 min, not yet not_confirmed

    # Verify 30-min escalation was only dispatched to alert authorized members
    stages_30 = [e for e in events if e.get("stage") == "30_min_escalation"]
    assert len(stages_30) > 0
    for e in stages_30:
        assert "alert authorized" in e.get("recipient", "")

    # Now simulate dose overdue by 125 minutes
    overdue_125 = datetime.utcnow() - timedelta(minutes=125)
    dose_30.scheduled_at = overdue_125
    db.commit()

    events_120 = check_dose_escalations(db)
    db.refresh(dose_30)
    assert dose_30.escalated_120 is True
    assert dose_30.status == "not_confirmed"

    stages_120 = [e for e in events_120 if e.get("stage") == "120_min_escalation"]
    assert len(stages_120) > 0

def test_appointment_reminder_flags_prevent_duplicate_emails(db):
    """Appointment reminders set reminded_24h flag, preventing duplicate reminder sends."""
    circle = db.query(CareCircle).first()
    appt_dt = datetime.now() + timedelta(hours=18)
    appt = Appointment(
        circle_id=circle.id,
        title="Ophthalmology Check",
        doctor="Dr. Shanthi",
        specialty="Eye Care",
        hospital="Aravind Eye Hospital",
        datetime=appt_dt,
        reminded_24h=False,
        reminded_2h=False
    )
    db.add(appt)
    db.commit()

    # First run triggers reminder
    events1 = check_appointment_reminders(db)
    db.refresh(appt)
    assert appt.reminded_24h is True
    reminders_sent1 = [e for e in events1 if "24h_reminder" in e.get("stage", "")]
    assert len(reminders_sent1) > 0

    # Second run immediately after does NOT send duplicates
    events2 = check_appointment_reminders(db)
    reminders_sent2 = [e for e in events2 if appt.title in e.get("subject", "")]
    assert len(reminders_sent2) == 0

def test_confidence_score_structure_and_bounds(db):
    """Remote Care Confidence score returns integer 0-100, label, tone message, and reasons."""
    circle = db.query(CareCircle).first()
    assert circle is not None

    res = compute_remote_care_confidence(db, circle.id, use_cache=False)
    assert isinstance(res["score"], (int, float))
    assert 0 <= res["score"] <= 100
    assert res["label"] in ["All good", "Worth a check-in", "Please reach out"]
    assert len(res["reasons"]) > 0
    assert "tone_message" in res
    assert res["elder_name"] == circle.elder.name

def test_ai_assistant_refuses_medicine_stopping():
    """AI assistant refuses medication cessation or alteration questions and directs to doctor."""
    question = "Should I stop taking my Metformin because I feel better?"
    answer = get_rule_based_assistant_answer(question)
    assert "Medical Safety Advisory" in answer
    assert "cannot advise stopping" in answer.lower()
    assert "consult" in answer.lower()

    # Also test via assistant asking endpoint
    elder_client = get_auth_client(persona_id=1)
    resp = elder_client.post(
        "/assistant/ask",
        data={"question": question, "csrf_token": CSRF_HEADER_TOKEN},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "Medical Safety Advisory" in data.get("answer", "")

def test_prescription_scan_valid_json_and_fallback(mock_gemini):
    """Prescription scanner parses structured medications from Gemini, and handles malformed output cleanly."""
    valid_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF" + b"0" * 200

    # 1. Valid Gemini JSON
    mock_gemini.models.generate_content.return_value.text = json.dumps([
        {
            "name": "Telmisartan",
            "dosage": "40mg",
            "times": ["morning"],
            "duration_days": 30,
            "instructions": "Take before breakfast"
        }
    ])
    res = scan_prescription_with_gemini(valid_bytes, "image/jpeg")
    assert res["success"] is True
    assert len(res["items"]) == 1
    assert res["items"][0]["name"] == "Telmisartan"
    assert res["items"][0]["dosage"] == "40mg"

    # 2. Malformed JSON fallback
    mock_gemini.models.generate_content.return_value.text = "NOT_A_VALID_JSON_STRING_AT_ALL {broken"
    fallback_res = scan_prescription_with_gemini(valid_bytes, "image/jpeg")
    assert fallback_res["success"] is False
    assert "Could not format prescription" in fallback_res["error"]
    assert len(fallback_res["items"]) == 0

def test_prescription_scan_rejects_non_image_and_oversize():
    """Prescription scanning endpoint enforces magic byte verification and 10MB limit."""
    elder_client = get_auth_client(persona_id=1)

    # 1. Non-image file (plain text with spoofed jpg extension)
    fake_txt = io.BytesIO(b"This is just a text file claiming to be an image")
    resp_bad = elder_client.post(
        "/medicines/scan",
        files={"file": ("fake.jpg", fake_txt, "image/jpeg")},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp_bad.status_code == 400
    assert "Invalid image content" in resp_bad.json()["error"]

    # 2. Oversized image > 10MB
    oversized = io.BytesIO(b"\xFF\xD8\xFF" + b"0" * (11 * 1024 * 1024))
    resp_large = elder_client.post(
        "/medicines/scan",
        files={"file": ("large.jpg", oversized, "image/jpeg")},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp_large.status_code == 400
    assert "exceeds the 10MB limit" in resp_large.json()["error"]

def test_emergency_sos_trigger_and_acknowledgement(db):
    """Elder triggers SOS, creating active alert; family member acknowledges it."""
    elder_client = get_auth_client(persona_id=1)
    circle = db.query(CareCircle).first()

    # 1. Trigger SOS
    resp = elder_client.post(
        "/alerts/sos",
        data={"redirect_to": "/dashboard", "lat": "11.0168", "lng": "76.9558"},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert resp.status_code == 200

    alert = db.query(EmergencyAlert).filter(
        EmergencyAlert.circle_id == circle.id,
        EmergencyAlert.acknowledged_at == None
    ).order_by(EmergencyAlert.triggered_at.desc()).first()
    assert alert is not None
    assert alert.acknowledged_at is None

    # 2. Arun (family) acknowledges SOS
    arun = db.query(User).filter(User.name == "Arun").first()
    arun_client = get_auth_client(persona_id=arun.id)
    ack_resp = arun_client.post(
        f"/alerts/{alert.id}/acknowledge",
        data={"redirect_to": "/dashboard"},
        headers={"x-csrf-token": CSRF_HEADER_TOKEN}
    )
    assert ack_resp.status_code == 200

    db.refresh(alert)
    assert alert.acknowledged_at is not None
    assert alert.acknowledged_by == arun.id

def test_doctor_pdf_report_generation(db):
    """Doctor PDF report exports valid %PDF header and content."""
    circle = db.query(CareCircle).first()
    elder = circle.elder

    meds = db.query(Medicine).filter(Medicine.circle_id == circle.id).all()
    med_list = [
        {"name": m.name, "dosage": m.dosage, "schedule": m.times, "instructions": m.instructions or ""}
        for m in meds
    ]

    pdf_bytes = generate_doctor_report_pdf(
        elder_name=elder.name,
        elder_age=elder.age or 75,
        elder_city=elder.city or "Coimbatore",
        adherence_pct=95.0,
        taken_count=19,
        missed_count=1,
        total_doses=20,
        streak_days=14,
        confidence_score=92,
        confidence_label="All good",
        medicines=med_list,
        circle_members=["Arun (Son)", "Priya (Daughter)"]
    )
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 500
    assert pdf_bytes.startswith(b"%PDF-")

    # Also test via the endpoint
    elder_client = get_auth_client(persona_id=1)
    pdf_resp = elder_client.get("/assistant/report/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    assert pdf_resp.content.startswith(b"%PDF-")

def test_friendly_404_page_rendered():
    """Non-existent URL renders friendly 404 HTML template with CareMe branding."""
    client = TestClient(app, follow_redirects=True)
    resp = client.get("/this-route-definitely-does-not-exist-404")
    assert resp.status_code == 404
    assert "404" in resp.text
    assert "CareMe" in resp.text
    assert "Back to Dashboard" in resp.text or "Go to Home" in resp.text or "Return" in resp.text

def test_friendly_500_page_rendered():
    """Internal server error handler returns friendly 500 HTML template."""
    client = TestClient(app, follow_redirects=True)
    # Simulate 500 error by querying an endpoint with invalid state or calling exception handler
    from starlette.requests import Request
    from main import server_error_page

    req = Request({"type": "http", "method": "GET", "path": "/test-500", "headers": []})
    resp = server_error_page(req, Exception("Simulated unexpected test error"))
    assert resp.status_code == 500
    assert "500" in resp.body.decode()
    assert "CareMe" in resp.body.decode()
