"""
services/email_service.py - CareMe Real Email Delivery Engine.
Sends responsive HTML + plain-text emails via Gmail SMTP (STARTTLS) or falls back
to console logging when credentials are truly empty.

Supports asynchronous background thread dispatch so slow SMTP handshakes never block
the web request or the APScheduler engine.
"""

import os
import smtplib
import logging
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Notification, User

logger = logging.getLogger("careme.email")

# In-memory history for demo inspection (last 25 emails)
recent_emails: List[Dict[str, Any]] = []

def get_smtp_credentials():
    """
    Reads SMTP_USER and SMTP_PASS at runtime (send time, not import time).
    Strips spaces and quotes from both values.
    Removes spaces from the 16-letter app password.
    """
    raw_user = os.getenv("SMTP_USER", "")
    raw_pass = os.getenv("SMTP_PASS", "")

    smtp_user = raw_user.strip().strip("'\"")
    smtp_pass = raw_pass.strip().strip("'\"").replace(" ", "")

    return smtp_user, smtp_pass

def generate_email_html(
    headline: str,
    message: str,
    details: dict = None,
    badge_text: str = "Notification",
    badge_color: str = "#14B8A6",
    action_url: str = "http://127.0.0.1:8000/dashboard",
    action_text: str = "View CareMe Dashboard"
) -> str:
    """Generates a responsive HTML email with CareMe branding (Teal #14B8A6 and Navy #0F2A4A)."""
    tagline = os.getenv("APP_TAGLINE", "Care from anywhere. Connected by CareMe.")
    details_html = ""
    if details:
        rows = ""
        for k, v in details.items():
            rows += f"""
            <tr>
                <td style="padding: 10px 14px; font-weight: bold; color: #475569; border-bottom: 1px solid #E2E8F0; width: 35%; font-size: 13px;">{k}</td>
                <td style="padding: 10px 14px; color: #0F172A; border-bottom: 1px solid #E2E8F0; font-size: 13px;">{v}</td>
            </tr>
            """
        details_html = f"""
        <table style="width: 100%; border-collapse: collapse; margin: 20px 0; background-color: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 12px; overflow: hidden;">
            {rows}
        </table>
        """

    action_button_html = ""
    if action_url and action_text:
        action_button_html = f"""
        <div style="margin: 28px 0 10px 0; text-align: center;">
            <a href="{action_url}" style="background-color: #14B8A6; color: #FFFFFF; padding: 14px 28px; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 14px; display: inline-block; box-shadow: 0 4px 6px -1px rgba(20, 184, 166, 0.2);">
                {action_text} &rarr;
            </a>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{headline}</title>
</head>
<body style="margin: 0; padding: 0; background-color: #F1F5F9; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased;">
    <table border="0" cellpadding="0" cellspacing="0" width="100%" style="table-layout: fixed;">
        <tr>
            <td align="center" style="padding: 30px 15px;">
                <!-- Main Email Card -->
                <table border="0" cellpadding="0" cellspacing="0" width="100%" style="max-width: 600px; background-color: #FFFFFF; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px -5px rgba(15, 42, 74, 0.08); border: 1px solid #E2E8F0;">
                    
                    <!-- Header (Navy #0F2A4A with Teal #14B8A6 Accent) -->
                    <tr>
                        <td style="background-color: #0F2A4A; padding: 28px 32px; border-bottom: 4px solid #14B8A6;">
                            <table border="0" cellpadding="0" cellspacing="0" width="100%">
                                <tr>
                                    <td>
                                        <div style="font-size: 22px; font-weight: 800; color: #FFFFFF; letter-spacing: -0.5px;">
                                            CareMe
                                        </div>
                                        <div style="color: #94A3B8; font-size: 12px; margin-top: 4px; font-weight: 500;">
                                            {tagline}
                                        </div>
                                    </td>
                                    <td align="right">
                                        <span style="background-color: rgba(20, 184, 166, 0.15); color: #14B8A6; border: 1px solid rgba(20, 184, 166, 0.4); font-size: 11px; font-weight: 700; text-transform: uppercase; padding: 5px 12px; border-radius: 20px;">
                                            {badge_text}
                                        </span>
                                    </td>
                                </tr>
                            </table>
                        </td>
                    </tr>

                    <!-- Body Content -->
                    <tr>
                        <td style="padding: 32px;">
                            <h2 style="margin: 0 0 14px 0; font-size: 20px; font-weight: 800; color: #0F2A4A; line-height: 1.3;">
                                {headline}
                            </h2>
                            <p style="margin: 0 0 16px 0; font-size: 15px; color: #334155; line-height: 1.6;">
                                {message}
                            </p>

                            {details_html}

                            {action_button_html}
                        </td>
                    </tr>

                    <!-- Footer -->
                    <tr>
                        <td style="background-color: #F8FAFC; padding: 20px 32px; border-top: 1px solid #E2E8F0; text-align: center;">
                            <p style="margin: 0; font-size: 12px; color: #64748B;">
                                Lakshmi Devi's Care Circle &bull; Coimbatore, Tamil Nadu
                            </p>
                            <p style="margin: 6px 0 0 0; font-size: 11px; color: #94A3B8;">
                                Automated notification powered by CareMe Healthcare Engine.
                            </p>
                        </td>
                    </tr>

                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""
    return html

def _log_to_console(to: str, subject: str, message: str, reason: str = ""):
    print("=" * 70, flush=True)
    print(f"📧 [CAREME EMAIL ENGINE - CONSOLE MODE]", flush=True)
    if reason:
        print(f"Status:  {reason}", flush=True)
    print(f"To:      {to}", flush=True)
    print(f"Subject: {subject}", flush=True)
    print(f"Time:    {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    print(f"Message: {message}", flush=True)
    print("=" * 70, flush=True)

def _send_smtp_direct(
    to_email: str,
    subject: str,
    headline: str,
    message: str,
    html_content: str,
    action_url: str
) -> Dict[str, Any]:
    """
    Executes the real SMTP handshake using Gmail SMTP (smtp.gmail.com:587, STARTTLS).
    If credentials are missing, logs to console in Console mode.
    If sending fails, returns the exact exception without hiding it.
    """
    smtp_user, smtp_pass = get_smtp_credentials()

    if not smtp_user or not smtp_pass:
        missing = []
        if not smtp_user:
            missing.append("SMTP_USER")
        if not smtp_pass:
            missing.append("SMTP_PASS")
        status_msg = f"Console mode: {', '.join(missing)} is empty in .env. Email logged to console."
        logger.info(f"[CONSOLE MODE] {status_msg} (Recipient: {to_email})")
        _log_to_console(to_email, subject, message, reason=status_msg)
        return {
            "mode": "console_logged",
            "success": True,
            "status_text": status_msg,
            "error": None,
            "error_message": None
        }

    # Construct MIMEMultipart with both plain-text and HTML versions
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"CareMe <{smtp_user}>"
    msg["To"] = to_email

    plain_text = f"{headline}\n\n{message}\n\nCareMe: {action_url}"
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        # Requirement 3: Send using smtplib.SMTP("smtp.gmail.com", 587, timeout=20),
        # then ehlo(), starttls(), ehlo(), login(), send_message()
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info(f"Successfully sent real Gmail SMTP email to {to_email} (Subject: {subject})")
        print(f"✅ [CAREME EMAIL] Successfully delivered via Gmail SMTP to {to_email} (Subject: {subject})", flush=True)
        return {
            "mode": "real_smtp",
            "success": True,
            "status_text": f"Delivered via Gmail SMTP ({smtp_user})",
            "error": None,
            "error_message": None
        }
    except Exception as e:
        # Requirement 4: Do not hide errors. If sending fails, log exact exception and return it.
        err_type = type(e).__name__
        err_str = str(e)
        exact_err = f"{err_type}: {err_str}" if err_str else err_type
        error_msg = f"Email failed: {exact_err}. Check SMTP_USER and SMTP_PASS (use a Gmail App Password)."
        logger.error(f"Gmail SMTP sending failed to {to_email}: {error_msg}", exc_info=True)
        print(f"❌ [CAREME EMAIL ERROR] {error_msg}", flush=True)
        return {
            "mode": "smtp_failed",
            "success": False,
            "status_text": error_msg,
            "error": exact_err,
            "error_message": error_msg
        }

def _record_recent_email(item: Dict[str, Any]):
    recent_emails.insert(0, item)
    if len(recent_emails) > 25:
        recent_emails.pop()

def send_email(
    to_email: str,
    subject: str,
    headline: str,
    message: str,
    details: dict = None,
    badge_text: str = "Alert",
    badge_color: str = "#14B8A6",
    action_url: str = "http://127.0.0.1:8000/dashboard",
    action_text: str = "View CareMe Dashboard",
    user_id: int = None,
    notif_type: str = "dose",
    db: Session = None,
    sync: bool = False
) -> dict:
    """
    Sends an email with CareMe branding via Gmail SMTP (STARTTLS) or safely logs
    to console if credentials are empty in .env.

    - Creates an in-app notification in the database.
    - If credentials exist and sync=False, dispatches via a background thread to prevent blocking.
    - If sync=True, performs delivery synchronously and returns exact delivery or error results.
    """
    to_email = to_email.strip()
    html_content = generate_email_html(
        headline=headline,
        message=message,
        details=details,
        badge_text=badge_text,
        badge_color=badge_color,
        action_url=action_url,
        action_text=action_text
    )

    # 1. Always create in-app notification in DB
    created_notif = None
    own_db = False
    if db is None:
        db = SessionLocal()
        own_db = True

    try:
        target_uid = user_id
        if not target_uid:
            user = db.query(User).filter(User.email == to_email).first()
            if user:
                target_uid = user.id

        if target_uid:
            notif = Notification(
                user_id=target_uid,
                type=notif_type,
                message=f"{subject}: {message}",
                created_at=datetime.utcnow(),
                is_read=False
            )
            db.add(notif)
            db.commit()
            created_notif = notif.id
    except Exception as e:
        logger.error(f"Error creating in-app notification for {to_email}: {e}")
        db.rollback()
    finally:
        if own_db:
            db.close()

    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "to": to_email,
        "subject": subject,
        "headline": headline,
        "message": message,
        "details": details or {},
        "badge": badge_text,
        "in_app_notif_id": created_notif,
        "mode": "pending",
        "success": False,
        "status_text": "Processing delivery...",
        "error": None,
        "error_message": None,
        "html_preview": html_content
    }

    smtp_user, smtp_pass = get_smtp_credentials()

    if not smtp_user or not smtp_pass:
        delivery = _send_smtp_direct(to_email, subject, headline, message, html_content, action_url)
        result.update(delivery)
        _record_recent_email(result)
        return result

    if sync:
        # Synchronous execution (used by /demo/send-test-email so user sees live result)
        delivery = _send_smtp_direct(to_email, subject, headline, message, html_content, action_url)
        result.update(delivery)
        _record_recent_email(result)
        return result
    else:
        # Requirement 8: Asynchronous background thread execution
        result["mode"] = "queued_smtp"
        result["status_text"] = "Dispatching via Gmail SMTP in background..."
        _record_recent_email(result)

        def _bg_worker(res_dict):
            delivery = _send_smtp_direct(to_email, subject, headline, message, html_content, action_url)
            res_dict.update(delivery)

        bg_thread = threading.Thread(target=_bg_worker, args=(result,), daemon=True)
        bg_thread.start()
        return result
