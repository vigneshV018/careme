from datetime import datetime
from sqlalchemy.orm import Session
from models import Notification, ActivityLog, CareCircle, Membership, User

def create_notification(db: Session, user_id: int, notif_type: str, message: str) -> Notification:
    notif = Notification(
        user_id=user_id,
        type=notif_type,
        message=message,
        created_at=datetime.utcnow(),
        is_read=False
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif

def notify_circle(
    db: Session,
    circle_id: int,
    notif_type: str,
    message: str,
    require_perm: str = None,
    exclude_user_id: int = None
):
    circle = db.query(CareCircle).filter(CareCircle.id == circle_id).first()
    if not circle:
        return

    # Notify elder if not excluded
    if circle.elder_id and circle.elder_id != exclude_user_id:
        create_notification(db, circle.elder_id, notif_type, message)

    # Notify approved members
    memberships = db.query(Membership).filter(
        Membership.circle_id == circle_id,
        Membership.status == "approved"
    ).all()

    for mem in memberships:
        if mem.user_id == exclude_user_id:
            continue
        if require_perm:
            perm_val = getattr(mem, require_perm, False)
            if not perm_val:
                continue
        create_notification(db, mem.user_id, notif_type, message)

def log_activity(db: Session, circle_id: int, user_id: int, action: str) -> ActivityLog:
    log_entry = ActivityLog(
        circle_id=circle_id,
        user_id=user_id,
        action=action,
        timestamp=datetime.utcnow()
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    return log_entry

def get_user_membership(db: Session, user: User, circle_id: int = None) -> Membership | None:
    query = db.query(Membership).filter(Membership.user_id == user.id)
    if circle_id:
        query = query.filter(Membership.circle_id == circle_id)
    return query.first()

def get_user_circle(db: Session, user: User) -> CareCircle | None:
    if user.role == "elder":
        circle = db.query(CareCircle).filter(CareCircle.elder_id == user.id).first()
        if circle:
            return circle
    # Check approved memberships first
    membership = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.status == "approved"
    ).first()
    if membership:
        return membership.circle
    # Check pending memberships
    pending = db.query(Membership).filter(
        Membership.user_id == user.id,
        Membership.status == "pending"
    ).first()
    if pending:
        return pending.circle
    # If elder without a circle, find any
    if user.role == "elder":
        circle = db.query(CareCircle).first()
        return circle
    return None

def get_user_permissions(db: Session, user: User, circle_id: int) -> dict:
    circle = db.query(CareCircle).filter(CareCircle.id == circle_id).first()
    if not circle:
        return {
            "can_view_health": False,
            "can_edit_medicines": False,
            "can_edit_appointments": False,
            "can_receive_alerts": False,
            "can_view_location": False,
            "can_manage_access": False,
            "is_owner": False
        }

    # Elder owns the circle
    if circle.elder_id == user.id:
        return {
            "can_view_health": True,
            "can_edit_medicines": True,
            "can_edit_appointments": True,
            "can_receive_alerts": True,
            "can_view_location": True,
            "can_manage_access": True,
            "is_owner": True
        }

    membership = db.query(Membership).filter(
        Membership.circle_id == circle_id,
        Membership.user_id == user.id,
        Membership.status == "approved"
    ).first()

    if not membership:
        return {
            "can_view_health": False,
            "can_edit_medicines": False,
            "can_edit_appointments": False,
            "can_receive_alerts": False,
            "can_view_location": False,
            "can_manage_access": False,
            "is_owner": False
        }

    return {
        "can_view_health": membership.can_view_health,
        "can_edit_medicines": membership.can_edit_medicines,
        "can_edit_appointments": membership.can_edit_appointments,
        "can_receive_alerts": membership.can_receive_alerts,
        "can_view_location": membership.can_view_location,
        "can_manage_access": membership.can_manage_access,
        "is_owner": False
    }

