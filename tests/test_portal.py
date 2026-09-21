"""Worker self-service portal (/me).

The tests that matter most here are not the ones that check a page renders.
They are the ones that check a worker CANNOT reach what is not theirs, because
this is the first feature in the system where two different populations share
one application, and the whole design rests on those two populations never
being able to satisfy each other's checks.
"""

from datetime import date, datetime, timedelta

import pytest

import portal
from database import db
from models import Attendance, EventSnapshot, Payroll, Worker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def portal_worker(app_context, make_worker, setting):
    """A worker who can sign in: active, with a PIN, face check switched off.

    The face path is exercised separately; switching it off here keeps the
    scoping tests focused on scoping rather than on the recogniser.
    """
    setting("portal_enabled", "on")
    setting("portal_require_face", "off")
    portal._ATTEMPTS.clear()
    return make_worker(name="Portal Tester", pin="4321")


def _sign_in_worker(client, worker, pin="4321"):
    return client.post("/me/login",
                       data={"worker_id": worker.worker_id, "pin": pin},
                       follow_redirects=False)


def _attendance(worker, day_offset=0, hours=8):
    start = datetime.utcnow() - timedelta(days=day_offset)
    row = Attendance(worker_id=worker.id, check_in_time=start,
                     check_out_time=start + timedelta(hours=hours),
                     verified_by_face=True, check_in_match_score=71.0)
    db.session.add(row)
    db.session.commit()
    return row


def _payroll(worker, week_ending, net=800.0, status="paid"):
    row = Payroll(worker_id=worker.id, week_ending=week_ending, total_hours=40.0,
                  overtime_hours=0.0, hourly_rate=20.0, gross_pay=800.0,
                  napsa_rate=0.05, nhima_rate=0.01, napsa_deduction=40.0,
                  nhima_deduction=8.0, net_pay=net, paid_status=status)
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------

def test_the_portal_sign_in_page_is_reachable(client, portal_worker):
    assert client.get("/me/").status_code == 200


def test_a_correct_id_and_pin_signs_the_worker_in(client, portal_worker):
    response = _sign_in_worker(client, portal_worker)
    assert response.status_code == 302
    assert "/me/dashboard" in response.headers["Location"]
    with client.session_transaction() as session:
        assert session["worker_logged_in"] is True
        assert session["worker_pk"] == portal_worker.id


def test_a_wrong_pin_is_refused(client, portal_worker):
    _sign_in_worker(client, portal_worker, pin="0000")
    with client.session_transaction() as session:
        assert "worker_logged_in" not in session


def test_an_inactive_worker_cannot_sign_in(client, app_context, make_worker, setting):
    setting("portal_require_face", "off")
    portal._ATTEMPTS.clear()
    worker = make_worker(name="Left The Farm", pin="4321", status="inactive")
    _sign_in_worker(client, worker)
    with client.session_transaction() as session:
        assert "worker_logged_in" not in session


def test_repeated_failures_lock_the_code_out(client, portal_worker):
    for _ in range(portal.MAX_ATTEMPTS):
        _sign_in_worker(client, portal_worker, pin="0000")
    # Even the correct PIN is refused once the throttle has tripped.
    _sign_in_worker(client, portal_worker, pin="4321")
    with client.session_transaction() as session:
        assert "worker_logged_in" not in session


def test_sign_in_needs_a_face_when_the_setting_is_on(client, portal_worker, setting):
    setting("portal_require_face", "on")
    portal._ATTEMPTS.clear()
    # Correct credentials, no photo: refused, because the PIN alone is not
    # enough to open wage history.
    _sign_in_worker(client, portal_worker)
    with client.session_transaction() as session:
        assert "worker_logged_in" not in session


def test_signing_out_clears_the_session(client, portal_worker):
    _sign_in_worker(client, portal_worker)
    client.get("/me/logout")
    with client.session_transaction() as session:
        assert "worker_logged_in" not in session
        assert "worker_pk" not in session


# ---------------------------------------------------------------------------
# The isolation that the whole design rests on
# ---------------------------------------------------------------------------

ADMIN_ROUTES = ["/dashboard", "/workers", "/attendance", "/payroll", "/cctv",
                "/biometric", "/users", "/audit-log", "/settings", "/tables-hub",
                "/cloud-sync"]


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_a_signed_in_worker_cannot_reach_any_admin_page(client, portal_worker, route):
    """A worker session must never satisfy @admin_required.

    This is the single most important test in the file. The dashboard checks
    `admin_logged_in`; the portal sets `worker_logged_in` and never writes an
    admin key. If that ever changes, every one of these turns red.
    """
    _sign_in_worker(client, portal_worker)
    response = client.get(route)
    assert response.status_code == 302, f"{route} should have redirected"
    assert "/me/" not in response.headers["Location"]


