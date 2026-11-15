from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from template_config import templates
from sqlalchemy.orm import Session
from database import get_db
from models import EmergencyAlert, CareCircle, User, Notification, Membership
from services.auth_service import get_current_user
from services.email_service import send_email
from services.notification_service import (
    get_user_circle, get_user_permissions, log_activity, notify_circle
)

router = APIRouter(prefix="/alerts", tags=["alerts"])

@router.get("", response_class=HTMLResponse)
def alerts_page(
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

    if user.role != "elder" and not permissions.get("can_receive_alerts"):
        return templates.TemplateResponse("restricted_access.html", {
            "request": request,
            "user": user,
            "circle": circle,
            "elder": circle.elder,
            "feature": "Emergency Alerts",
            "message": f"{circle.elder.name} has not shared emergency alerts with you.",
            "demo_users": demo_users,
            "unread_notifs": unread_notifs
        })

    alerts = db.query(EmergencyAlert).filter(
        EmergencyAlert.circle_id == circle.id
    ).order_by(EmergencyAlert.created_at.desc()).all()

    active_alert = next((a for a in alerts if not a.acknowledged_at), None)

    return templates.TemplateResponse("alerts.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "alerts": alerts,
        "active_alert": active_alert,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/sos")
def trigger_sos(
    request: Request,
    lat: float = Form(11.0168),  # Default Coimbatore coords
    lng: float = Form(76.9558),
    redirect_to: str = Form("/dashboard"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    alert = EmergencyAlert(
        circle_id=circle.id,
        triggered_by=user.id,
        created_at=datetime.utcnow(),
        lat=lat,
        lng=lng
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    # Activity and notifications
    log_activity(db, circle.id, user.id, f"CRITICAL: Emergency SOS activated by {user.name}")
    msg = f"EMERGENCY ALERT: {user.name} triggered SOS at {datetime.now().strftime('%I:%M %p')}. Location: {user.city or 'Coimbatore'} (GPS: {lat}, {lng}). Immediate attention needed!"
    notify_circle(db, circle.id, notif_type="sos", message=msg, require_perm="can_receive_alerts")

    # Real Email Dispatch to authorized members and elder (Requirement 7)
    sos_time_str = datetime.now().strftime("%I:%M %p")
    alert_recipients = []
    if circle.elder and circle.elder.email:
        alert_recipients.append((circle.elder.name, circle.elder.email, circle.elder.id, "Elder"))

    alert_members = db.query(Membership).filter(
        Membership.circle_id == circle.id,
        Membership.status == "approved",
        Membership.can_receive_alerts == True
    ).all()
    for m in alert_members:
        if m.user and m.user.email and m.user.id != user.id:
            alert_recipients.append((m.user.name, m.user.email, m.user.id, m.relationship))

    for r_name, r_email, r_uid, r_rel in alert_recipients:
        send_email(
            to_email=r_email,
            subject=f"EMERGENCY ALERT: {user.name} triggered SOS",
            headline=f"EMERGENCY SOS: {user.name} Needs Immediate Assistance",
            message=f"Urgent: {user.name} triggered an Emergency SOS alert at {sos_time_str}. Location: {user.city or 'Coimbatore'} (GPS: {lat}, {lng}). Immediate attention is needed!",
            details={
                "Triggered By": user.name,
                "Time": sos_time_str,
                "Location": f"{user.city or 'Coimbatore'} (GPS: {lat}, {lng})",
                "Status": "ACTIVE EMERGENCY SOS",
                "Emergency Response": "Please check in or dial 112 if immediate medical assistance is required."
            },
            badge_text="Emergency SOS",
            badge_color="#DC2626",
            action_url="http://127.0.0.1:8000/alerts",
            action_text="View SOS Alert & Acknowledge",
            user_id=r_uid,
            notif_type="sos",
            db=db,
            sync=False
        )

    # If AJAX request, return JSON
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"status": "success", "alert_id": alert.id})

    return RedirectResponse(url=f"{redirect_to}?sos_active=1", status_code=status.HTTP_302_FOUND)

@router.post("/{alert_id}/acknowledge")
def acknowledge_sos(
    alert_id: int,
    redirect_to: str = Form("/dashboard"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    alert = db.query(EmergencyAlert).filter(EmergencyAlert.id == alert_id, EmergencyAlert.circle_id == circle.id).first()
    if alert and not alert.acknowledged_at:
        alert.acknowledged_by = user.id
        alert.acknowledged_at = datetime.utcnow()
        db.commit()

        log_activity(db, circle.id, user.id, f"Emergency Alert #{alert.id} acknowledged by {user.name}")
        msg = f"Alert Update: {user.name} ({user.role}) has acknowledged the Emergency SOS and is attending to Lakshmi."
        notify_circle(db, circle.id, notif_type="sos", message=msg)

    return RedirectResponse(url=f"{redirect_to}?success=Alert+acknowledged", status_code=status.HTTP_302_FOUND)
