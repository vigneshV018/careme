import random
from fastapi import APIRouter, Request, Response, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from template_config import templates
from sqlalchemy.orm import Session
from database import get_db
from models import User, CareCircle, Membership, Medicine, DoseLog, Appointment
from services.auth_service import (
    hash_password, verify_password, hash_pin, verify_pin,
    login_user, logout_user, get_current_user_optional, get_current_user,
    generate_password_reset_token, verify_password_reset_token
)
from services.notification_service import log_activity, create_notification
from services.rate_limiter import check_login_rate_limit, record_failed_login, reset_login_rate_limit
from services.email_service import send_email
from services.timezone import now_kolkata

router = APIRouter(prefix="", tags=["auth"])

# -----------------------------------------------------------------------------
# Login Endpoints
# -----------------------------------------------------------------------------
@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = None, success: str = None, db: Session = Depends(get_db)):
    current_user = get_current_user_optional(request, db)
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    
    demo_users = db.query(User).all()
    return templates.TemplateResponse("login.html", {
        "request": request,
        "error": error,
        "success": success,
        "demo_users": demo_users
    })

@router.post("/auth/login")
def login_post(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()

    # Rate limiting: 5 failed tries, then 5 min lockout
    is_locked, remaining_secs = check_login_rate_limit(clean_email)
    if is_locked:
        mins = max(1, (remaining_secs + 59) // 60)
        return RedirectResponse(
            url=f"/auth/login?error=Too+many+failed+login+attempts.+Account+locked+for+{mins}+minutes",
            status_code=status.HTTP_302_FOUND
        )

    user = db.query(User).filter(User.email == clean_email).first()
    if not user or not verify_password(password, user.password_hash):
        attempts, lockout = record_failed_login(clean_email)
        if lockout > 0:
            return RedirectResponse(
                url="/auth/login?error=Too+many+failed+login+attempts.+Account+locked+for+5+minutes",
                status_code=status.HTTP_302_FOUND
            )
        rem = max(0, 5 - attempts)
        return RedirectResponse(
            url=f"/auth/login?error=Invalid+email+or+password.+({rem}+attempts+remaining)",
            status_code=status.HTTP_302_FOUND
        )

    # Success: reset rate limiter
    reset_login_rate_limit(clean_email)
    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    login_user(redirect, user.id, request)
    return redirect

@router.post("/auth/pin")
def login_pin(
    request: Request,
    pin: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_pin = pin.strip()
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"pin:{client_ip}"

    # Rate limiting
    is_locked, remaining_secs = check_login_rate_limit(rate_key)
    if is_locked:
        mins = max(1, (remaining_secs + 59) // 60)
        return RedirectResponse(
            url=f"/auth/login?error=Too+many+failed+PIN+attempts.+Locked+for+{mins}+minutes",
            status_code=status.HTTP_302_FOUND
        )

    matched_user = None
    all_users = db.query(User).all()
    for u in all_users:
        if u.pin_hash and verify_pin(clean_pin, u.pin_hash):
            matched_user = u
            break

    if not matched_user:
        attempts, lockout = record_failed_login(rate_key)
        if lockout > 0:
            return RedirectResponse(
                url="/auth/login?error=Too+many+failed+PIN+attempts.+Locked+for+5+minutes",
                status_code=status.HTTP_302_FOUND
            )
        return RedirectResponse(
            url="/auth/login?error=Invalid+PIN.+Please+try+again",
            status_code=status.HTTP_302_FOUND
        )

    # Success: reset rate limiter
    reset_login_rate_limit(rate_key)
    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    login_user(redirect, matched_user.id, request)
    return redirect

@router.get("/auth/switch/{user_id}")
def quick_switch(user_id: int, request: Request, db: Session = Depends(get_db)):
    from config import DEMO_MODE
    if not DEMO_MODE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Persona switcher is disabled in production.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_302_FOUND)
    
    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    login_user(redirect, user.id, request)
    return redirect

# -----------------------------------------------------------------------------
# Registration & Onboarding
# -----------------------------------------------------------------------------
@router.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request, error: str = None, db: Session = Depends(get_db)):
    return templates.TemplateResponse("register.html", {
        "request": request,
        "error": error
    })

@router.post("/auth/register")
def register_post(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    phone: str = Form(None),
    city: str = Form(None),
    age: int = Form(None),
    pin: str = Form(None),
    circle_passcode: str = Form(None),
    medical_consent: str = Form(None),
    db: Session = Depends(get_db)
):
    # 1. Validate Consent Checkbox
    if not medical_consent:
        return RedirectResponse(
            url="/auth/register?error=You+must+accept+the+CareMe+medical+disclaimer+and+privacy+policy+to+register.",
            status_code=status.HTTP_302_FOUND
        )

    # 2. Validate Password Minimum Length (8 characters)
    if len(password.strip()) < 8:
        return RedirectResponse(
            url="/auth/register?error=Password+must+be+at+least+8+characters+long.",
            status_code=status.HTTP_302_FOUND
        )

    clean_email = email.strip().lower()
    existing = db.query(User).filter(User.email == clean_email).first()
    if existing:
        return RedirectResponse(
            url="/auth/register?error=Email+already+registered.+Please+log+in.",
            status_code=status.HTTP_302_FOUND
        )

    # If Family or Caregiver provided a Care Passcode, verify it exists before creating account
    target_circle = None
    if role in ("family", "caregiver") and circle_passcode:
        target_circle = db.query(CareCircle).filter(CareCircle.passcode == circle_passcode.strip()).first()
        if not target_circle:
            return RedirectResponse(
                url="/auth/register?error=Care+Passcode+not+found.+Please+check+the+6-digit+code+with+your+elder+family+member.",
                status_code=status.HTTP_302_FOUND
            )

    # Create User
    user = User(
        name=name.strip(),
        email=clean_email,
        password_hash=hash_password(password.strip()),
        pin_hash=hash_pin(pin) if (pin and pin.strip()) else None,
        role=role,
        phone=phone.strip() if phone else None,
        city=city.strip() if city else None,
        age=age,
        photo_url=f"https://api.dicebear.com/7.x/personas/svg?seed={name.strip()}"
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # If Elder: create Care Circle & approved owner membership, then redirect to onboarding
    if role == "elder":
        passcode = str(random.randint(100000, 999999))
        while db.query(CareCircle).filter(CareCircle.passcode == passcode).first():
            passcode = str(random.randint(100000, 999999))

        circle = CareCircle(elder_id=user.id, passcode=passcode)
        db.add(circle)
        db.commit()
        db.refresh(circle)

        owner_mem = Membership(
            circle_id=circle.id,
            user_id=user.id,
            relationship="Elder (Self)",
            can_view_health=True,
            can_edit_medicines=True,
            can_edit_appointments=True,
            can_receive_alerts=True,
            can_view_location=True,
            can_manage_access=True,
            status="approved"
        )
        db.add(owner_mem)
        db.commit()

        redirect = RedirectResponse(url="/onboarding/elder", status_code=status.HTTP_302_FOUND)
        login_user(redirect, user.id, request)
        return redirect

    # If Family/Caregiver joining with passcode: create pending membership
    if target_circle:
        rel = "Family" if role == "family" else "Caregiver"
        membership = Membership(
            circle_id=target_circle.id,
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
        db.add(membership)
        db.commit()

        log_activity(db, target_circle.id, user.id, f"{user.name} requested to join care circle as {rel}")
        if target_circle.elder_id:
            create_notification(
                db,
                target_circle.elder_id,
                "family",
                f"{user.name} requested to join your Care Circle as {rel}. Please review and approve."
            )
            # Send real email notification to elder (Requirement 7)
            if target_circle.elder and target_circle.elder.email:
                send_email(
                    to_email=target_circle.elder.email,
                    subject=f"CareMe: {user.name} requested to join your Care Circle",
                    headline=f"New Access Request: {user.name}",
                    message=f"{user.name} registered as your {rel} and requested to join your Care Circle using your Care Passcode. No health data or controls have been shared yet. Please review and approve on your CareMe dashboard.",
                    details={
                        "Requester": user.name,
                        "Relationship": rel,
                        "Email": user.email,
                        "Phone": user.phone or "Not provided",
                        "Circle Passcode": target_circle.passcode,
                        "Status": "Pending Elder Approval"
                    },
                    badge_text="Access Request",
                    badge_color="#3B82F6",
                    action_url="http://127.0.0.1:8000/circle",
                    action_text="Review & Approve Access",
                    user_id=target_circle.elder.id,
                    notif_type="family",
                    db=db,
                    sync=False
                )

    redirect = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    login_user(redirect, user.id, request)
    return redirect

# -----------------------------------------------------------------------------
# Elder Onboarding
# -----------------------------------------------------------------------------
@router.get("/onboarding/elder", response_class=HTMLResponse)
def elder_onboarding_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if user.role != "elder":
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    circle = db.query(CareCircle).filter(CareCircle.elder_id == user.id).first()
    if not circle:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)

    return templates.TemplateResponse("onboarding_elder.html", {
        "request": request,
        "user": user,
        "circle": circle
    })

@router.post("/onboarding/elder")
def elder_onboarding_post(
    request: Request,
    med_name: str = Form(None),
    med_dosage: str = Form(None),
    med_time: str = Form("08:00"),
    contact_name: str = Form(None),
    contact_role: str = Form(None),
    contact_phone: str = Form(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    circle = db.query(CareCircle).filter(CareCircle.elder_id == user.id).first()
    if circle:
        # Add First Medicine if provided
        if med_name and med_name.strip():
            medicine = Medicine(
                circle_id=circle.id,
                name=med_name.strip(),
                dosage=med_dosage.strip() if med_dosage else "As directed",
                instructions="Take with water",
                times=[med_time],
                days=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                start_date=now_kolkata().date()
            )
            db.add(medicine)
            db.commit()
            db.refresh(medicine)

            # Create today's dose log
            today_dt = now_kolkata()
            try:
                hh, mm = map(int, med_time.split(":"))
                scheduled = today_dt.replace(hour=hh, minute=mm, second=0, microsecond=0).replace(tzinfo=None)
                dose_log = DoseLog(
                    medicine_id=medicine.id,
                    scheduled_at=scheduled,
                    status="pending"
                )
                db.add(dose_log)
                db.commit()
            except Exception:
                pass

            log_activity(db, circle.id, user.id, f"Added initial medicine {medicine.name} ({medicine.dosage})")

        # Record Emergency Contact in Activity Log / Notifications
        if contact_name and contact_name.strip():
            desc = f"Emergency contact registered: {contact_name.strip()} ({contact_role or 'Family'}) - {contact_phone or 'Phone on file'}"
            log_activity(db, circle.id, user.id, desc)

    return RedirectResponse(url="/dashboard?success=Welcome+to+your+CareMe+Circle!", status_code=status.HTTP_302_FOUND)

# -----------------------------------------------------------------------------
# Forgot Password & Reset Password
# -----------------------------------------------------------------------------
@router.get("/auth/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, error: str = None, success: str = None):
    return templates.TemplateResponse("forgot_password.html", {
        "request": request,
        "error": error,
        "success": success
    })

@router.post("/auth/forgot-password")
def forgot_password_post(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db)
):
    clean_email = email.strip().lower()
    user = db.query(User).filter(User.email == clean_email).first()

    if user:
        token = generate_password_reset_token(user)
        reset_url = str(request.base_url).rstrip("/") + f"/auth/reset-password?token={token}"

        send_email(
            to_email=user.email,
            subject="CareMe: Password Reset Request",
            headline="Reset Your CareMe Password",
            message=(
                "We received a request to reset your CareMe password. Click the link below to select a new password. "
                "This reset link is single-use and will expire in 30 minutes. If you did not request a password reset, you can safely ignore this email."
            ),
            details={
                "Account Email": user.email,
                "Request Time": now_kolkata().strftime("%d %b %Y, %I:%M %p"),
                "Link Expiration": "30 minutes (Single Use)"
            },
            badge_text="Security Notice",
            badge_color="#0F2A4A",
            action_url=reset_url,
            action_text="Reset My Password",
            user_id=user.id,
            notif_type="family",
            db=db
        )

    # Always return success message to prevent user enumeration
    return RedirectResponse(
        url="/auth/forgot-password?success=If+an+account+exists+with+that+email,+a+secure+30-minute+reset+link+has+been+sent.",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/auth/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = "", error: str = None, db: Session = Depends(get_db)):
    user = verify_password_reset_token(token, db) if token else None
    return templates.TemplateResponse("reset_password.html", {
        "request": request,
        "token": token,
        "token_valid": bool(user),
        "error": error
    })

@router.post("/auth/reset-password")
def reset_password_post(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = verify_password_reset_token(token, db)
    if not user:
        return RedirectResponse(
            url="/auth/reset-password?token=" + token + "&error=Reset+link+is+invalid+or+has+expired.+Please+request+a+new+one.",
            status_code=status.HTTP_302_FOUND
        )

    if len(password.strip()) < 8:
        return RedirectResponse(
            url="/auth/reset-password?token=" + token + "&error=Password+must+be+at+least+8+characters+long.",
            status_code=status.HTTP_302_FOUND
        )

    if password.strip() != confirm_password.strip():
        return RedirectResponse(
            url="/auth/reset-password?token=" + token + "&error=Passwords+do+not+match.+Please+try+again.",
            status_code=status.HTTP_302_FOUND
        )

    user.password_hash = hash_password(password.strip())
    db.commit()

    return RedirectResponse(
        url="/auth/login?success=Password+reset+successful.+Please+sign+in+with+your+new+password.",
        status_code=status.HTTP_302_FOUND
    )

# -----------------------------------------------------------------------------
# Privacy Notice Page
# -----------------------------------------------------------------------------
@router.get("/privacy", response_class=HTMLResponse)
def privacy_page(request: Request):
    return templates.TemplateResponse("privacy.html", {"request": request})

# -----------------------------------------------------------------------------
# Logout
# -----------------------------------------------------------------------------
@router.get("/auth/logout")
def logout():
    redirect = RedirectResponse(url="/auth/login?success=Logged+out+successfully", status_code=status.HTTP_302_FOUND)
    logout_user(redirect)
    return redirect