def test_a_worker_cannot_read_capture_files_through_the_admin_route(client, portal_worker):
    _sign_in_worker(client, portal_worker)
    response = client.get("/captures/faces/anything.jpg")
    assert response.status_code == 302        # bounced to the admin login


def test_an_admin_session_does_not_open_the_portal(client, signed_in, portal_worker):
    """And the reverse: a supervisor is not a worker.

    An administrator who wants to see somebody's records uses the dashboard,
    where the access is audited and shown in the context of the whole farm.
    """
    signed_in("admin")
    response = client.get("/me/dashboard")
    assert response.status_code == 302
    assert "/me/" in response.headers["Location"]


def test_the_portal_can_be_switched_off_entirely(client, portal_worker, setting):
    _sign_in_worker(client, portal_worker)
    setting("portal_enabled", "off")
    assert client.get("/me/dashboard").status_code == 404


# ---------------------------------------------------------------------------
# Scoping: a worker sees their own records and nobody else's
# ---------------------------------------------------------------------------

def test_attendance_shows_only_this_workers_records(client, portal_worker, make_worker):
    other = make_worker(name="Somebody Else", pin="9876")
    _attendance(portal_worker, day_offset=1)
    _attendance(other, day_offset=1)
    _attendance(other, day_offset=2)

    _sign_in_worker(client, portal_worker)
    body = client.get("/me/attendance").get_data(as_text=True)
    assert "Somebody Else" not in body
    # One record in total, not three.
    assert "1 record" in body


def test_payslips_show_only_this_workers_rows(client, portal_worker, make_worker):
    other = make_worker(name="Somebody Else", pin="9876")
    _payroll(portal_worker, date(2026, 8, 23), net=111.11)
    _payroll(other, date(2026, 8, 23), net=999.99)

    _sign_in_worker(client, portal_worker)
    body = client.get("/me/payslips").get_data(as_text=True)
    assert "111.11" in body
    assert "999.99" not in body


def test_another_workers_payslip_is_not_reachable_by_id(client, portal_worker, make_worker):
    other = make_worker(name="Somebody Else", pin="9876")
    theirs = _payroll(other, date(2026, 8, 23), net=999.99)

    _sign_in_worker(client, portal_worker)
    assert client.get(f"/me/payslips/{theirs.payroll_id}").status_code == 404


def test_unpaid_weeks_are_hidden(client, portal_worker):
    _payroll(portal_worker, date(2026, 8, 16), net=500.00, status="paid")
    pending = _payroll(portal_worker, date(2026, 8, 23), net=612.00, status="pending")

    _sign_in_worker(client, portal_worker)
    body = client.get("/me/payslips").get_data(as_text=True)
    assert "500.00" in body
    assert "612.00" not in body
    # And not reachable directly either.
    assert client.get(f"/me/payslips/{pending.payroll_id}").status_code == 404


def test_a_worker_cannot_open_another_workers_snapshot(client, portal_worker, make_worker):
    other = make_worker(name="Somebody Else", pin="9876")
    row = _attendance(other, day_offset=1)
    shot = EventSnapshot(attendance_id=row.attendance_id, snapshot_type="photo_check_in",
                         file_path="captures/other.jpg")
    db.session.add(shot)
    db.session.commit()

    _sign_in_worker(client, portal_worker)
    assert client.get(f"/me/snapshot/{shot.snapshot_id}").status_code == 404


# ---------------------------------------------------------------------------
# Pages render
# ---------------------------------------------------------------------------

def test_the_dashboard_shows_the_workers_own_details(client, portal_worker):
    _sign_in_worker(client, portal_worker)
    body = client.get("/me/dashboard").get_data(as_text=True)
    assert "Portal Tester" in body
    assert portal_worker.worker_id in body


def test_attendance_paginates(client, portal_worker):
    for day in range(portal.PER_PAGE + 4):
        _attendance(portal_worker, day_offset=day + 1)
    _sign_in_worker(client, portal_worker)

    first = client.get("/me/attendance").get_data(as_text=True)
    assert "Page 1 of 2" in first
    second = client.get("/me/attendance?page=2")
    assert second.status_code == 200
    assert "Page 2 of 2" in second.get_data(as_text=True)


def test_signed_out_visitors_are_sent_to_the_portal_sign_in(client, portal_worker):
    for route in ("/me/dashboard", "/me/attendance", "/me/payslips"):
        response = client.get(route)
        assert response.status_code == 302
        assert "/me/" in response.headers["Location"]
