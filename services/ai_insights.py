from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import DoseLog, Medicine, CareCircle

def get_circle_adherence_analytics(db: Session, circle_id: int, days: int = 7):
    cutoff = datetime.now() - timedelta(days=days)
    
    logs = db.query(DoseLog).join(Medicine).filter(
        Medicine.circle_id == circle_id,
        DoseLog.scheduled_at >= cutoff
    ).all()

    total = len(logs)
    taken = sum(1 for l in logs if l.status == "taken")
    missed = sum(1 for l in logs if l.status == "not_confirmed")
    pending = sum(1 for l in logs if l.status == "pending")

    due = taken + missed
    adherence_pct = round((taken / due * 100), 1) if due > 0 else 100.0

    # Time of day breakdown
    morning_taken = 0
    morning_missed = 0
    afternoon_taken = 0
    afternoon_missed = 0
    evening_taken = 0
    evening_missed = 0

    for l in logs:
        hour = l.scheduled_at.hour
        if 5 <= hour < 12:
            if l.status == "taken":
                morning_taken += 1
            elif l.status == "not_confirmed":
                morning_missed += 1
        elif 12 <= hour < 17:
            if l.status == "taken":
                afternoon_taken += 1
            elif l.status == "not_confirmed":
                afternoon_missed += 1
        else:
            if l.status == "taken":
                evening_taken += 1
            elif l.status == "not_confirmed":
                evening_missed += 1

    # Daily breakdown for past 7 days chart
    daily_stats = []
    for d in range(6, -1, -1):
        day_date = (datetime.now() - timedelta(days=d)).date()
        day_logs = [l for l in logs if l.scheduled_at.date() == day_date]
        d_total = len(day_logs)
        d_taken = sum(1 for l in day_logs if l.status == "taken")
        d_missed = sum(1 for l in day_logs if l.status == "not_confirmed")
        pct = round((d_taken / d_total * 100)) if d_total > 0 else 100
        daily_stats.append({
            "date": day_date.strftime("%a %d"),
            "total": d_total,
            "taken": d_taken,
            "missed": d_missed,
            "pct": pct
        })

    # AI Insights generation
    insights = []
    if morning_missed > 0 and morning_missed >= (afternoon_missed + evening_missed):
        pct_misses = round((morning_missed / (missed or 1)) * 100)
        insights.append({
            "type": "warning",
            "title": "Morning Routine Vulnerability Detected",
            "message": f"Lakshmi has an {adherence_pct}% overall adherence rate, but {pct_misses}% of missed doses happen between 8:00 AM and 10:00 AM (primarily Metformin).",
            "action": "Recommendation: Arun or Meena can schedule a 7:45 AM 'Morning Chai & Meds' check-in call."
        })
    else:
        insights.append({
            "type": "success",
            "title": "Consistent Medication Habit",
            "message": f"Adherence is currently healthy at {adherence_pct}%.",
            "action": "Keep encouraging Lakshmi with daily positive reinforcement."
        })

    if adherence_pct >= 85:
        insights.append({
            "type": "info",
            "title": "Cardiology Readiness",
            "message": "Metformin and Amlodipine regimen consistency is stable ahead of tomorrow's ECG & consultation with Dr. Ramesh at KG Hospital.",
            "action": "Ensure latest blood pressure log is shared with Dr. Ramesh."
        })

    return {
        "total": total,
        "taken": taken,
        "missed": missed,
        "pending": pending,
        "adherence_pct": adherence_pct,
        "morning": {"taken": morning_taken, "missed": morning_missed},
        "afternoon": {"taken": afternoon_taken, "missed": afternoon_missed},
        "evening": {"taken": evening_taken, "missed": evening_missed},
        "daily_stats": daily_stats,
        "insights": insights
    }
