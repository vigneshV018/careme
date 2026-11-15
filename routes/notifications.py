from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from template_config import templates
from sqlalchemy.orm import Session
from database import get_db
from models import Notification, User, CareCircle
from services.auth_service import get_current_user
from services.notification_service import get_user_circle, get_user_permissions

router = APIRouter(prefix="/notifications", tags=["notifications"])

@router.get("", response_class=HTMLResponse)
def notifications_page(
    request: Request,
    filter_type: str = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    query = db.query(Notification).filter(Notification.user_id == user.id)
    if filter_type and filter_type != "all":
        query = query.filter(Notification.type == filter_type)
    
    notifications = query.order_by(Notification.created_at.desc()).all()
    demo_users = db.query(User).all()
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id) if circle else {}
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("notifications.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder if circle else None,
        "permissions": permissions,
        "notifications": notifications,
        "current_filter": filter_type or "all",
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/read-all")
def mark_all_read(
    redirect_to: str = Form("/notifications"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)

@router.post("/{notif_id}/read")
def mark_one_read(
    notif_id: int,
    redirect_to: str = Form("/notifications"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    notif = db.query(Notification).filter(Notification.id == notif_id, Notification.user_id == user.id).first()
    if notif:
        notif.is_read = True
        db.commit()
    return RedirectResponse(url=redirect_to, status_code=status.HTTP_302_FOUND)
