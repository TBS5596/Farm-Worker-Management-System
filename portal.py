"""Worker self-service portal, served under /me.

A second, completely separate front door. The dashboard in `app.py` is for the
people who *run* the farm; this is for the people who *work* on it, and the two
must never be able to reach each other's pages.

Three rules hold this module together. Break any one of them and a worker can
read somebody else's wages:

  1. SEPARATE SESSION. A worker session sets `worker_logged_in`; the dashboard
     checks `admin_logged_in`. Nothing here ever writes an `admin_*` session
     key, so `@admin_required` can never be satisfied by a worker, and
     `@worker_required` can never be satisfied by a supervisor.

  2. EVERY QUERY IS SCOPED. No query in this file is written without a
     `worker_id == me.id` filter. `_me()` is the only way to learn who is
     signed in, and it re-reads the worker from the database on every request
     so that deactivating somebody takes effect immediately rather than at
     their next sign-in.

  3. MEDIA IS SCOPED TOO. `/captures/<path>` in app.py is admin-only and stays
     that way. A worker reaches their own attendance photo through
     `/me/snapshot/<id>`, which checks the snapshot belongs to them before
     serving a single byte.

Sign-in is worker code + PIN + a face match, in that order. The PIN alone was
never meant to protect anything more valuable than a clock-in - it is four
digits, it gets written on lists, and it gets typed at a shared terminal in
front of a queue. Putting wage history behind it alone would have been a
mistake, so the same recogniser that guards attendance guards the portal.
"""

from __future__ import annotations

import base64
import os
import threading
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_file, session, url_for)

import attendance_service
import face_engine
import payroll_engine
from database import db
from models import (Attendance, AuditLog, DailyAttendanceSummary,
                    EventSnapshot, Payroll, Setting, Worker)
from paths import BASE_DIR

portal = Blueprint("portal", __name__, url_prefix="/me")

# How long a portal session survives without a request. Workers use their own
# phones, so this is comfort rather than kiosk paranoia - but a phone left on a
# bench should not stay signed in all afternoon.
IDLE_TIMEOUT = timedelta(minutes=30)

PER_PAGE = 15

# Sign-in throttle. Five failures in fifteen minutes locks a worker code out
# for fifteen. Deliberately in memory: it costs no schema change and no write
# on every failed attempt. The honest limitation is that it is per-process and
# resets when the app restarts, which is acceptable here because the PIN is the
# weaker of two factors, not the only one.
_LOCK = threading.Lock()
_ATTEMPTS: dict[str, list[datetime]] = {}
MAX_ATTEMPTS = 5
ATTEMPT_WINDOW = timedelta(minutes=15)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def _flag(key: str, default: str = "on") -> bool:
    return _setting(key, default).strip().lower() in ("1", "true", "on", "yes")


def portal_enabled() -> bool:
    return _flag("portal_enabled", "on")


def portal_requires_face() -> bool:
    """Does portal sign-in need a face match?

    Deliberately its own setting rather than reusing
    `face_verification_required`. That one governs attendance, and a farm might
    switch it off to run a demonstration without a camera. If the portal shared
    it, that demonstration would silently drop wage history to PIN-only access.
    """
    return _flag("portal_require_face", "on")


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------

def _recent_failures(code: str) -> int:
    with _LOCK:
        cutoff = datetime.utcnow() - ATTEMPT_WINDOW
        kept = [t for t in _ATTEMPTS.get(code, []) if t > cutoff]
        _ATTEMPTS[code] = kept
        return len(kept)


def _record_failure(code: str) -> None:
    with _LOCK:
        _ATTEMPTS.setdefault(code, []).append(datetime.utcnow())


def _clear_failures(code: str) -> None:
    with _LOCK:
        _ATTEMPTS.pop(code, None)


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _sign_in(worker: Worker) -> None:
    session["worker_logged_in"] = True
    session["worker_pk"] = worker.id
    session["worker_code"] = worker.worker_id
    session["worker_name"] = worker.name
    session["worker_seen_at"] = datetime.utcnow().isoformat()


def _sign_out() -> None:
    for key in ("worker_logged_in", "worker_pk", "worker_code",
                "worker_name", "worker_seen_at"):
        session.pop(key, None)


def _me() -> Worker | None:
    """The signed-in worker, re-read from the database on every request.

    Re-reading rather than trusting the session is what makes a deactivation
    take effect at once: a supervisor who suspends somebody mid-shift does not
    have to wait for that person's session to expire.
    """
    pk = session.get("worker_pk")
    if not pk:
        return None
    worker = Worker.query.get(pk)
    if not worker or worker.status != "active":
        return None
    return worker


def _audit(action: str, details: str = "") -> None:
    """Audit trail entry attributed to a worker rather than a dashboard user.

    `app._log_audit` reads `admin_username` from the session and would record
    every portal action as "system". Portal entries are prefixed `worker:` so
    the two populations stay distinguishable in one log.
    """
    try:
        who = f"worker:{session.get('worker_code', '?')}"
        ip = request.remote_addr or "-"
    except RuntimeError:
        who, ip = "worker:?", "-"
    try:
        db.session.add(AuditLog(username=who, action=action, details=details, ip_address=ip))
        db.session.commit()
    except Exception:
        db.session.rollback()


