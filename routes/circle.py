import random
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from template_config import templates
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import CareCircle, Membership, User, ActivityLog, Notification
from services.auth_service import get_current_user
from services.notification_service import (
    get_user_circle, get_user_permissions, log_activity, notify_circle, create_notification
)

router = APIRouter(prefix="/circle", tags=["circle"])

@router.get("", response_class=HTMLResponse)
def circle_detail(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    # Check if user itself is in pending status
    if user.role != "elder":
        current_membership = db.query(Membership).filter(
            Membership.circle_id == circle.id,
            Membership.user_id == user.id
        ).first()
        if current_membership and current_membership.status == "pending":
            return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    permissions = get_user_permissions(db, user, circle.id)
    members = db.query(Membership).options(joinedload(Membership.user)).filter(
        Membership.circle_id == circle.id,
        Membership.status == "approved"
    ).all()
    pending_members = db.query(Membership).options(joinedload(Membership.user)).filter(
        Membership.circle_id == circle.id,
        Membership.status == "pending"
    ).all()
    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("circle.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "members": members,
        "pending_members": pending_members,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })

@router.post("/join")
def join_circle(
    request: Request,
    passcode: str = Form(...),
    relationship: str = Form("Family"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = db.query(CareCircle).filter(CareCircle.passcode == passcode.strip()).first()
    if not circle:
        return RedirectResponse(url="/circle?error=Invalid+circle+passcode", status_code=status.HTTP_302_FOUND)

    existing = db.query(Membership).filter(
        Membership.circle_id == circle.id,
        Membership.user_id == user.id
    ).first()

    rel = relationship.strip() or "Family"
    if not existing:
        mem = Membership(
            circle_id=circle.id,
            user_id=user.id,
            relationship=rel,
            can_view_health=False,
            can_edit_medicines=False,
            can_edit_appointments=False,
            can_receive_alerts=False,
            can_view_location=False,
            can_manage_access=False,
            status="pending"
        )
        db.add(mem)
        db.commit()
        log_activity(db, circle.id, user.id, f"{user.name} requested to join Care Circle as {rel}")
        if circle.elder_id:
            create_notification(
                db,
                circle.elder_id,
                "family",
                f"{user.name} requested to join your Care Circle as {rel}. Please review and approve."
            )
    elif existing.status == "approved":
        return RedirectResponse(url="/circle?error=You+are+already+an+approved+member", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

@router.post("/member/{mem_id}/approve")
def approve_member(
    mem_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    mem = db.query(Membership).filter(Membership.id == mem_id).first()
    if not mem:
        return RedirectResponse(url="/dashboard?error=Member+not+found", status_code=status.HTTP_302_FOUND)

    circle = mem.circle
    permissions = get_user_permissions(db, user, circle.id)
    if not (user.id == circle.elder_id or user.role == "elder" or permissions.get("is_owner")):
        return RedirectResponse(url="/dashboard?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    mem.status = "approved"
    # Minimal default permissions
    mem.can_view_health = True
    mem.can_receive_alerts = True
    mem.can_edit_medicines = False
    mem.can_edit_appointments = False
    mem.can_view_location = False
    mem.can_manage_access = False
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} approved {mem.user.name} ({mem.relationship}) into the Care Circle")
    create_notification(
        db,
        mem.user_id,
        "family",
        f"Your request to join {circle.elder.name}'s Care Circle has been approved!"
    )

    referer = request.headers.get("referer", "/dashboard")
    return RedirectResponse(url=f"{referer}?success=Approved+{mem.user.name}+into+the+care+circle", status_code=status.HTTP_302_FOUND)

@router.post("/member/{mem_id}/decline")
def decline_member(
    mem_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    mem = db.query(Membership).filter(Membership.id == mem_id).first()
    if not mem:
        return RedirectResponse(url="/dashboard?error=Member+not+found", status_code=status.HTTP_302_FOUND)

    circle = mem.circle
    permissions = get_user_permissions(db, user, circle.id)
    if not (user.id == circle.elder_id or user.role == "elder" or permissions.get("is_owner")):
        return RedirectResponse(url="/dashboard?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    name = mem.user.name
    log_activity(db, circle.id, user.id, f"{user.name} declined join request from {name}")
    create_notification(
        db,
        mem.user_id,
        "family",
        f"Your request to join {circle.elder.name}'s Care Circle was declined."
    )
    db.delete(mem)
    db.commit()

    referer = request.headers.get("referer", "/dashboard")
    return RedirectResponse(url=f"{referer}?success=Declined+request+from+{name}", status_code=status.HTTP_302_FOUND)

from pydantic import BaseModel

class PermissionToggle(BaseModel):
    permission: str
    value: bool

@router.post("/member/{mem_id}/toggle-permission")
def toggle_permission(
    mem_id: int,
    payload: PermissionToggle,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    mem = db.query(Membership).filter(Membership.id == mem_id).first()
    if not mem:
        raise HTTPException(status_code=404, detail="Member not found")

    circle = mem.circle
    permissions = get_user_permissions(db, user, circle.id)
    if not (user.id == circle.elder_id or user.role == "elder" or permissions.get("is_owner")):
        raise HTTPException(status_code=403, detail="Permission denied. Only elder can alter access.")

    perm_name = payload.permission
    new_value = payload.value

    valid_perms = {
        "can_view_health",
        "can_edit_medicines",
        "can_edit_appointments",
        "can_receive_alerts",
        "can_view_location",
        "can_manage_access"
    }

    if perm_name not in valid_perms:
        raise HTTPException(status_code=400, detail=f"Invalid permission: {perm_name}")

    setattr(mem, perm_name, new_value)
    db.commit()

    perm_labels = {
        "can_view_health": "View Health",
        "can_edit_medicines": "Edit Medicines",
        "can_edit_appointments": "Edit Appointments",
        "can_receive_alerts": "Receive Alerts",
        "can_view_location": "View Location",
        "can_manage_access": "Manage Access"
    }
    label = perm_labels.get(perm_name, perm_name)
    action_desc = f"{user.name} {'granted' if new_value else 'revoked'} '{label}' permission for {mem.user.name}"
    log_activity(db, circle.id, user.id, action_desc)

    return JSONResponse({
        "status": "success",
        "member_id": mem.id,
        "permission": perm_name,
        "value": getattr(mem, perm_name),
        "message": action_desc
    })

@router.post("/regenerate-passcode")
def regenerate_passcode(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    permissions = get_user_permissions(db, user, circle.id)
    if not (user.id == circle.elder_id or user.role == "elder" or permissions.get("is_owner")):
        return RedirectResponse(url="/circle?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    new_code = str(random.randint(100000, 999999))
    circle.passcode = new_code
    db.commit()

    log_activity(db, circle.id, user.id, f"{user.name} regenerated the Care Passcode to {new_code}")
    referer = request.headers.get("referer", "/circle")
    return RedirectResponse(url=f"{referer}?success=Care+Passcode+regenerated:+{new_code}", status_code=status.HTTP_302_FOUND)

@router.post("/member/{mem_id}/update")
def update_membership(
    mem_id: int,
    relationship: str = Form(...),
    can_view_health: bool = Form(False),
    can_edit_medicines: bool = Form(False),
    can_edit_appointments: bool = Form(False),
    can_receive_alerts: bool = Form(False),
    can_view_location: bool = Form(False),
    can_manage_access: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_manage_access") and not permissions.get("is_owner"):
        return RedirectResponse(url="/circle?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    mem = db.query(Membership).filter(Membership.id == mem_id, Membership.circle_id == circle.id).first()
    if mem:
        mem.relationship = relationship
        mem.can_view_health = can_view_health
        mem.can_edit_medicines = can_edit_medicines
        mem.can_edit_appointments = can_edit_appointments
        mem.can_receive_alerts = can_receive_alerts
        mem.can_view_location = can_view_location
        mem.can_manage_access = can_manage_access
        db.commit()
        log_activity(db, circle.id, user.id, f"Permissions updated for member {mem.user.name}")

    return RedirectResponse(url="/circle?success=Permissions+updated", status_code=status.HTTP_302_FOUND)

@router.post("/member/{mem_id}/remove")
def remove_member(
    mem_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    permissions = get_user_permissions(db, user, circle.id)
    if not permissions.get("can_manage_access") and not permissions.get("is_owner"):
        return RedirectResponse(url="/circle?error=Permission+denied", status_code=status.HTTP_302_FOUND)

    mem = db.query(Membership).filter(Membership.id == mem_id, Membership.circle_id == circle.id).first()
    if mem:
        name = mem.user.name
        db.delete(mem)
        db.commit()
        log_activity(db, circle.id, user.id, f"Removed member {name} from care circle")

    return RedirectResponse(url="/circle?success=Member+removed", status_code=status.HTTP_302_FOUND)

@router.get("/activity", response_class=HTMLResponse)
def activity_timeline(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = get_user_circle(db, user)
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    permissions = get_user_permissions(db, user, circle.id)
    activities = db.query(ActivityLog).filter(
        ActivityLog.circle_id == circle.id
    ).order_by(ActivityLog.timestamp.desc()).limit(50).all()

    demo_users = db.query(User).all()
    unread_notifs = db.query(Notification).filter(Notification.user_id == user.id, Notification.is_read == False).count()

    return templates.TemplateResponse("activity.html", {
        "request": request,
        "user": user,
        "circle": circle,
        "elder": circle.elder,
        "permissions": permissions,
        "activities": activities,
        "demo_users": demo_users,
        "unread_notifs": unread_notifs
    })
