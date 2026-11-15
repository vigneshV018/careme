import json
import os
from datetime import datetime, date, timedelta, time
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from template_config import templates
from sqlalchemy.orm import Session
from database import get_db
from models import Medicine, DoseLog, CareCircle, User, Notification
from services.auth_service import get_current_user
from services.notification_service import (
    get_user_circle, get_user_permissions, log_activity, notify_circle
)
from services.gemini_scanner import scan_prescription_with_gemini, TIME_MAPPING
from config import GEMINI_API_KEY, DEMO_MODE

router = APIRouter(prefix="/medicines", tags=["medicines"])

@router.get("", response_class=HTMLResponse)
def medicines_list(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    permissions = get_user_permissions(db, user, circle.id)
    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    if user.role != "elder" and not permissions.get("can_view_health"):
        return templates.TemplateResponse("restricted_access.html", {
            "request": request,
            "user": user,
            "circle": circle,
            "elder": circle.elder,
            "feature": "Medicines & Prescriptions",
            "message": f"{circle.elder.name} has not shared medicine details with you.",
            "demo_users": demo_users,
            "unread_notifs": unread_notifs
        })

    medicines = db.query(Medicine).filter(Medicine.circle_id == circle.id).all()

    # Past 7 days logs
    seven_days_ago = datetime.combine(date.today() - timedelta(days=7), datetime.min.time())
    recent_logs = db.query(DoseLog).join(Medicine).filter(
        Medicine.circle_id == circle.id,
        DoseLog.scheduled_at >= seven_days_ago
    ).order_by(DoseLog.scheduled_at.desc()).all()

    return templates.TemplateResponse("medicines.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "medicines": medicines,
        "recent_logs": recent_logs,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.get("/add", response_class=HTMLResponse)
def medicine_add_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines"):
        return RedirectResponse(url="/medicines?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()
    has_gemini = bool(os.getenv("GEMINI_API_KEY", GEMINI_API_KEY).strip())

    return templates.TemplateResponse("medicine_form.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "permissions": permissions,
        "medicine": None,
        "action": "add",
        "demo_users": demo_users,
        "unread_notifs": unread_notifs,
        "gemini_configured": has_gemini,
        "demo_mode": DEMO_MODE
    })

@router.post("/scan")
async def scan_prescription(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return JSONResponse({"success": False, "error": "Care Circle not found."}, status_code=404)

    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines") and not permissions.get("is_owner") and user.role != "elder":
        return JSONResponse({"success": False, "error": "Permission denied. You do not have permission to edit medicines."}, status_code=403)

    content_type = file.content_type or "image/jpeg"
    filename = file.filename or ""
    allowed_exts = (".jpg", ".jpeg", ".png", ".webp")
    if not (content_type.startswith("image/") or filename.lower().endswith(allowed_exts)):
        return JSONResponse({
            "success": False,
            "error": "Invalid image file format. Please upload or snap a JPG or PNG prescription photo."
        }, status_code=400)

    try:
        image_bytes = await file.read()
        if not image_bytes or len(image_bytes) == 0:
            return JSONResponse({
                "success": False,
                "error": "Empty file received. Please upload or capture a photo of the prescription."
            }, status_code=400)

        result = scan_prescription_with_gemini(image_bytes, content_type)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({
            "success": False,
            "error": f"Prescription scanning error: {str(e)}. Please try again or use manual form below."
        }, status_code=500)

@router.post("/confirm-batch")
async def confirm_batch_medicines(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        raise HTTPException(status_code=404, detail="Care circle not found")

    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines") and not permissions.get("is_owner") and user.role != "elder":
        raise HTTPException(status_code=403, detail="Permission denied. You do not have permission to edit medicines.")

    raw_medicines = []
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
        raw_medicines = payload.get("medicines", [])
    else:
        form = await request.form()
        raw_json = form.get("medicines_json")
        if raw_json:
            try:
                raw_medicines = json.loads(raw_json)
            except Exception:
                pass

    if not raw_medicines:
        raise HTTPException(status_code=400, detail="No medicines provided for confirmation.")

    time_mapping = {
        "morning": "08:00",
        "afternoon": "14:00",
        "evening": "18:00",
        "night": "21:00"
    }

    saved_medicines = []
    today = date.today()

    for item in raw_medicines:
        name = str(item.get("name", "")).strip()
        dosage = str(item.get("dosage", "")).strip()
        instructions = str(item.get("instructions", "")).strip()
        raw_times = item.get("times", [])
        raw_duration = item.get("duration_days", 30)

        if not name or name.lower() == "unclear":
            name = "Prescribed Medication"

        mapped_times = []
        if isinstance(raw_times, str):
            raw_times = [t.strip().lower() for t in raw_times.replace(",", " ").split() if t.strip()]

        for t in raw_times:
            clean_t = str(t).strip().lower()
            if clean_t in time_mapping:
                mapped_times.append(time_mapping[clean_t])
            elif ":" in clean_t:
                mapped_times.append(clean_t)

        if not mapped_times:
            mapped_times = ["08:00"]
        mapped_times = sorted(list(set(mapped_times)))

        try:
            duration_days = int(raw_duration)
        except (ValueError, TypeError):
            duration_days = 30

        end_date = today + timedelta(days=duration_days) if duration_days > 0 else None
        days_list = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

        med = Medicine(
            circle_id=circle.id,
            name=name,
            dosage=dosage if dosage else "As prescribed",
            instructions=instructions if instructions else "Take as directed by doctor",
            times=json.dumps(mapped_times),
            days=json.dumps(days_list),
            start_date=today,
            end_date=end_date
        )
        db.add(med)
        db.commit()
        db.refresh(med)
        saved_medicines.append(med)

        # Generate DoseLog records for today
        for t_str in mapped_times:
            try:
                parts = t_str.split(":")
                h, m = int(parts[0]), int(parts[1])
                sched = datetime.combine(today, time(h, m))
                db.add(DoseLog(
                    medicine_id=med.id,
                    scheduled_at=sched,
                    status="pending"
                ))
            except Exception:
                pass
        db.commit()

    log_activity(
        db,
        circle.id,
        user.id,
        f"{user.name} confirmed and added {len(saved_medicines)} medicines via Gemini prescription scan: {', '.join([m.name for m in saved_medicines])}"
    )

    notify_circle(
        db,
        circle.id,
        notif_type="dose",
        message=f"{user.name} added {len(saved_medicines)} prescribed medications to the schedule.",
        require_perm="can_receive_alerts"
    )

    return JSONResponse({
        "status": "success",
        "saved_count": len(saved_medicines),
        "message": f"Successfully saved {len(saved_medicines)} medicines to schedule.",
        "redirect_url": f"/medicines?success=Successfully+saved+{len(saved_medicines)}+prescribed+medicines+to+schedule"
    })

@router.post("/add")
def medicine_add_post(
    name: str = Form(...),
    dosage: str = Form(...),
    instructions: str = Form(None),
    times_raw: str = Form(...),  # e.g. "08:00, 14:00"
    days_raw: str = Form("Mon, Tue, Wed, Thu, Fri, Sat, Sun"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines"):
        return RedirectResponse(url="/medicines?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    times = [t.strip() for t in times_raw.split(",") if t.strip()]
    days = [d.strip() for d in days_raw.split(",") if d.strip()]

    med = Medicine(
        circle_id=circle.id,
        name=name.strip(),
        dosage=dosage.strip(),
        instructions=instructions.strip() if instructions else "",
        times=json.dumps(times),
        days=json.dumps(days),
        start_date=date.today()
    )
    db.add(med)
    db.commit()
    db.refresh(med)

    # Generate dose log for today
    today = date.today()
    for t_str in times:
        try:
            parts = t_str.split(":")
            h, m = int(parts[0]), int(parts[1])
            sched = datetime.combine(today, time(h, m))
            db.add(DoseLog(
                medicine_id=med.id,
                scheduled_at=sched,
                status="pending"
            ))
        except Exception:
            pass
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} added new medicine: {med.name} ({med.dosage})")
    notify_circle(db, circle.id, notif_type="dose", message=f"New medicine added: {med.name} ({med.dosage})", require_perm="can_receive_alerts")

    return RedirectResponse(url="/medicines?success=Medicine+added+successfully", status_code=status.HTTP_302_FOUND)

@router.get("/edit/{med_id}", response_class=HTMLResponse)
def medicine_edit_form(
    med_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines"):
        return RedirectResponse(url="/medicines?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    med = db.query(Medicine).filter(Medicine.id == med_id, Medicine.circle_id == circle.id).first()
    if not med:
        return RedirectResponse(url="/medicines", status_code=status.HTTP_302_FOUND)

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    times_str = ", ".join(med.get_times_list())
    days_str = ", ".join(med.get_days_list())

    return templates.TemplateResponse("medicine_form.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "permissions": permissions,
        "medicine": med,
        "times_str": times_str,
        "days_str": days_str,
        "action": "edit",
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/edit/{med_id}")
def medicine_edit_post(
    med_id: int,
    name: str = Form(...),
    dosage: str = Form(...),
    instructions: str = Form(None),
    times_raw: str = Form(...),
    days_raw: str = Form("Mon, Tue, Wed, Thu, Fri, Sat, Sun"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines"):
        return RedirectResponse(url="/medicines?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    med = db.query(Medicine).filter(Medicine.id == med_id, Medicine.circle_id == circle.id).first()
    if not med:
        return RedirectResponse(url="/medicines", status_code=status.HTTP_302_FOUND)

    times = [t.strip() for t in times_raw.split(",") if t.strip()]
    days = [d.strip() for d in days_raw.split(",") if d.strip()]

    med.name = name.strip()
    med.dosage = dosage.strip()
    med.instructions = instructions.strip() if instructions else ""
    med.times = json.dumps(times)
    med.days = json.dumps(days)
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} updated medicine details for {med.name}")
    return RedirectResponse(url="/medicines?success=Medicine+updated", status_code=status.HTTP_302_FOUND)

@router.post("/delete/{med_id}")
def medicine_delete(
    med_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_medicines"):
        return RedirectResponse(url="/medicines?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    med = db.query(Medicine).filter(Medicine.id == med_id, Medicine.circle_id == circle.id).first()
    if med:
        name = med.name
        db.delete(med)
        db.commit()
        log_activity(db, circle.id, user.id, f"{user.name} removed medicine: {name}")

    return RedirectResponse(url="/medicines?success=Medicine+removed", status_code=status.HTTP_302_FOUND)

@router.post("/dose/{dose_id}/take")
def dose_take(
    dose_id: int,
    redirect_to: str = Form("/dashboard"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    dose = db.query(DoseLog).filter(DoseLog.id == dose_id).first()
    if not dose:
        return RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)

    dose.status = "taken"
    dose.confirmed_at = datetime.now()
    db.commit()

    med = dose.medicine
    circle_id = med.circle_id
    log_activity(db, circle_id, user.id, f"{user.name} confirmed dose: {med.name} ({med.dosage}) taken")
    notify_circle(db, circle_id, notif_type="dose", message=f"Dose Confirmed: {med.name} ({med.dosage}) marked taken by {user.name} at {datetime.now().strftime('%I:%M %p')}.", exclude_user_id=user.id)

    return RedirectResponse(url=f"{redirect_to}?success=Dose+marked+as+taken", status_code=status.HTTP_302_FOUND)

@router.post("/dose/{dose_id}/undo")
def dose_undo(
    dose_id: int,
    redirect_to: str = Form("/dashboard"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    dose = db.query(DoseLog).filter(DoseLog.id == dose_id).first()
    if dose:
        dose.status = "pending"
        dose.confirmed_at = None
        db.commit()
        med = dose.medicine
        log_activity(db, med.circle_id, user.id, f"{user.name} reverted {med.name} dose back to pending")

    return RedirectResponse(url=f"{redirect_to}?info=Dose+status+reverted", status_code=status.HTTP_302_FOUND)
