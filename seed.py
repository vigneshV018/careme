import os
import sys
import json
from datetime import datetime, timedelta, date, time
from database import engine, SessionLocal, Base
from models import (
    User, CareCircle, Membership, Medicine, DoseLog,
    Appointment, EmergencyAlert, ActivityLog, Notification
)
from services.auth_service import hash_password, hash_pin

def seed():
    print("Dropping existing tables and creating fresh schema...")
    try:
        engine.dispose()
    except Exception:
        pass
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        print("Creating users...")
        # 1. Elder: Lakshmi (75, Coimbatore, PIN 1234)
        lakshmi = User(
            name="Lakshmi",
            email="lakshmi@caresync.ai",
            password_hash=hash_password("password123"),
            pin_hash=hash_pin("1234"),
            role="elder",
            phone="+91 98765 43210",
            city="Coimbatore",
            age=75,
            photo_url="https://images.unsplash.com/photo-1727179299533-c5fd6092851c?w=200&h=200&auto=format&fit=crop&crop=face&q=80"
        )
        # 2. Son: Arun (30, Chennai)
        arun = User(
            name="Arun",
            email="arun@caresync.ai",
            password_hash=hash_password("password123"),
            pin_hash=hash_pin("0000"),
            role="family",
            phone="+91 98401 23456",
            city="Chennai",
            age=30,
            photo_url="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=200&auto=format&fit=crop&q=80"
        )
        # 3. Daughter: Priya
        priya = User(
            name="Priya",
            email="priya@caresync.ai",
            password_hash=hash_password("password123"),
            pin_hash=hash_pin("0000"),
            role="family",
            phone="+91 98402 34567",
            city="Bengaluru",
            age=28,
            photo_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=200&auto=format&fit=crop&q=80"
        )
        # 4. Caregiver: Meena
        meena = User(
            name="Meena",
            email="meena@caresync.ai",
            password_hash=hash_password("password123"),
            pin_hash=hash_pin("0000"),
            role="caregiver",
            phone="+91 98403 45678",
            city="Coimbatore",
            age=35,
            photo_url="https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=200&auto=format&fit=crop&q=80"
        )

        db.add_all([lakshmi, arun, priya, meena])
        db.commit()
        db.refresh(lakshmi)
        db.refresh(arun)
        db.refresh(priya)
        db.refresh(meena)

        print(f"Users created: Lakshmi (id={lakshmi.id}), Arun (id={arun.id}), Priya (id={priya.id}), Meena (id={meena.id})")

        # Create Care Circle with passcode 482915
        circle = CareCircle(
            elder_id=lakshmi.id,
            passcode="482915"
        )
        db.add(circle)
        db.commit()
        db.refresh(circle)
        print(f"Care Circle created with passcode {circle.passcode} (id={circle.id})")

        # Memberships
        mem_arun = Membership(
            circle_id=circle.id,
            user_id=arun.id,
            relationship="Son",
            can_view_health=True,
            can_edit_medicines=True,
            can_edit_appointments=True,
            can_receive_alerts=True,
            can_view_location=True,
            can_manage_access=True,
            status="approved"
        )
        mem_priya = Membership(
            circle_id=circle.id,
            user_id=priya.id,
            relationship="Daughter",
            can_view_health=True,
            can_edit_medicines=True,
            can_edit_appointments=True,
            can_receive_alerts=True,
            can_view_location=True,
            can_manage_access=False,
            status="approved"
        )
        mem_meena = Membership(
            circle_id=circle.id,
            user_id=meena.id,
            relationship="Caregiver",
            can_view_health=True,
            can_edit_medicines=True,
            can_edit_appointments=True,
            can_receive_alerts=True,
            can_view_location=True,
            can_manage_access=False,
            status="approved"
        )
        db.add_all([mem_arun, mem_priya, mem_meena])
        db.commit()

        # Medicines
        med_metformin = Medicine(
            circle_id=circle.id,
            name="Metformin",
            dosage="500mg",
            instructions="Take after breakfast with a full glass of water",
            times=json.dumps(["08:00"]),
            days=json.dumps(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
            start_date=date.today() - timedelta(days=30),
            end_date=None
        )
        med_amlodipine = Medicine(
            circle_id=circle.id,
            name="Amlodipine",
            dosage="5mg",
            instructions="Take morning dose for blood pressure regulation",
            times=json.dumps(["10:00"]),
            days=json.dumps(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
            start_date=date.today() - timedelta(days=30),
            end_date=None
        )
        med_atorvastatin = Medicine(
            circle_id=circle.id,
            name="Atorvastatin",
            dosage="10mg",
            instructions="Take after lunch/mid-day as prescribed",
            times=json.dumps(["14:00"]),
            days=json.dumps(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
            start_date=date.today() - timedelta(days=30),
            end_date=None
        )
        db.add_all([med_metformin, med_amlodipine, med_atorvastatin])
        db.commit()
        db.refresh(med_metformin)
        db.refresh(med_amlodipine)
        db.refresh(med_atorvastatin)

        print("Medicines created: Metformin 500mg (08:00), Amlodipine 5mg (10:00), Atorvastatin 10mg (14:00)")

        # Dose logs for past 7 days (about 86% taken, misses mostly in morning)
        # 7 days: day -6 to day 0. 3 medicines per day = 21 doses.
        # Exactly 18 taken (85.7% ~ 86%) and 3 missed/not_confirmed.
        # Misses in morning:
        # Day -5 (08:00 Metformin) - Missed
        # Day -3 (08:00 Metformin) - Missed
        # Day -2 (10:00 Amlodipine) - Missed
        # All others: taken
        today = date.today()
        now = datetime.now()
        dose_logs = []

        med_list = [
            (med_metformin, "08:00", 8),
            (med_amlodipine, "10:00", 10),
            (med_atorvastatin, "14:00", 14)
        ]

        for day_offset in range(7, 0, -1):
            target_date = today - timedelta(days=day_offset)

            for med, time_str, hour in med_list:
                scheduled_time = datetime.combine(target_date, time(hour, 0))

                # Check misses condition: 3 morning misses out of 21 doses = 18 taken / 21 = 85.7% (~86%)
                is_missed = False
                if day_offset == 5 and med.name == "Metformin":
                    is_missed = True
                elif day_offset == 3 and med.name == "Metformin":
                    is_missed = True
                elif day_offset == 2 and med.name == "Amlodipine":
                    is_missed = True

                if is_missed:
                    status = "not_confirmed"
                    confirmed_at = None
                    reminded = True
                    esc30 = True
                    esc120 = True
                else:
                    status = "taken"
                    confirmed_at = scheduled_time + timedelta(minutes=14)
                    reminded = True
                    esc30 = False
                    esc120 = False

                dose_logs.append(DoseLog(
                    medicine_id=med.id,
                    scheduled_at=scheduled_time,
                    status=status,
                    confirmed_at=confirmed_at,
                    reminded=reminded,
                    escalated_30=esc30,
                    escalated_120=esc120
                ))

        # Also add today's doses for interactive use
        # 08:00 taken, 10:00 taken, 14:00 pending
        dose_logs.append(DoseLog(
            medicine_id=med_metformin.id,
            scheduled_at=datetime.combine(today, time(8, 0)),
            status="taken",
            confirmed_at=datetime.combine(today, time(8, 15)),
            reminded=True,
            escalated_30=False,
            escalated_120=False
        ))
        dose_logs.append(DoseLog(
            medicine_id=med_amlodipine.id,
            scheduled_at=datetime.combine(today, time(10, 0)),
            status="taken",
            confirmed_at=datetime.combine(today, time(10, 8)),
            reminded=True,
            escalated_30=False,
            escalated_120=False
        ))
        dose_logs.append(DoseLog(
            medicine_id=med_atorvastatin.id,
            scheduled_at=datetime.combine(today, time(14, 0)),
            status="pending",
            confirmed_at=None,
            reminded=False,
            escalated_30=False,
            escalated_120=False
        ))
        db.add_all(dose_logs)
        db.commit()

        taken_count = sum(1 for d in dose_logs if d.status == "taken")
        total_count = len(dose_logs)
        print(f"Dose logs created: {taken_count}/{total_count} taken ({round(taken_count/total_count*100, 1)}%)")

        # Appointment: Dr. Ramesh, Cardiologist, KG Hospital, Coimbatore, tomorrow 11:00 AM
        tomorrow_11am = datetime.combine(today + timedelta(days=1), time(11, 0))
        appt = Appointment(
            circle_id=circle.id,
            doctor="Dr. Ramesh",
            specialty="Cardiologist",
            hospital="KG Hospital",
            address="Arts College Road, Coimbatore - 641018",
            phone="+91 422 2221212",
            datetime=tomorrow_11am,
            notes="Quarterly cardiac follow-up, BP review, and ECG evaluation.",
            reminded_24h=True,
            reminded_2h=False
        )
        db.add(appt)
        db.commit()
        print(f"Appointment created with Dr. Ramesh at KG Hospital tomorrow at 11:00 AM")

        # Activity Logs
        activities = [
            ActivityLog(
                circle_id=circle.id,
                user_id=arun.id,
                action="Arun joined Care Circle as Son",
                timestamp=datetime.utcnow() - timedelta(days=6)
            ),
            ActivityLog(
                circle_id=circle.id,
                user_id=arun.id,
                action="Prescribed medicines Metformin, Amlodipine, and Atorvastatin added",
                timestamp=datetime.utcnow() - timedelta(days=6)
            ),
            ActivityLog(
                circle_id=circle.id,
                user_id=meena.id,
                action="Caregiver Meena assigned to Lakshmi's daily care circle",
                timestamp=datetime.utcnow() - timedelta(days=5)
            ),
            ActivityLog(
                circle_id=circle.id,
                user_id=arun.id,
                action="Scheduled Cardiology consultation with Dr. Ramesh at KG Hospital",
                timestamp=datetime.utcnow() - timedelta(days=1)
            ),
            ActivityLog(
                circle_id=circle.id,
                user_id=lakshmi.id,
                action="Lakshmi confirmed morning medication",
                timestamp=datetime.utcnow() - timedelta(hours=2)
            ),
        ]
        db.add_all(activities)

        # Notifications
        notifs = [
            Notification(
                user_id=arun.id,
                type="appointment",
                message="Reminder: Dr. Ramesh (Cardiologist) appointment tomorrow at 11:00 AM at KG Hospital, Coimbatore.",
                created_at=datetime.utcnow() - timedelta(hours=3),
                is_read=False
            ),
            Notification(
                user_id=arun.id,
                type="missed",
                message="Pattern Insight: Morning dose of Metformin was missed 2 days ago. Consider a morning reminder call.",
                created_at=datetime.utcnow() - timedelta(days=2),
                is_read=True
            ),
            Notification(
                user_id=lakshmi.id,
                type="appointment",
                message="Doctor appointment tomorrow at 11:00 AM with Dr. Ramesh at KG Hospital. Arun has been notified.",
                created_at=datetime.utcnow() - timedelta(hours=3),
                is_read=False
            ),
            Notification(
                user_id=meena.id,
                type="dose",
                message="Daily care routine active for Lakshmi Amma. Please check blood pressure before noon.",
                created_at=datetime.utcnow() - timedelta(hours=4),
                is_read=False
            )
        ]
        db.add_all(notifs)
        db.commit()
        print("Activity logs and notifications seeded.")

        print("Seeding completed successfully!")

    except Exception as e:
        print(f"Error during seeding: {e}")
        db.rollback()
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    seed()
