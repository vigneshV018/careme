from datetime import datetime, date, timedelta
from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from template_config import templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from database import get_db
from models import (
    User, CareCircle, Membership, Medicine, DoseLog,
    Appointment, EmergencyAlert, ActivityLog, Notification
)
from services.auth_service import get_current_user, get_current_user_optional
from services.notification_service import get_user_circle, get_user_permissions, get_user_membership
from services.ai_insights import get_circle_adherence_analytics
from services.confidence import compute_remote_care_confidence
from services.gemini_service import generate_weekly_summary

router = APIRouter(tags=["dashboard"])

@router.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Check if non-elder has a membership
    if user.role != "elder":
        membership = get_user_membership(db, user)
        if not membership:
            return templates.TemplateResponse("join_circle.html", {
                "request": request,
                "user": user
            })
        if membership.status == "pending":
            circle = membership.circle
            elder = circle.elder
            unread_notifs = db.query(Notification).filter(
                Notification.user_id == user.id,
                Notification.is_read == False
            ).count()
            return templates.TemplateResponse("pending_approval.html", {
                "request": request,
                "user": user,
                "circle": circle,
                "elder": elder,
                "membership": membership,
                "demo_users": db.query(User).all(),
                "unread_notifs": unread_notifs
            })

    circle = get_user_circle(db, user)
    if not circle:
        if user.role == "elder":
            import random
            circle = CareCircle(elder_id=user.id, passcode=str(random.randint(100000, 999999)))
            db.add(circle)
            db.commit()
            db.refresh(circle)
        else:
            return templates.TemplateResponse("join_circle.html", {
                "request": request,
                "user": user
            })

    permissions = get_user_permissions(db, user, circle.id)
    elder = circle.elder
    demo_users = db.query(User).all()

    # Unread notifications
    unread_notifs = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False
    ).count()

    # Active SOS Alert
    active_sos = db.query(EmergencyAlert).filter(
        EmergencyAlert.circle_id == circle.id,
        EmergencyAlert.acknowledged_at == None
    ).order_by(EmergencyAlert.created_at.desc()).first()

    # Today's dose logs
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_end = datetime.combine(date.today(), datetime.max.time())
    today_doses = db.query(DoseLog).join(Medicine).filter(
        Medicine.circle_id == circle.id,
        DoseLog.scheduled_at >= today_start,
        DoseLog.scheduled_at <= today_end
    ).order_by(DoseLog.scheduled_at).all()

    # Upcoming appointment
    now = datetime.now()
    next_appointment = db.query(Appointment).filter(
        Appointment.circle_id == circle.id,
        Appointment.datetime >= now
    ).order_by(Appointment.datetime.asc()).first()

    # Circle members
    members = db.query(Membership).filter(
        Membership.circle_id == circle.id,
        Membership.status == "approved"
    ).all()

    # Pending requests for elder review
    pending_requests = []
    if user.role == "elder" or permissions.get("can_manage_access") or permissions.get("is_owner"):
        pending_requests = db.query(Membership).filter(
            Membership.circle_id == circle.id,
            Membership.status == "pending"
        ).all()

    # Recent activity
    recent_activities = db.query(ActivityLog).filter(
        ActivityLog.circle_id == circle.id
    ).order_by(ActivityLog.timestamp.desc()).limit(8).all()

    # Analytics for family/caregiver
    analytics = get_circle_adherence_analytics(db, circle.id, days=7)

    # Remote Care Confidence (computed in pure Python)
    confidence = compute_remote_care_confidence(db, circle.id)

    # Plain-language Weekly Summary (Gemini 2.5 Flash with rule-based fallback)
    weekly_summary = None
    if user.role == "elder" or permissions.get("can_view_health"):
        facts = {
            "elder_name": elder.name,
            "adherence_rate": f"{analytics['adherence_pct']}%",
            "doses_taken": analytics["taken"],
            "doses_unconfirmed": analytics["missed"],
            "total_due": analytics["taken"] + analytics["missed"],
            "most_missed_time_of_day": "Morning (8:00 AM – 10:00 AM, typically Metformin)" if analytics["morning"]["missed"] > 0 else "None",
            "confidence_score": confidence["score"],
            "confidence_label": confidence["label"],
            "confidence_reasons": confidence["reasons"],
            "next_appointment": (
                f"{next_appointment.doctor} ({next_appointment.specialty}) at {next_appointment.hospital}, "
                f"{next_appointment.datetime.strftime('%A at %I:%M %p')}"
            ) if next_appointment else "None scheduled"
        }
        weekly_summary = generate_weekly_summary(facts)

    context = {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": elder,
        "permissions": permissions,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs,
        "active_sos": active_sos,
        "today_doses": today_doses,
        "next_appointment": next_appointment,
        "members": members,
        "pending_requests": pending_requests,
        "recent_activities": recent_activities,
        "analytics": analytics,
        "confidence": confidence,
        "weekly_summary": weekly_summary,
        "today_date": date.today().strftime("%A, %B %d, %Y")
    }

    if user.role == "elder":
        return templates.TemplateResponse("elder_dashboard.html", context)
    elif user.role == "caregiver":
        return templates.TemplateResponse("caregiver_dashboard.html", context)
    else:
        return templates.TemplateResponse("family_dashboard.html", context)

@router.get("/location", response_class=HTMLResponse)
def location_page(
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

    if user.role != "elder" and not permissions.get("can_view_location"):
        return templates.TemplateResponse("restricted_access.html", {
            "request": request,
            "user": user,
            "circle": circle,
            "elder": circle.elder,
            "feature": "Live Location",
            "message": f"{circle.elder.name} has not shared location tracking with you.",
            "demo_users": demo_users,
            "unread_notifs": unread_notifs
        })

    return templates.TemplateResponse("location.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.get("/offline", response_class=HTMLResponse)
def offline_page(request: Request):
    return templates.TemplateResponse("offline.html", {"request": request})
