import json
from datetime import datetime, date
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date, ForeignKey, Text
)
from sqlalchemy.orm import relationship as sa_relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    pin_hash = Column(String(255), nullable=True)
    role = Column(String(50), nullable=False)  # 'elder', 'family', 'caregiver'
    phone = Column(String(50), nullable=True)
    city = Column(String(100), nullable=True)
    age = Column(Integer, nullable=True)
    photo_url = Column(String(255), nullable=True)

    # Relationships
    owned_circles = sa_relationship("CareCircle", back_populates="elder", foreign_keys="CareCircle.elder_id")
    memberships = sa_relationship("Membership", back_populates="user", cascade="all, delete-orphan", foreign_keys="Membership.user_id")
    notifications = sa_relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    triggered_alerts = sa_relationship("EmergencyAlert", back_populates="caller", foreign_keys="EmergencyAlert.triggered_by")
    acknowledged_alerts = sa_relationship("EmergencyAlert", back_populates="responder", foreign_keys="EmergencyAlert.acknowledged_by")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "phone": self.phone,
            "city": self.city,
            "age": self.age,
            "photo_url": self.photo_url
        }


class CareCircle(Base):
    __tablename__ = "care_circles"

    id = Column(Integer, primary_key=True, index=True)
    elder_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    passcode = Column(String(6), unique=True, nullable=False, index=True)

    # Relationships
    elder = sa_relationship("User", back_populates="owned_circles", foreign_keys=[elder_id])
    memberships = sa_relationship("Membership", back_populates="circle", cascade="all, delete-orphan")
    medicines = sa_relationship("Medicine", back_populates="circle", cascade="all, delete-orphan")
    appointments = sa_relationship("Appointment", back_populates="circle", cascade="all, delete-orphan")
    emergency_alerts = sa_relationship("EmergencyAlert", back_populates="circle", cascade="all, delete-orphan")
    activity_logs = sa_relationship("ActivityLog", back_populates="circle", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("care_circles.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    relationship = Column(String(50), default="Family")
    can_view_health = Column(Boolean, default=True)
    can_edit_medicines = Column(Boolean, default=False)
    can_edit_appointments = Column(Boolean, default=False)
    can_receive_alerts = Column(Boolean, default=True)
    can_view_location = Column(Boolean, default=True)
    can_manage_access = Column(Boolean, default=False)
    status = Column(String(50), default="approved")  # 'pending', 'approved'

    # Relationships
    circle = sa_relationship("CareCircle", back_populates="memberships")
    user = sa_relationship("User", back_populates="memberships")


class Medicine(Base):
    __tablename__ = "medicines"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("care_circles.id"), nullable=False)
    name = Column(String(100), nullable=False)
    dosage = Column(String(100), nullable=False)
    instructions = Column(String(255), nullable=True)
    times = Column(Text, nullable=False, default="[]")  # JSON list like ["08:00", "14:00"]
    days = Column(Text, nullable=False, default='["Daily"]')  # JSON list
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)

    # Relationships
    circle = sa_relationship("CareCircle", back_populates="medicines")
    dose_logs = sa_relationship("DoseLog", back_populates="medicine", cascade="all, delete-orphan")

    def get_times_list(self):
        try:
            return json.loads(self.times)
        except Exception:
            return [self.times] if self.times else []

    def get_days_list(self):
        try:
            return json.loads(self.days)
        except Exception:
            return ["Daily"]


class DoseLog(Base):
    __tablename__ = "dose_logs"

    id = Column(Integer, primary_key=True, index=True)
    medicine_id = Column(Integer, ForeignKey("medicines.id"), nullable=False)
    scheduled_at = Column(DateTime, nullable=False, index=True)
    status = Column(String(50), default="pending")  # 'taken', 'pending', 'not_confirmed'
    confirmed_at = Column(DateTime, nullable=True)
    reminded = Column(Boolean, default=False)
    escalated_30 = Column(Boolean, default=False)
    escalated_120 = Column(Boolean, default=False)

    # Relationships
    medicine = sa_relationship("Medicine", back_populates="dose_logs")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("care_circles.id"), nullable=False)
    doctor = Column(String(100), nullable=False)
    specialty = Column(String(100), nullable=False)
    hospital = Column(String(150), nullable=False)
    address = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    datetime = Column(DateTime, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    reminded_24h = Column(Boolean, default=False)
    reminded_2h = Column(Boolean, default=False)

    # Relationships
    circle = sa_relationship("CareCircle", back_populates="appointments")


class EmergencyAlert(Base):
    __tablename__ = "emergency_alerts"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("care_circles.id"), nullable=False)
    triggered_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    # Relationships
    circle = sa_relationship("CareCircle", back_populates="emergency_alerts")
    caller = sa_relationship("User", foreign_keys=[triggered_by], back_populates="triggered_alerts")
    responder = sa_relationship("User", foreign_keys=[acknowledged_by], back_populates="acknowledged_alerts")


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, index=True)
    circle_id = Column(Integer, ForeignKey("care_circles.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(255), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    circle = sa_relationship("CareCircle", back_populates="activity_logs")
    user = sa_relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)  # 'dose', 'missed', 'appointment', 'sos', 'caregiver', 'family'
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    is_read = Column(Boolean, default=False)

    # Relationships
    user = sa_relationship("User", back_populates="notifications")
