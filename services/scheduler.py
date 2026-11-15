import os
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from services.timezone import KOLKATA_TZ, now_kolkata

from sqlalchemy.orm import joinedload
from config import ESCALATE_1_MIN, ESCALATE_2_MIN
from database import SessionLocal
from models import DoseLog, Appointment, Medicine, CareCircle, Membership, User, ActivityLog
from services.email_service import send_email, create_smtp_session

logger = logging.getLogger("careme.scheduler")
scheduler = BackgroundScheduler(timezone=KOLKATA_TZ, daemon=True)

def check_dose_escalations(db_session=None):
    """
    Executes the dose escalation rules:
    1. At dose time: email and notify the ELDER only: 'Time for <medicine>'.
    2. After 30 minutes unconfirmed (ESCALATE_1_MIN): email ONLY members with can_receive_alerts.
       Message: '<medicine> was not confirmed at <time>. This doesn't always mean it was missed. Please check in.'
       Never say 'missed for sure'.
    3. After 120 minutes (ESCALATE_2_MIN): mark not_confirmed and email the whole circle including caregivers.
    """
    close_db = False
    if db_session is None:
        db = SessionLocal()
        close_db = True
    else:
        db = db_session

    events_summary = []
    smtp_session = create_smtp_session()
    try:
        now = now_kolkata().replace(tzinfo=None)
        # Query only doses within the relevant active window (last 24 hours to +5 min)
        time_window_start = now - timedelta(hours=24)
        time_window_end = now + timedelta(minutes=5)

        pending_doses = db.query(DoseLog).options(
            joinedload(DoseLog.medicine).joinedload(Medicine.circle).joinedload(CareCircle.elder)
        ).join(Medicine).filter(
            DoseLog.status == "pending",
            DoseLog.scheduled_at >= time_window_start,
            DoseLog.scheduled_at <= time_window_end
        ).all()

        for dose in pending_doses:
            med = dose.medicine
            circle = med.circle if med else None
            if not circle or not circle.elder:
                continue

            elder = circle.elder
            delta = now - dose.scheduled_at
            time_str = dose.scheduled_at.strftime("%I:%M %p")

            # -------------------------------------------------------------
            # RULE 1: At dose time (scheduled_at <= now, and not yet reminded)
            # Email and in-app notify the ELDER only.
            # -------------------------------------------------------------
            if now >= dose.scheduled_at and not dose.reminded:
                dose.reminded = True
                subject = f"Time for {med.name}"
                headline = f"Time for your {med.name} ({med.dosage})"
                message = f"{elder.name} Amma, it is time for your {med.name} ({med.dosage}). Instructions: {med.instructions or 'Take as prescribed by doctor with water.'}"

                res = send_email(
                    to_email=elder.email,
                    subject=subject,
                    headline=headline,
                    message=message,
                    details={
                        "Medicine": f"{med.name} ({med.dosage})",
                        "Scheduled Time": time_str,
                        "Instructions": med.instructions or "Take with water"
                    },
                    badge_text="Dose Reminder",
                    badge_color="#14B8A6",
                    action_url="http://127.0.0.1:8000/dashboard",
                    action_text="I Took This Medicine",
                    user_id=elder.id,
                    notif_type="dose",
                    db=db,
                    sync=True,
                    smtp_connection=smtp_session
                )

                db.add(ActivityLog(
                    circle_id=circle.id,
                    user_id=elder.id,
                    action=f"Dose reminder sent to {elder.name} for {med.name} ({med.dosage})",
                    timestamp=datetime.utcnow()
                ))
                db.commit()

                events_summary.append({
                    "stage": "dose_time",
                    "recipient": f"{elder.name} (Elder only)",
                    "email": elder.email,
                    "subject": subject,
                    "message": message,
                    "mode": res.get("mode")
                })

            # -------------------------------------------------------------
            # RULE 2: After 30 minutes unconfirmed (ESCALATE_1_MIN)
            # Email ONLY members with can_receive_alerts.
            # Text: "<medicine> was not confirmed at <time>. This doesn't always mean it was missed. Please check in."
            # Never say "missed for sure".
            # -------------------------------------------------------------
            if delta >= timedelta(minutes=ESCALATE_1_MIN) and not dose.escalated_30:
                dose.escalated_30 = True
                subject = f"CareMe Update: {med.name} not confirmed at {time_str}"
                headline = f"{med.name} Confirmation Pending"
                message = f"{med.name} was not confirmed at {time_str}. This doesn't always mean it was missed. Please check in."

                # Get only members with can_receive_alerts (eager-loaded user)
                alert_members = db.query(Membership).options(joinedload(Membership.user)).filter(
                    Membership.circle_id == circle.id,
                    Membership.status == "approved",
                    Membership.can_receive_alerts == True
                ).all()

                for m in alert_members:
                    res = send_email(
                        to_email=m.user.email,
                        subject=subject,
                        headline=headline,
                        message=message,
                        details={
                            "Elder": elder.name,
                            "Medicine": f"{med.name} ({med.dosage})",
                            "Scheduled Time": time_str,
                            "Status": "Confirmation Pending (30 min overdue)"
                        },
                        badge_text="Check-In Notice",
                        badge_color="#F59E0B",
                        action_url="http://127.0.0.1:8000/dashboard",
                        action_text="View Circle Status",
                        user_id=m.user_id,
                        notif_type="missed",
                        db=db,
                        sync=True,
                        smtp_connection=smtp_session
                    )
                    events_summary.append({
                        "stage": "30_min_escalation",
                        "recipient": f"{m.user.name} ({m.relationship} - alert authorized)",
                        "email": m.user.email,
                        "subject": subject,
                        "message": message,
                        "mode": res.get("mode")
                    })

                db.add(ActivityLog(
                    circle_id=circle.id,
                    user_id=elder.id,
                    action=f"30-min escalation: Check-in notice sent to alert authorized members for {med.name}",
                    timestamp=datetime.utcnow()
                ))
                db.commit()

            # -------------------------------------------------------------
            # RULE 3: After 120 minutes (ESCALATE_2_MIN)
            # Mark not_confirmed and email the whole circle including caregivers.
            # -------------------------------------------------------------
            if delta >= timedelta(minutes=ESCALATE_2_MIN) and not dose.escalated_120:
                dose.escalated_120 = True
                dose.status = "not_confirmed"
                subject = f"CareMe Escalation: Overdue {med.name} for {elder.name}"
                headline = f"Overdue Dose: {med.name} Marked Not Confirmed"
                message = f"{med.name} ({med.dosage}) scheduled for {time_str} remains unconfirmed after 2 hours and has been marked Not Confirmed. Please check on {elder.name} immediately."

                # Gather whole circle (elder + all approved members including caregivers, eager-loaded)
                all_recipients = [(elder.name, elder.email, elder.id, "Elder")]
                circle_members = db.query(Membership).options(joinedload(Membership.user)).filter(
                    Membership.circle_id == circle.id,
                    Membership.status == "approved"
                ).all()
                for cm in circle_members:
                    all_recipients.append((cm.user.name, cm.user.email, cm.user_id, cm.relationship))

                for r_name, r_email, r_uid, r_rel in all_recipients:
                    res = send_email(
                        to_email=r_email,
                        subject=subject,
                        headline=headline,
                        message=message,
                        details={
                            "Elder": f"{elder.name} (Age {elder.age or 75})",
                            "Medicine": f"{med.name} ({med.dosage})",
                            "Scheduled Time": time_str,
                            "Status": "Marked NOT CONFIRMED (Over 2 Hours)"
                        },
                        badge_text="2-Hour Escalation",
                        badge_color="#EF4444",
                        action_url="http://127.0.0.1:8000/dashboard",
                        action_text="Open CareMe Emergency View",
                        user_id=r_uid,
                        notif_type="missed",
                        db=db,
                        sync=True,
                        smtp_connection=smtp_session
                    )
                    events_summary.append({
                        "stage": "120_min_escalation",
                        "recipient": f"{r_name} ({r_rel})",
                        "email": r_email,
                        "subject": subject,
                        "message": message,
                        "mode": res.get("mode")
                    })

                db.add(ActivityLog(
                    circle_id=circle.id,
                    user_id=elder.id,
                    action=f"120-min critical escalation: {med.name} marked not confirmed, entire circle alerted",
                    timestamp=datetime.utcnow()
                ))
                db.commit()

    except Exception as e:
        logger.error(f"Error in check_dose_escalations: {e}", exc_info=True)
        db.rollback()
    finally:
        if smtp_session:
            try:
                smtp_session.quit()
            except Exception:
                pass
        if close_db:
            db.close()

    return events_summary

