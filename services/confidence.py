"""
Remote Care Confidence Engine
Computes a 0-100 'Remote Care Confidence' score in pure Python (no AI),
evaluating medication adherence, streak continuity, time-of-day patterns,
recency of activity, and healthcare touchpoints.

Tone guideline: Respects elder independence, encourages supportive connection,
never sounds alarming or clinical.
"""

import time
import logging
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session
from models import DoseLog, Medicine, CareCircle, Appointment, ActivityLog, EmergencyAlert
from config import CONFIDENCE_CACHE_SECONDS

logger = logging.getLogger("careme.confidence")

# In-memory cache for confidence scores: {circle_id: (cached_at_timestamp, cached_result)}
_confidence_cache: Dict[int, Tuple[float, Dict[str, Any]]] = {}

def clear_confidence_cache(circle_id: Optional[int] = None) -> None:
    """Clears the confidence score cache for a specific circle or all circles."""
    if circle_id is not None:
        _confidence_cache.pop(circle_id, None)
    else:
        _confidence_cache.clear()

def compute_remote_care_confidence(db: Session, circle_id: int, use_cache: bool = True) -> Dict[str, Any]:
    """
    Computes a 0-100 Remote Care Confidence score from 7-day adherence,
    streak continuity, time-of-day patterns, hours since last activity, and upcoming appointments.
    Caches results for 60 seconds per care circle for high-performance dashboard rendering.
    """
    now_ts = time.time()
    if use_cache and circle_id in _confidence_cache:
        cached_ts, cached_data = _confidence_cache[circle_id]
        if now_ts - cached_ts < CONFIDENCE_CACHE_SECONDS:
            return cached_data

    circle = db.query(CareCircle).filter(CareCircle.id == circle_id).first()
    elder_name = circle.elder.name if (circle and circle.elder) else "Your loved one"

    now = datetime.now()
    seven_days_ago = now - timedelta(days=7)

    # 1. 7-day dose logs
    logs_7d = db.query(DoseLog).join(Medicine).filter(
        Medicine.circle_id == circle_id,
        DoseLog.scheduled_at >= seven_days_ago,
        DoseLog.scheduled_at <= now
    ).order_by(DoseLog.scheduled_at.desc()).all()

    taken_count = sum(1 for l in logs_7d if l.status == "taken")
    missed_count = sum(1 for l in logs_7d if l.status == "not_confirmed")
    pending_count = sum(1 for l in logs_7d if l.status == "pending")
    due_count = taken_count + missed_count

    if due_count > 0:
        adherence_pct = round((taken_count / due_count) * 100, 1)
    else:
        adherence_pct = 100.0

    # 2. Consecutive unconfirmed doses (starting from latest backwards)
    consecutive_unconfirmed = 0
    for l in logs_7d:
        if l.status == "not_confirmed":
            consecutive_unconfirmed += 1
        elif l.status == "taken":
            break  # Streak broken by confirmed dose

    # 3. Repeated pattern by time of day
    morning_missed = 0   # 05:00 - 11:59
    afternoon_missed = 0 # 12:00 - 16:59
    evening_missed = 0   # 17:00 - 23:59

    for l in logs_7d:
        if l.status == "not_confirmed":
            h = l.scheduled_at.hour
            if 5 <= h < 12:
                morning_missed += 1
            elif 12 <= h < 17:
                afternoon_missed += 1
            else:
                evening_missed += 1

    pattern_detected = None
    if morning_missed >= 2 and morning_missed >= (afternoon_missed + evening_missed):
        pattern_detected = "morning"
    elif afternoon_missed >= 2 and afternoon_missed >= (morning_missed + evening_missed):
        pattern_detected = "afternoon"
    elif evening_missed >= 2 and evening_missed >= (morning_missed + afternoon_missed):
        pattern_detected = "evening"

    # 4. Hours since last activity
    latest_activity = db.query(ActivityLog).filter(
        ActivityLog.circle_id == circle_id
    ).order_by(ActivityLog.timestamp.desc()).first()

    latest_taken_dose = db.query(DoseLog).join(Medicine).filter(
        Medicine.circle_id == circle_id,
        DoseLog.status == "taken",
        DoseLog.confirmed_at != None
    ).order_by(DoseLog.confirmed_at.desc()).first()

    timestamps = []
    if latest_activity and latest_activity.timestamp:
        timestamps.append(latest_activity.timestamp)
    if latest_taken_dose and latest_taken_dose.confirmed_at:
        timestamps.append(latest_taken_dose.confirmed_at)

    if timestamps:
        most_recent_time = max(timestamps)
        hours_since_activity = max(0.1, round((now - most_recent_time).total_seconds() / 3600.0, 1))
    else:
        hours_since_activity = 6.0  # Safe default

    # 5. Upcoming appointments
    next_appointment = db.query(Appointment).filter(
        Appointment.circle_id == circle_id,
        Appointment.datetime >= now
    ).order_by(Appointment.datetime.asc()).first()

    # -------------------------------------------------------------
    # SCORING ALGORITHM (0 - 100)
    # Component 1: 7-day confirmation rate (up to 40 pts)
    # Component 2: Consecutive unconfirmed doses (up to 25 pts)
    # Component 3: Time of day pattern (up to 15 pts)
    # Component 4: Hours since last activity (up to 10 pts)
    # Component 5: Upcoming appointments (up to 10 pts)
    # -------------------------------------------------------------
    reasons: List[str] = []

    # Component 1 (40 pts)
    if adherence_pct >= 95:
        p1 = 40
        reasons.append(f"7-day medication confirmation rate is excellent at {adherence_pct}% ({taken_count} of {due_count} doses confirmed).")
    elif adherence_pct >= 85:
        p1 = 34
        reasons.append(f"7-day medication routine is steady at {adherence_pct}% ({taken_count} of {due_count} doses confirmed).")
    elif adherence_pct >= 75:
        p1 = 26
        reasons.append(f"7-day medication confirmation rate is {adherence_pct}% ({missed_count} unconfirmed doses this week).")
    elif adherence_pct >= 60:
        p1 = 18
        reasons.append(f"7-day confirmation rate is {adherence_pct}% with {missed_count} doses awaiting confirmation.")
    else:
        p1 = 10
        reasons.append(f"7-day confirmation rate is currently {adherence_pct}%.")

    # Component 2 (25 pts)
    if consecutive_unconfirmed == 0:
        p2 = 25
        reasons.append("Recent doses have been confirmed on time without back-to-back misses.")
    elif consecutive_unconfirmed == 1:
        p2 = 18
        reasons.append("One recent dose is currently unconfirmed.")
    elif consecutive_unconfirmed == 2:
        p2 = 10
        reasons.append("Two consecutive doses were not confirmed.")
    else:
        p2 = 2
        reasons.append(f"{consecutive_unconfirmed} consecutive doses are unconfirmed.")

    # Component 3 (15 pts)
    if missed_count == 0:
        p3 = 15
        reasons.append("No repeating missed dose patterns detected.")
    elif pattern_detected == "morning":
        p3 = 6
        reasons.append(f"Unconfirmed doses show a morning pattern ({morning_missed} missed between 8:00 AM and 10:00 AM).")
    elif pattern_detected == "afternoon":
        p3 = 6
        reasons.append(f"Unconfirmed doses show an afternoon pattern ({afternoon_missed} missed between 12:00 PM and 5:00 PM).")
    elif pattern_detected == "evening":
        p3 = 6
        reasons.append(f"Unconfirmed doses show an evening pattern ({evening_missed} missed after 5:00 PM).")
    else:
        p3 = 11
        reasons.append("Occasional isolated unconfirmed doses with no repeating time-of-day pattern.")

    # Component 4 (10 pts)
    if hours_since_activity <= 4:
        p4 = 10
        reasons.append(f"Active in the care circle within the last {int(hours_since_activity)} hour{'s' if int(hours_since_activity) != 1 else ''}.")
    elif hours_since_activity <= 12:
        p4 = 8
        reasons.append(f"Last recorded circle activity was {int(hours_since_activity)} hours ago.")
    elif hours_since_activity <= 24:
        p4 = 5
        reasons.append(f"Last circle activity was about {int(hours_since_activity)} hours ago.")
    else:
        p4 = 2
        reasons.append("No recorded circle activity in over 24 hours.")

    # Component 5 (10 pts)
    if next_appointment:
        delta_hours = (next_appointment.datetime - now).total_seconds() / 3600.0
        if delta_hours <= 48:
            p5 = 10
            reasons.append(f"Upcoming doctor visit scheduled with {next_appointment.doctor} ({next_appointment.specialty}) at {next_appointment.hospital} within 48 hours.")
        elif delta_hours <= 168:  # 7 days
            p5 = 8
            reasons.append(f"Doctor visit with {next_appointment.doctor} is planned for this week ({next_appointment.datetime.strftime('%A, %b %d')}).")
        else:
            p5 = 6
            reasons.append(f"Next medical check-up scheduled for {next_appointment.datetime.strftime('%b %d')}.")
    else:
        p5 = 5
        reasons.append("No upcoming medical appointments scheduled on the calendar.")

    # Calculate total score
    raw_score = p1 + p2 + p3 + p4 + p5
    score = max(0, min(100, raw_score))

    # Determine Label and Tone
    if score >= 85:
        label = "All good"
        color = "emerald"
        tone_message = f"{elder_name} is following her daily routine comfortably. Everything looks consistent and well-paced."
    elif score >= 65:
        label = "Worth a check-in"
        color = "amber"
        tone_message = f"{elder_name} is doing well overall. A casual chat or tea-time check-in would be a thoughtful way to connect and touch base on morning routines."
    else:
        label = "Please reach out"
        color = "orange"
        tone_message = f"A friendly hello or phone check-in today would be wonderful to see how {elder_name} is feeling and catch up on her day."

    result = {
        "score": score,
        "label": label,
        "color": color,
        "reasons": reasons,
        "tone_message": tone_message,
        "elder_name": elder_name,
        "metrics": {
            "adherence_pct": adherence_pct,
            "taken_count": taken_count,
            "missed_count": missed_count,
            "due_count": due_count,
            "consecutive_unconfirmed": consecutive_unconfirmed,
            "pattern_detected": pattern_detected,
            "hours_since_activity": hours_since_activity,
            "next_appointment": {
                "doctor": next_appointment.doctor if next_appointment else None,
                "specialty": next_appointment.specialty if next_appointment else None,
                "hospital": next_appointment.hospital if next_appointment else None,
                "datetime_str": next_appointment.datetime.strftime('%A, %b %d at %I:%M %p') if next_appointment else None
            } if next_appointment else None
        }
    }
    _confidence_cache[circle_id] = (now_ts, result)
    return result

