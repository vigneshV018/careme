from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from template_config import templates
from sqlalchemy.orm import Session
from database import get_db
from models import Appointment, CareCircle, User, Notification
from services.auth_service import get_current_user
from services.notification_service import (
    get_user_circle, get_user_permissions, log_activity, notify_circle
)

router = APIRouter(prefix="/appointments", tags=["appointments"])

@router.get("", response_class=HTMLResponse)
def appointments_list(
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
            "feature": "Doctor Appointments",
            "message": f"{circle.elder.name} has not shared appointments with you.",
            "demo_users": demo_users,
            "unread_notifs": unread_notifs
        })

    now = datetime.now()
    
    upcoming = db.query(Appointment).filter(
        Appointment.circle_id == circle.id,
        Appointment.datetime >= now
    ).order_by(Appointment.datetime.asc()).all()

    past = db.query(Appointment).filter(
        Appointment.circle_id == circle.id,
        Appointment.datetime < now
    ).order_by(Appointment.datetime.desc()).all()

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("appointments.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "upcoming": upcoming,
        "past": past,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.get("/add", response_class=HTMLResponse)
def appointment_add_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_appointments"):
        return RedirectResponse(url="/appointments?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("appointment_form.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "permissions": permissions,
        "appointment": None,
        "action": "add",
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/add")
def appointment_add_post(
    doctor: str = Form(...),
    specialty: str = Form(...),
    hospital: str = Form(...),
    address: str = Form(None),
    phone: str = Form(None),
    datetime_str: str = Form(...),  # e.g. "2026-11-16T11:00"
    notes: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_appointments"):
        return RedirectResponse(url="/appointments?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    try:
        dt = datetime.fromisoformat(datetime_str)
    except Exception:
        return RedirectResponse(url="/appointments/add?error=Invalid+date+format", status_code=status.HTTP_302_FOUND)

    appt = Appointment(
        circle_id=circle.id,
        doctor=doctor.strip(),
        specialty=specialty.strip(),
        hospital=hospital.strip(),
        address=address.strip() if address else "",
        phone=phone.strip() if phone else "",
        datetime=dt,
        notes=notes.strip() if notes else ""
    )
    db.add(appt)
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} scheduled appointment with {appt.doctor} ({appt.specialty}) at {appt.hospital}")
    notify_circle(db, circle.id, notif_type="appointment", message=f"New appointment booked: {appt.doctor} at {appt.hospital} on {appt.datetime.strftime('%b %d, %I:%M %p')}.", require_perm="can_receive_alerts")

    return RedirectResponse(url="/appointments?success=Appointment+scheduled", status_code=status.HTTP_302_FOUND)

@router.get("/edit/{appt_id}", response_class=HTMLResponse)
def appointment_edit_form(
    appt_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_appointments"):
        return RedirectResponse(url="/appointments?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.circle_id == circle.id).first()
    if not appt:
        return RedirectResponse(url="/appointments", status_code=status.HTTP_302_FOUND)

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("appointment_form.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "permissions": permissions,
        "appointment": appt,
        "action": "edit",
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/edit/{appt_id}")
def appointment_edit_post(
    appt_id: int,
    doctor: str = Form(...),
    specialty: str = Form(...),
    hospital: str = Form(...),
    address: str = Form(None),
    phone: str = Form(None),
    datetime_str: str = Form(...),
    notes: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_appointments"):
        return RedirectResponse(url="/appointments?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.circle_id == circle.id).first()
    if not appt:
        return RedirectResponse(url="/appointments", status_code=status.HTTP_302_FOUND)

    try:
        dt = datetime.fromisoformat(datetime_str)
    except Exception:
        return RedirectResponse(url=f"/appointments/edit/{appt_id}?error=Invalid+date+format", status_code=status.HTTP_302_FOUND)

    appt.doctor = doctor.strip()
    appt.specialty = specialty.strip()
    appt.hospital = hospital.strip()
    appt.address = address.strip() if address else ""
    appt.phone = phone.strip() if phone else ""
    appt.datetime = dt
    appt.notes = notes.strip() if notes else ""
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} updated appointment with {appt.doctor}")
    return RedirectResponse(url="/appointments?success=Appointment+updated", status_code=status.HTTP_302_FOUND)

@router.post("/delete/{appt_id}")
def appointment_delete(
    appt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_edit_appointments"):
        return RedirectResponse(url="/appointments?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.circle_id == circle.id).first()
    if appt:
        doc = appt.doctor
        db.delete(appt)
        db.commit()
        log_activity(db, circle.id, user.id, f"{user.name} removed appointment with {doc}")

    return RedirectResponse(url="/appointments?success=Appointment+removed", status_code=status.HTTP_302_FOUND)

@router.post("/{appt_id}/accompany")
def accompany_appointment(
    appt_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.circle_id == circle.id).first()
    if appt:
        note_append = f"\n[Accompanying: {user.name} ({user.role}) confirmed attendance]"
        appt.notes = (appt.notes or "") + note_append
        db.commit()
        log_activity(db, circle.id, user.id, f"{user.name} volunteered to accompany Lakshmi to {appt.doctor} appointment")
        notify_circle(db, circle.id, notif_type="appointment", message=f"{user.name} will accompany Lakshmi to Dr. Ramesh at KG Hospital.", require_perm="can_receive_alerts")

    return RedirectResponse(url="/appointments?success=Attendance+confirmed", status_code=status.HTTP_302_FOUND)