def check_appointment_reminders(db_session=None):
    """
    Appointment reminders: 24h and 2h before, using the reminded flags to avoid duplicates.
    """
    close_db = False
    if db_session is None:
        db = SessionLocal()
        close_db = True
    else:
        db = db_session

    events_summary = []
    smtp_session = create_smtp_session()
    try:
        now = now_kolkata().replace(tzinfo=None)
        # Relevant time window for appointment reminders: next 25 hours (covers 24h & 2h reminders)
        upcoming = db.query(Appointment).options(
            joinedload(Appointment.circle).joinedload(CareCircle.elder)
        ).filter(
            Appointment.datetime > now,
            Appointment.datetime <= now + timedelta(hours=25)
        ).all()

        for appt in upcoming:
            time_until = appt.datetime - now
            circle = appt.circle if appt else None
            if not circle or not circle.elder:
                continue

            elder = circle.elder
            appt_time_str = appt.datetime.strftime("%A, %b %d at %I:%M %p")

            # Recipients: elder + members with can_receive_alerts (eager-loaded user)
            recipients = [(elder.name, elder.email, elder.id, "Elder")]
            members = db.query(Membership).options(joinedload(Membership.user)).filter(
                Membership.circle_id == appt.circle_id,
                Membership.status == "approved",
                Membership.can_receive_alerts == True
            ).all()
            for m in members:
                recipients.append((m.user.name, m.user.email, m.user_id, m.relationship))

            # 24-HOUR REMINDER
            if time_until <= timedelta(hours=24) and not appt.reminded_24h:
                appt.reminded_24h = True
                subject = f"Appointment Tomorrow: {appt.doctor} at {appt.hospital}"
                headline = f"Doctor Visit Tomorrow with {appt.doctor}"
                message = f"Reminder: {elder.name} has an appointment tomorrow with {appt.doctor} ({appt.specialty}) at {appt.hospital} ({appt_time_str})."

                for r_name, r_email, r_uid, r_rel in recipients:
                    res = send_email(
                        to_email=r_email,
                        subject=subject,
                        headline=headline,
                        message=message,
                        details={
                            "Patient": elder.name,
                            "Doctor": f"{appt.doctor} ({appt.specialty})",
                            "Hospital": appt.hospital,
                            "Address": appt.address or "Coimbatore",
                            "Phone": appt.phone or "Reception",
                            "Date & Time": appt_time_str
                        },
                        badge_text="24h Reminder",
                        badge_color="#3B82F6",
                        action_url="http://127.0.0.1:8000/appointments",
                        action_text="View Consultation Details",
                        user_id=r_uid,
                        notif_type="appointment",
                        db=db,
                        sync=True,
                        smtp_connection=smtp_session
                    )
                    events_summary.append({
                        "stage": "appointment_24h",
                        "recipient": f"{r_name} ({r_rel})",
                        "email": r_email,
                        "subject": subject,
                        "message": message,
                        "mode": res.get("mode")
                    })

                db.add(ActivityLog(
                    circle_id=circle.id,
                    user_id=elder.id,
                    action=f"24h appointment reminder sent for {appt.doctor} at {appt.hospital}",
                    timestamp=datetime.utcnow()
                ))
                db.commit()

            # 2-HOUR REMINDER
            if time_until <= timedelta(hours=2) and not appt.reminded_2h:
                appt.reminded_2h = True
                subject = f"Urgent Reminder: Appointment in 2 Hours with {appt.doctor}"
                headline = f"Appointment in 2 Hours at {appt.hospital}"
                message = f"Doctor visit for {elder.name} is in 2 hours with {appt.doctor} ({appt.specialty}) at {appt.datetime.strftime('%I:%M %p')}. Please ensure travel preparations are ready."

                for r_name, r_email, r_uid, r_rel in recipients:
                    res = send_email(
                        to_email=r_email,
                        subject=subject,
                        headline=headline,
                        message=message,
                        details={
                            "Patient": elder.name,
                            "Doctor": appt.doctor,
                            "Hospital": appt.hospital,
                            "Time": appt.datetime.strftime('%I:%M %p'),
                            "Clinic Phone": appt.phone
                        },
                        badge_text="2h Urgent Notice",
                        badge_color="#EF4444",
                        action_url="http://127.0.0.1:8000/appointments",
                        action_text="View Clinic Address & Contact",
                        user_id=r_uid,
                        notif_type="appointment",
                        db=db,
                        sync=True,
                        smtp_connection=smtp_session
                    )
                    events_summary.append({
                        "stage": "appointment_2h",
                        "recipient": f"{r_name} ({r_rel})",
                        "email": r_email,
                        "subject": subject,
                        "message": message,
                        "mode": res.get("mode")
                    })

                db.add(ActivityLog(
                    circle_id=circle.id,
                    user_id=elder.id,
                    action=f"2-hour appointment reminder sent for {appt.doctor}",
                    timestamp=datetime.utcnow()
                ))
                db.commit()

    except Exception as e:
        logger.error(f"Error in check_appointment_reminders: {e}", exc_info=True)
        db.rollback()
    finally:
        if smtp_session:
            try:
                smtp_session.quit()
            except Exception:
                pass
        if close_db:
            db.close()

    return events_summary

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(check_dose_escalations, "interval", seconds=30, id="dose_escalations", replace_existing=True)
        scheduler.add_job(check_appointment_reminders, "interval", seconds=60, id="appointment_reminders", replace_existing=True)
        scheduler.start()
        logger.info("CareMe Background Scheduler started with 30s dose checks and 60s appointment checks.")

def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("CareMe Background Scheduler stopped.")
