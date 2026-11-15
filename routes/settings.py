from fastapi import APIRouter, Request, Response, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from database import get_db
from models import (
    User, CareCircle, Membership, Medicine, DoseLog,
    Appointment, EmergencyAlert, ActivityLog, Notification
)
from services.auth_service import get_current_user, logout_user
from template_config import templates

router = APIRouter(prefix="/settings", tags=["settings"])

@router.get("", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    success: str = None,
    error: str = None
):
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "user": user,
        "success": success,
        "error": error
    })

@router.post("/profile")
def update_profile(
    request: Request,
    name: str = Form(...),
    phone: str = Form(None),
    city: str = Form(None),
    age: int = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user.name = name.strip()
    user.phone = phone.strip() if phone else None
    user.city = city.strip() if city else None
    user.age = age
    db.commit()
    return RedirectResponse(
        url="/settings?success=Profile+updated+successfully",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/delete-account")
def delete_account(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = user.id

    # 1. Delete notifications for user
    db.query(Notification).filter(Notification.user_id == user_id).delete()

    # 2. Delete user's activity logs
    db.query(ActivityLog).filter(ActivityLog.user_id == user_id).delete()

    # 3. If elder, delete entire circle and associated health data
    if user.role == "elder":
        circles = db.query(CareCircle).filter(CareCircle.elder_id == user_id).all()
        for circle in circles:
            # Delete dose logs
            med_ids = [m.id for m in db.query(Medicine).filter(Medicine.circle_id == circle.id).all()]
            if med_ids:
                db.query(DoseLog).filter(DoseLog.medicine_id.in_(med_ids)).delete(synchronize_session=False)
            # Delete medicines
            db.query(Medicine).filter(Medicine.circle_id == circle.id).delete()
            # Delete appointments
            db.query(Appointment).filter(Appointment.circle_id == circle.id).delete()
            # Delete emergency alerts
            db.query(EmergencyAlert).filter(EmergencyAlert.circle_id == circle.id).delete()
            # Delete circle activity logs
            db.query(ActivityLog).filter(ActivityLog.circle_id == circle.id).delete()
            # Delete all memberships in circle
            db.query(Membership).filter(Membership.circle_id == circle.id).delete()
            # Delete circle
            db.delete(circle)

    # 4. Delete user's memberships
    db.query(Membership).filter(Membership.user_id == user_id).delete()

    # 5. Delete the user
    db.delete(user)
    db.commit()

    # Log out user
    redirect = RedirectResponse(
        url="/auth/login?success=Account+and+all+personal+data+have+been+permanently+deleted.",
        status_code=status.HTTP_302_FOUND
    )
    logout_user(redirect)
    return redirect

