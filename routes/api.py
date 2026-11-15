from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import DoseLog, EmergencyAlert, Notification, User, Medicine, CareCircle
from services.auth_service import get_current_user_optional
from services.notification_service import notify_circle, log_activity
from services.ai_insights import get_circle_adherence_analytics

router = APIRouter(prefix="/api", tags=["api"])

@router.get("/health")
def api_health():
    return {"status": "ok", "service": "CareMe"}

@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user_optional)):
    if not user:
        return {"unread": 0}
    count = db.query(Notification).filter(
        Notification.user_id == user.id,
        Notification.is_read == False
    ).count()
    return {"unread": count}

@router.post("/dose/{dose_id}/take")
def api_take_dose(dose_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user_optional)):
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    dose = db.query(DoseLog).filter(DoseLog.id == dose_id).first()
    if not dose:
        raise HTTPException(status_code=404, detail="Dose not found")

    dose.status = "taken"
    dose.confirmed_at = datetime.now()
    db.commit()

    med = dose.medicine
    circle_id = med.circle_id
    log_activity(db, circle_id, user.id, f"{user.name} confirmed dose: {med.name} ({med.dosage}) taken")
    notify_circle(db, circle_id, notif_type="dose", message=f"Dose Confirmed: {med.name} ({med.dosage}) taken at {datetime.now().strftime('%I:%M %p')}.", exclude_user_id=user.id)

    analytics = get_circle_adherence_analytics(db, circle_id, days=7)

    return {
        "status": "success",
        "dose_id": dose.id,
        "confirmed_at": dose.confirmed_at.strftime("%I:%M %p"),
        "adherence_pct": analytics["adherence_pct"],
        "taken_count": analytics["taken"],
        "total_count": analytics["total"]
    }