def worker_required(f):
    """Require a signed-in, still-active worker with a live session.

    Note what this does NOT accept: an `admin_logged_in` session. A supervisor
    who wants to look at a worker's records uses the dashboard, which shows
    them in the context of the whole farm and audits the access.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not portal_enabled():
            abort(404)
        if not session.get("worker_logged_in"):
            return redirect(url_for("portal.login"))

        seen = session.get("worker_seen_at")
        try:
            last = datetime.fromisoformat(seen) if seen else None
        except (TypeError, ValueError):
            last = None
        if last is None or datetime.utcnow() - last > IDLE_TIMEOUT:
            _sign_out()
            flash("You were signed out after a period of inactivity.", "warning")
            return redirect(url_for("portal.login"))

        if _me() is None:
            _sign_out()
            flash("This worker record is no longer active. Speak to your supervisor.", "danger")
            return redirect(url_for("portal.login"))

        session["worker_seen_at"] = datetime.utcnow().isoformat()
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------

def _decode(raw_bytes: bytes):
    """Bytes of a JPEG or PNG into an OpenCV frame, or None."""
    try:
        import cv2
        import numpy as np
        buffer = np.frombuffer(raw_bytes, dtype=np.uint8)
        return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _submitted_frame():
    """The worker's photo, from whichever of the two capture paths the phone used.

    There are two because of a constraint that is easy to miss until it bites.
    Browsers only expose `getUserMedia` - the live in-page camera preview - in a
    *secure context*: HTTPS, or localhost. A farm serving this over plain HTTP
    at http://192.168.1.20:8010 is neither, so on that network
    `navigator.mediaDevices` is simply undefined and the pretty inline preview
    cannot work at all.

    So the primary path is a plain file input carrying `capture="user"`, which
    opens the phone's own camera app, needs no secure context, and works on any
    handset. The live preview is used only when the browser actually offers it
    (an HTTPS deployment, or a desktop at localhost), in which case the canvas
    frame arrives as a data URL instead.
    """
    upload = request.files.get("photo")
    if upload and upload.filename:
        return _decode(upload.read())

    raw = request.form.get("frame", "")
    if raw:
        try:
            payload = raw.split(",", 1)[1] if "," in raw else raw
            return _decode(base64.b64decode(payload))
        except Exception:
            return None
    return None


@portal.route("/", methods=["GET"])
def login():
    if not portal_enabled():
        abort(404)
    if session.get("worker_logged_in") and _me():
        return redirect(url_for("portal.dashboard"))
    return render_template("portal_login.html",
                           org_name=_setting("org_name", "FMS Farm"),
                           require_face=portal_requires_face())


@portal.route("/login", methods=["POST"])
def do_login():
    if not portal_enabled():
        abort(404)

    org = _setting("org_name", "FMS Farm")
    code = request.form.get("worker_id", "").strip().upper()
    pin = request.form.get("pin", "").strip()

    def refuse(message: str, category: str = "danger"):
        flash(message, category)
        return redirect(url_for("portal.login"))

    if not code or not pin:
        return refuse("Enter your Worker ID and PIN.")

    if _recent_failures(code) >= MAX_ATTEMPTS:
        return refuse("Too many failed attempts. Wait 15 minutes, or ask your "
                      "supervisor to reset your PIN.")

    worker = Worker.query.filter_by(worker_id=code).filter(Worker.status == "active").first()

    # One message for a bad code and a bad PIN, so the form cannot be used to
    # discover which worker codes exist.
    if not worker or not worker.check_pin(pin):
        _record_failure(code)
        return refuse("Worker ID or PIN is incorrect.")

    if portal_requires_face():
        if face_engine.sample_count_for(worker.id) == 0:
            return refuse("Your face is not enrolled yet, so you cannot sign in here. "
                          "Ask your supervisor to enrol you on the Biometric page.")

        frame = _submitted_frame()
        if frame is None:
            return refuse("No photo was captured. Tap the camera button, take a "
                          "photo of your face, then sign in.")

        threshold = attendance_service.match_threshold()
        result = face_engine.verify_worker(worker.id, [frame], threshold=threshold,
                                           require_eyes=_flag("face_require_eyes", "on"))
        attendance_service.log_transaction(
            worker.id, "portal_login", bool(result["matched"]),
            score=result["score"], threshold=threshold,
            error_message=None if result["matched"] else result["reason"],
        )
        if not result["matched"]:
            _record_failure(code)
            return refuse(attendance_service.REASON_MESSAGES.get(
                result["reason"], "Face verification failed. Please try again."))

    _clear_failures(code)
    _sign_in(worker)
    _audit("portal.login", f"{worker.worker_id} signed in to the worker portal")
    return redirect(url_for("portal.dashboard"))


@portal.route("/logout")
def logout():
    if session.get("worker_logged_in"):
        _audit("portal.logout", f"{session.get('worker_code')} signed out")
    _sign_out()
    flash("You have been signed out.", "success")
    return redirect(url_for("portal.login"))


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _shell(me: Worker, **extra) -> dict:
    return dict(me=me, org_name=_setting("org_name", "FMS Farm"), **extra)


@portal.route("/dashboard")
@worker_required
def dashboard():
    me = _me()
    today = date.today()
    week_from = today - timedelta(days=today.weekday())      # Monday
    month_from = today.replace(day=1)

    def totals(since: date) -> dict:
        rows = (DailyAttendanceSummary.query
                .filter(DailyAttendanceSummary.worker_id == me.id)
                .filter(DailyAttendanceSummary.summary_date >= since)
                .filter(DailyAttendanceSummary.summary_date <= today)
                .all())
        return {
            "days": len(rows),
            "hours": round(sum(r.total_hours or 0.0 for r in rows), 2),
            "overtime": round(sum(r.overtime_hours or 0.0 for r in rows), 2),
        }

    open_session = (Attendance.query
                    .filter(Attendance.worker_id == me.id)
                    .filter(Attendance.check_out_time.is_(None))
                    .order_by(Attendance.check_in_time.desc())
                    .first())

    recent = (Attendance.query
              .filter(Attendance.worker_id == me.id)
              .order_by(Attendance.check_in_time.desc())
              .limit(5).all())

    last_payslip = (Payroll.query
                    .filter(Payroll.worker_id == me.id)
                    .filter(Payroll.paid_status == "paid")
                    .order_by(Payroll.week_ending.desc())
                    .first())

    return render_template("portal_dashboard.html", **_shell(
        me,
        active="dashboard",
        week=totals(week_from),
        month=totals(month_from),
        open_session=open_session,
        recent=recent,
        last_payslip=last_payslip,
        period_label=payroll_engine.period_label,
        my_period=payroll_engine.PERIODS[payroll_engine.worker_period(me)]["label"],
        samples=face_engine.sample_count_for(me.id),
    ))


@portal.route("/attendance")
@worker_required
def attendance():
    me = _me()
    page = max(1, request.args.get("page", 1, type=int))

    pagination = (Attendance.query
                  .filter(Attendance.worker_id == me.id)
                  .order_by(Attendance.check_in_time.desc())
                  .paginate(page=page, per_page=PER_PAGE, error_out=False))

    # Snapshot ids for the rows on this page only, so the template can offer
    # each worker their own photo without a second query per row.
    ids = [row.attendance_id for row in pagination.items]
    shots: dict[int, int] = {}
    if ids:
        for shot in (EventSnapshot.query
                     .filter(EventSnapshot.attendance_id.in_(ids))
                     .order_by(EventSnapshot.captured_at.asc()).all()):
            shots.setdefault(shot.attendance_id, shot.snapshot_id)

    return render_template("portal_attendance.html", **_shell(
        me, active="attendance", pagination=pagination, shots=shots,
    ))


@portal.route("/payslips")
@worker_required
def payslips():
    me = _me()
    page = max(1, request.args.get("page", 1, type=int))

    # Paid weeks only. A pending row is still provisional - regenerating the
    # week can change it - and showing a worker a figure that later moves is
    # how a payroll system loses their trust.
    pagination = (Payroll.query
                  .filter(Payroll.worker_id == me.id)
                  .filter(Payroll.paid_status == "paid")
                  .order_by(Payroll.week_ending.desc())
                  .paginate(page=page, per_page=PER_PAGE, error_out=False))

    return render_template("portal_payslips.html", **_shell(
        me, active="payslips", pagination=pagination,
        period_label=payroll_engine.period_label,
    ))


@portal.route("/payslips/<int:payroll_id>")
@worker_required
def payslip(payroll_id: int):
    me = _me()
    # Scoped by worker AND by paid status: guessing another id gets a 404, not
    # somebody else's wages.
    row = (Payroll.query
           .filter(Payroll.payroll_id == payroll_id)
           .filter(Payroll.worker_id == me.id)
           .filter(Payroll.paid_status == "paid")
           .first_or_404())
    return render_template("portal_payslip.html", **_shell(
        me, active="payslips", row=row,
        period_label=payroll_engine.period_label,
    ))


@portal.route("/snapshot/<int:snapshot_id>")
@worker_required
def snapshot(snapshot_id: int):
    """Serve one attendance photo, and only to the worker it is of.

    `/captures/<path>` in app.py stays administrator-only. This route exists so
    a worker can see their own evidence without that one being relaxed: it
    joins the snapshot to its attendance row and refuses unless the row belongs
    to the signed-in worker.
    """
    me = _me()
    row = (db.session.query(EventSnapshot)
           .join(Attendance, EventSnapshot.attendance_id == Attendance.attendance_id)
           .filter(EventSnapshot.snapshot_id == snapshot_id)
           .filter(Attendance.worker_id == me.id)
           .first())
    if not row or not row.file_path:
        abort(404)

    full = os.path.normpath(os.path.join(BASE_DIR, row.file_path))
    if not full.startswith(BASE_DIR) or not os.path.exists(full):
        abort(404)
    return send_file(full)
