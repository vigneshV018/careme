import asyncio
import json
from starlette.requests import Request
from database import SessionLocal
from seed import seed
from models import User, CareCircle, Membership, ActivityLog, Notification

from routes.auth import register_post
from routes.dashboard import dashboard, location_page
from routes.medicines import medicines_list
from routes.appointments import appointments_list
from routes.alerts import alerts_page
from routes.circle import (
    circle_detail, approve_member, decline_member,
    toggle_permission, regenerate_passcode, PermissionToggle
)
from fastapi import HTTPException

def make_request(path="/", method="GET", json_body=None):
    body_bytes = b""
    headers = []
    if json_body is not None:
        body_bytes = json.dumps(json_body).encode("utf-8")
        headers = [(b"content-type", b"application/json")]

    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": headers,
        "query_string": b"",
        "server": ("127.0.0.1", 8000),
        "client": ("127.0.0.1", 54321),
    }

    req = Request(scope)
    if json_body is not None:
        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        req._receive = receive
    return req

def run_all_tests():
    print("\n=======================================================", flush=True)
    print(" CARE-SYNC AI: ELDER-CONTROLLED ACCESS TEST SUITE", flush=True)
    print("=======================================================\n", flush=True)

    db = SessionLocal()
    # Clean up any leftover test user
    old_ravi = db.query(User).filter(User.email == "ravi@caresync.ai").first()
    if old_ravi:
        db.delete(old_ravi)
        db.commit()

    # Reset Arun's location permission to True for test consistency
    arun_init = db.query(User).filter(User.name == "Arun").first()
    if arun_init:
        arun_mem_init = db.query(Membership).filter(Membership.user_id == arun_init.id).first()
        if arun_mem_init:
            arun_mem_init.can_view_location = True
            db.commit()

    # Verify initial state
    circle = db.query(CareCircle).filter(CareCircle.passcode == "482915").first()
    assert circle is not None, "CareCircle with passcode 482915 must exist"
    lakshmi = circle.elder
    assert lakshmi.name == "Lakshmi"
    print(f" Initial state verified: Care Circle {circle.passcode} owned by {lakshmi.name}")

    # -------------------------------------------------------------------
    # TEST 1: Join as a new user with passcode 482915
    # -------------------------------------------------------------------
    print("\n--- TEST 1: Register New User (Ravi) with Passcode 482915 ---")
    reg_resp = register_post(
        name="Ravi",
        email="ravi@caresync.ai",
        password="password123",
        role="family",
        phone="+91 99887 76655",
        city="Chennai",
        age=32,
        pin=None,
        circle_passcode="482915",
        db=db
    )
    assert reg_resp.status_code == 302, f"Expected 302 redirect, got {reg_resp.status_code}"

    db.expire_all()
    ravi = db.query(User).filter(User.email == "ravi@caresync.ai").first()
    assert ravi is not None, "Ravi must be created in DB"

    ravi_mem = db.query(Membership).filter(Membership.user_id == ravi.id).first()
    assert ravi_mem is not None, "Ravi membership record must exist"
    assert ravi_mem.status == "pending", f"Expected status 'pending', got '{ravi_mem.status}'"
    assert ravi_mem.can_view_health is False, "can_view_health must be False"
    assert ravi_mem.can_edit_medicines is False, "can_edit_medicines must be False"
    assert ravi_mem.can_edit_appointments is False, "can_edit_appointments must be False"
    assert ravi_mem.can_receive_alerts is False, "can_receive_alerts must be False"
    assert ravi_mem.can_view_location is False, "can_view_location must be False"
    assert ravi_mem.can_manage_access is False, "can_manage_access must be False"
    print("✓ Membership created with status='pending' and NO access (all 6 flags False)")

    # Ravi visits dashboard
    req_ravi_dash = make_request("/dashboard")
    dash_resp = dashboard(req_ravi_dash, user=ravi, db=db)
    dash_html = dash_resp.body.decode("utf-8")
    assert "Waiting for Lakshmi to approve" in dash_html, "Dashboard must show 'Waiting for Lakshmi to approve'"
    assert "Pending Elder Approval" in dash_html, "Dashboard must show 'Pending Elder Approval'"
    assert "482915" in dash_html, "Dashboard must display passcode used"
    print("✓ Ravi's dashboard renders 'Waiting for Lakshmi to approve' page")

    # Ravi visits /medicines (server-side enforcement)
    med_resp = medicines_list(make_request("/medicines"), user=ravi, db=db)
    med_html = med_resp.body.decode("utf-8")
    assert "Lakshmi has not shared medicine details with you" in med_html
    print("✓ Server blocks Ravi from /medicines: 'Lakshmi has not shared medicine details with you.'")

    # Ravi visits /appointments (server-side enforcement)
    appt_resp = appointments_list(make_request("/appointments"), user=ravi, db=db)
    appt_html = appt_resp.body.decode("utf-8")
    assert "Lakshmi has not shared appointments with you" in appt_html
    print("✓ Server blocks Ravi from /appointments: 'Lakshmi has not shared appointments with you.'")

    # Ravi visits /alerts (server-side enforcement)
    alert_resp = alerts_page(make_request("/alerts"), user=ravi, db=db)
    alert_html = alert_resp.body.decode("utf-8")
    assert "Lakshmi has not shared emergency alerts with you" in alert_html
    print("✓ Server blocks Ravi from /alerts: 'Lakshmi has not shared emergency alerts with you.'")

    # Ravi visits /location (server-side enforcement)
    loc_resp = location_page(make_request("/location"), user=ravi, db=db)
    loc_html = loc_resp.body.decode("utf-8")
    assert "Lakshmi has not shared location tracking with you" in loc_html
    print("✓ Server blocks Ravi from /location: 'Lakshmi has not shared location tracking with you.'")

    # -------------------------------------------------------------------
    # TEST 2: Approve as Lakshmi
    # -------------------------------------------------------------------
    print("\n--- TEST 2: Elder Lakshmi Reviews & Approves Ravi ---")
    req_lakshmi = make_request("/dashboard")
    elder_dash = dashboard(req_lakshmi, user=lakshmi, db=db)
    elder_html = elder_dash.body.decode("utf-8")
    assert "Pending Requests to Join Your Care Circle" in elder_html, "Elder dashboard must have pending requests card"
    assert "Ravi" in elder_html, "Ravi must be listed in pending requests card"
    assert "Approve" in elder_html, "Approve button must be present"
    assert "Decline" in elder_html, "Decline button must be present"
    print("✓ Elder dashboard displays large 'Pending Care Circle Requests' card with Approve & Decline buttons")

    # Lakshmi approves Ravi
    appr_resp = approve_member(ravi_mem.id, make_request(f"/circle/member/{ravi_mem.id}/approve", method="POST"), user=lakshmi, db=db)
    assert appr_resp.status_code == 302

    db.expire_all()
    ravi_mem_after = db.query(Membership).filter(Membership.id == ravi_mem.id).first()
    assert ravi_mem_after.status == "approved", "Ravi membership should be approved"
    assert ravi_mem_after.can_view_health is True, "Default minimal permission: can_view_health=True"
    assert ravi_mem_after.can_receive_alerts is True, "Default minimal permission: can_receive_alerts=True"
    assert ravi_mem_after.can_edit_medicines is False, "can_edit_medicines remains False"
    assert ravi_mem_after.can_view_location is False, "can_view_location remains False"
    print("✓ Ravi's membership activated with minimal default permissions (health=True, alerts=True, location=False)")

    # Verify activity log
    log = db.query(ActivityLog).filter(ActivityLog.circle_id == circle.id).order_by(ActivityLog.timestamp.desc()).first()
    assert "approved Ravi" in log.action
    print(f"✓ Action logged in activity_log: '{log.action}'")

    # Ravi's dashboard is now active
    dash_active = dashboard(make_request("/dashboard"), user=ravi, db=db)
    dash_active_html = dash_active.body.decode("utf-8")
    assert "Waiting for Lakshmi to approve" not in dash_active_html
    assert "Lakshmi Devi" in dash_active_html
    print("✓ Ravi now views active family dashboard")

    # Ravi can now view medicines
    med_active = medicines_list(make_request("/medicines"), user=ravi, db=db)
    med_active_html = med_active.body.decode("utf-8")
    assert "Metformin" in med_active_html
    print("✓ Ravi can now view health & medicines")

    # -------------------------------------------------------------------
    # TEST 3: Turn off "View location" for Arun
    # -------------------------------------------------------------------
    print("\n--- TEST 3: Turn Off 'View Location' for Arun ---")
    arun = db.query(User).filter(User.name == "Arun").first()
    arun_mem = db.query(Membership).filter(Membership.user_id == arun.id).first()
    assert arun_mem.can_view_location is True, "Arun initially has location permission"

    # Toggle off can_view_location for Arun
    toggle_req = make_request(f"/circle/member/{arun_mem.id}/toggle-permission", method="POST")
    toggle_res = toggle_permission(arun_mem.id, PermissionToggle(permission="can_view_location", value=False), toggle_req, user=lakshmi, db=db)
    assert toggle_res.status_code == 200
    toggle_data = json.loads(toggle_res.body.decode("utf-8"))
    assert toggle_data["status"] == "success"
    assert toggle_data["permission"] == "can_view_location"
    assert toggle_data["value"] is False
    print(f"✓ AJAX toggle response: {toggle_data['message']}")

    db.expire_all()
    arun_mem_after = db.query(Membership).filter(Membership.id == arun_mem.id).first()
    assert arun_mem_after.can_view_location is False, "DB confirms Arun can_view_location is False"
    print("✓ Database confirms Arun's can_view_location is now False")

    # -------------------------------------------------------------------
    # TEST 4: Confirm Arun can no longer see location
    # -------------------------------------------------------------------
    print("\n--- TEST 4: Confirm Arun Can No Longer See Location ---")
    arun_dash = dashboard(make_request("/dashboard"), user=arun, db=db)
    arun_dash_html = arun_dash.body.decode("utf-8")
    assert "Lakshmi has not shared location tracking with you" in arun_dash_html, "Dashboard must show restricted location notice"
    assert "11.0168° N, 76.9558° E" not in arun_dash_html, "GPS coordinates must NOT be visible to Arun"
    print("✓ Arun's dashboard displays: 'Lakshmi has not shared location tracking with you' and hides GPS coordinates")

    arun_loc = location_page(make_request("/location"), user=arun, db=db)
    arun_loc_html = arun_loc.body.decode("utf-8")
    assert "Lakshmi has not shared location tracking with you" in arun_loc_html
    print("✓ Server-side enforcement: /location displays restricted message for Arun")

    # -------------------------------------------------------------------
    # TEST 5: Verify Read-Only Mode & Permission Enforcement for Arun
    # -------------------------------------------------------------------
    print("\n--- TEST 5: Verify Read-Only Permissions for Arun ---")
    arun_circle = circle_detail(make_request("/circle"), user=arun, db=db)
    arun_circle_html = arun_circle.body.decode("utf-8")
    assert "Granted Permissions (Read-Only)" in arun_circle_html, "Arun must see read-only badges"
    print("✓ Arun sees /circle in read-only mode")

    # Arun attempts to toggle permissions
    unauth_req = make_request(f"/circle/member/{ravi_mem.id}/toggle-permission", method="POST")
    try:
        toggle_permission(ravi_mem.id, PermissionToggle(permission="can_view_location", value=True), unauth_req, user=arun, db=db)
        assert False, "Should have raised HTTPException 403"
    except HTTPException as e:
        assert e.status_code == 403, f"Expected 403, got {e.status_code}"
        print("✓ Server blocks non-elder from modifying permissions (403 Forbidden)")

    # -------------------------------------------------------------------
    # TEST 6: Regenerate Passcode & Share Button
    # -------------------------------------------------------------------
    print("\n--- TEST 6: Regenerate Passcode and Share/Copy Button ---")
    old_passcode = circle.passcode
    regen_resp = regenerate_passcode(make_request("/circle/regenerate-passcode", method="POST"), user=lakshmi, db=db)
    assert regen_resp.status_code == 302

    db.expire_all()
    circle_regen = db.query(CareCircle).filter(CareCircle.id == circle.id).first()
    assert circle_regen.passcode != old_passcode, "Passcode should have changed"
    assert len(circle_regen.passcode) == 6, "Passcode must be 6 digits"
    print(f"✓ Passcode successfully regenerated from {old_passcode} to {circle_regen.passcode}")

    elder_circle = circle_detail(make_request("/circle"), user=lakshmi, db=db)
    elder_circle_html = elder_circle.body.decode("utf-8")
    assert "Share &amp; Copy" in elder_circle_html or "Share & Copy" in elder_circle_html
    assert "Regenerate" in elder_circle_html
    print("✓ Passcode card includes both 'Share & Copy' and 'Regenerate' buttons")

    db.close()
    print("\n=======================================================")
    print(" ALL 6 TEST PHASES PASSED WITH 100% SUCCESS! ")
    print("=======================================================\n")

if __name__ == "__main__":
    run_all_tests()
