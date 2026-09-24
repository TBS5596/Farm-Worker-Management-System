"""Farm Worker Management System - Flask application.

Route layer only. The work lives in focused modules:

    face_engine.py        enrolment and identity verification
    attendance_service.py the clock-in / clock-out pipeline
    cctv_engine.py        camera sources, streaming, clips, health
    payroll_engine.py     daily summaries and computed payroll
    geofence.py           location checks
    sync_engine.py        cloud upload with an offline queue
    security.py           role-based access control
    exports.py            CSV exports
    api.py                JSON API (/api/v1)
"""

import json
import os
import secrets
import string
import hashlib
from datetime import date, datetime, timedelta

from flask import (
    Flask, Response, abort, flash, redirect, render_template, request,
    send_from_directory, session, url_for,
)

import barcode_engine
import cctv_engine
import exports
import face_engine
import geofence
import payroll_engine
import reports_engine
import sync_engine
from api import api as api_blueprint
from portal import portal as portal_blueprint
from attendance_service import match_threshold, record_punch
from database import db
from migrations import apply_migrations
from models import (
    Attendance,
    AuditLog,
    BiometricDevice,
    BiometricTransaction,
    CCTVFeed,
    CCTVRecording,
    CloudSyncMetadata,
    DailyAttendanceSummary,
    EventSnapshot,
    FaceTemplate,
    HardwareHealthLog,
    OfflineSyncQueue,
    Payroll,
    Setting,
    User,
    Worker,
)
from paths import BASE_DIR, CAPTURES_DIR, CLIPS_DIR, FACES_DIR, ensure_dirs
from security import (
    ATTENDANCE_MANAGE,
    BIOMETRIC_MANAGE,
    CCTV_MANAGE,
    PAYROLL_MANAGE,
    ROLE_LABELS,
    SETTINGS_MANAGE,
    SYNC_MANAGE,
    USER_MANAGE,
    WORKER_MANAGE,
    admin_required,
    can,
    normalize_role,
    permission_required,
)

# Upper bound per worker. More samples make matching more robust, but each one
# is a 40 KB row and a longer training pass, and the gain flattens off after
# about five. Three is treated as the practical minimum throughout the UI.
MAX_ENROLL_SAMPLES = 8


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def _resolve_secret_key() -> str:
    """A stable secret key, so a restart does not log everybody out.

    Order: FMS_SECRET_KEY env var, then a generated key cached beside the app.
    """
    from_env = os.environ.get("FMS_SECRET_KEY", "").strip()
    if from_env:
        return from_env

    key_path = os.path.join(BASE_DIR, ".secret_key")
    try:
        if os.path.exists(key_path):
            cached = open(key_path, "r", encoding="utf-8").read().strip()
            if cached:
                return cached
        generated = secrets.token_hex(32)
        with open(key_path, "w", encoding="utf-8") as handle:
            handle.write(generated)
        os.chmod(key_path, 0o600)
        return generated
    except OSError:
        return secrets.token_hex(32)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = _resolve_secret_key()
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "FMS_DATABASE_URI", f"sqlite:///{os.path.join(BASE_DIR, 'fms.db')}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # enrolment photo uploads

    db.init_app(app)

    with app.app_context():
        db.create_all()
        changes = apply_migrations()
        if changes:
            app.logger.info("Schema migrations applied: %s", ", ".join(changes))
        _seed_defaults()

    ensure_dirs()

    app.jinja_env.globals.update(
        can=can,
        role_labels=ROLE_LABELS,
        face_engine_info=face_engine.engine_info,
    )

    app.register_blueprint(api_blueprint)
    # The worker self-service portal at /me. A separate blueprint, and a
    # separate session: nothing under /me can satisfy @admin_required, and
    # nothing on the dashboard can satisfy @worker_required.
    app.register_blueprint(portal_blueprint)
    _register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

DEFAULT_SETTINGS = {
    "org_name": "FMS Farm",
    # Camera
    "camera_index": "0",
    "camera_sources": "",
    # Face verification
    "face_match_threshold": "35",
    "face_verification_required": "on",
    "face_require_eyes": "on",
    # Location
    "farm_latitude": "",
    "farm_longitude": "",
    "geofence_radius_m": "500",
    "geofence_enforce": "off",
    # Payroll
    # The farm-wide pay cycle. Any worker can override it on their own record;
    # a blank override means "use this". weekly | fortnightly | semi-monthly | monthly
    "payroll_period": "weekly",
    "standard_day_hours": "8",
    "overtime_multiplier": "1.5",
    "napsa_rate": "0.05",
    "nhima_rate": "0.01",
    "default_hourly_rate": "15",
    "shift_start_time": "07:00",
    "shift_end_time": "17:00",
    # Identity card / barcode
    # Turning this on adds a third factor at the capture point: the card is
    # something the worker HAS, the PIN something they KNOW, the face
    # something they ARE.
    "barcode_enabled": "off",
    # What the printed barcode actually contains. The three options trade
    # convenience against exposure, and the farm chooses:
    #   nrc_plain   the National Registration Number itself. This is what a
    #               scan of a dropped card reveals, so it exposes a national
    #               identifier to anyone who picks the card up.
    #   nrc_hash    a one-way scramble of the NRC. Unique per person and tied
    #               to the NRC, but the NRC cannot be recovered from it.
    #   card_number a generated code meaning nothing outside this system, and
    #               the only option under which a lost card can be voided and
    #               reissued without changing the worker's identity.
    "barcode_source": "nrc_plain",
    # code128 prints as a classic striped barcode and suits a cheap laser
    # scanner; qr survives a creased card better and is readable by a phone.
    "barcode_symbology": "code128",
    # Whether the PIN is still required once a card has been scanned. On by
    # default, because the three-factor claim depends on it. A farm with a long
    # queue at the gate can switch it off and fall back to card plus face.
    "barcode_require_pin": "on",
    # Allow a supervisor to read a card with the device camera instead of a
    # dedicated scanner.
    "barcode_camera_scan": "on",
    # How often a page carrying charts reloads itself, in seconds. 0 is off.
    # A farm office leaves the dashboard open all day, so a stale screen is the
    # common failure; a viewer can override this for their own browser.
    "chart_refresh_seconds": "0",
    # Recording
    "clip_recording_enabled": "on",
    "clip_seconds": "6",
    # Worker self-service portal (/me)
    "portal_enabled": "on",
    # Kept separate from face_verification_required on purpose: switching
    # attendance verification off for a demonstration must not silently drop
    # the portal to PIN-only access to wage history.
    "portal_require_face": "on",
    # Cloud
    "firebase_bucket": "",
    "firebase_project_id": "",
    "firebase_credentials_json": "",
}


def _seed_defaults() -> None:
    """Create the default admin, settings rows and baseline camera feed."""
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            name="System Administrator",
            email="admin@example.com",
            phone="0000000000",
            role="admin",
            is_active=True,
            must_change_password=True,  # forced change on first login
        )
        admin.set_password("admin")
        db.session.add(admin)

    for key, value in DEFAULT_SETTINGS.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))

    if not Setting.query.filter_by(key="api_key").first():
        db.session.add(Setting(key="api_key", value=secrets.token_urlsafe(24)))

    db.session.commit()

    # Nobody may be locked out by the new permission checks.
    for user in User.query.all():
        if (user.role or "").strip().lower() not in ROLE_LABELS:
            user.role = "admin"
    db.session.commit()

    # A database created before roles were enforced can easily have no
    # administrator at all - the first release defaulted every account to
    # 'supervisor'. Promote one so Users and Settings stay reachable.
    if not User.query.filter_by(role="admin", is_active=True).first():
        candidate = (User.query.filter_by(username="admin").first()
                     or User.query.order_by(User.id.asc()).first())
        if candidate:
            candidate.role = "admin"
            candidate.is_active = True
            db.session.commit()

    _backfill_payroll_periods()
    _ensure_default_cctv_entries()


def _backfill_payroll_periods() -> None:
    """Stamp legacy payroll rows as the weeks they actually were.

    Every row written before pay cycles existed covered the seven days ending
    on week_ending, because that was the only period the system had. Leaving
    period_type NULL would make a mixed history unreadable - a payslip list
    cannot say whether 875 was a week or a month - so the rows are labelled
    once, here.

    Idempotent: it only touches rows that have no period_type, so a second
    start-up finds nothing to do.
    """
    stale = Payroll.query.filter(Payroll.period_type.is_(None)).all()
    if not stale:
        return
    for row in stale:
        row.period_type = "weekly"
        if row.period_start is None and row.week_ending:
            row.period_start = row.week_ending - timedelta(days=6)
    db.session.commit()


def _ensure_default_cctv_entries() -> None:
    """Ensure the local camera is registered as a watchable feed."""
    camera_index = _get_setting("camera_index", "0").strip() or "0"
    builtin_url = f"builtin://{camera_index}"

    feed = CCTVFeed.query.filter_by(rtsp_url=builtin_url).first()
    if not feed:
        feed = CCTVFeed(
            camera_name=f"Built-in Camera {camera_index}",
            camera_location="Local Device",
            rtsp_url=builtin_url,
            status="online",
            last_heartbeat=datetime.utcnow(),
        )
        db.session.add(feed)
        db.session.flush()

    if not CCTVFeed.query.filter_by(is_primary=True).first():
        feed.is_primary = True

    db.session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_setting(key: str, default: str = "") -> str:
    """Read one settings row.

    An empty string counts as unset and falls back to `default`, which is why a
    cleared field in the Settings form behaves the same as a missing row.

        _get_setting("org_name", "FMS Farm")   -> "Chisamba Green Farms"
        _get_setting("farm_latitude")          -> "" when never configured
    """
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def _save_settings(values: dict) -> None:
    """Upsert several settings in one transaction.

        _save_settings({"geofence_enforce": "on", "geofence_radius_m": "300"})
    """
    for key, value in values.items():
        row = Setting.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))
    db.session.commit()


def _generate_password(length: int = 8) -> str:
    """A temporary password for a new or reset account, e.g. "T7hQ2mVx91".

    Shown once in a flash message and never stored in plain text. The account
    is flagged must_change_password, so it cannot be used indefinitely.
    """
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _log_audit(action: str, details: str = "") -> None:
    """Append to the audit trail.

        _log_audit("worker.add", "Added worker 0009 - Moses Banda")

    Safe to call anywhere: outside a request there is no session or IP, so it
    records the actor as "system". A failure here must never break the action
    being audited, hence the broad rollback.
    """
    try:
        username = session.get("admin_username", "system")
        ip = request.remote_addr or "-"
    except RuntimeError:
        username, ip = "system", "-"
    try:
        db.session.add(AuditLog(username=username, action=action, details=details, ip_address=ip))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _pin_fingerprint(pin: str) -> str:
    """SHA-256 of a PIN, used only to enforce PIN uniqueness across workers.

    Not a biometric: the biometric template lives in `face_templates`.
    """
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def _is_pin_unique(pin: str, exclude_worker_id: str | None = None) -> bool:
    """True when no other worker already uses this PIN.

    Shared PINs would make the ID+PIN half of a clock-in ambiguous, so they are
    refused. `exclude_worker_id` lets a worker keep their own PIN while being
    edited:

        _is_pin_unique("4321")                            -> False if taken
        _is_pin_unique("4321", exclude_worker_id="0003")  -> True for 0003
    """
    query = Worker.query.filter_by(pin_fingerprint=_pin_fingerprint(pin))
    if exclude_worker_id:
        query = query.filter(Worker.worker_id != exclude_worker_id)
    return query.first() is None


def _generate_worker_id() -> str:
    """The next free 4-digit worker code: "0001", "0002", ...

    Takes the highest numeric code in use and counts up, then confirms the
    candidate is actually free - so an imported record already holding "0002"
    is skipped rather than colliding. Non-numeric legacy codes are ignored when
    finding the maximum.
    """
    max_seq = 0
    for row in Worker.query.with_entities(Worker.worker_id).all():
        existing = (row.worker_id or "").strip()
        if existing.isdigit():
            max_seq = max(max_seq, int(existing))

    next_seq = max_seq + 1
    if next_seq > 9999:
        raise ValueError("Worker ID sequence exceeded 4 digits")
    while True:
        candidate = f"{next_seq:04d}"
        if not Worker.query.filter_by(worker_id=candidate).first():
            return candidate
        next_seq += 1


def _parse_date(raw: str, fallback: date | None = None) -> date | None:
    """Parse an HTML date input ("2026-08-23"), or return the fallback.

    Returning None rather than raising lets each route decide whether a bad
    date is an error to report or a field to ignore.
    """
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _float_or_none(raw):
    """Parse a number from a form field, or None.

    None is meaningful here: a blank hourly rate means "use the default rate
    from Settings", which is different from a rate of zero.
    """
    try:
        value = float(raw)
        return value
    except (TypeError, ValueError):
        return None


def _build_attendance_sessions(rows: list[Attendance]) -> list:
    """Build display sessions from Attendance rows, newest first."""
    # Three bulk queries instead of per-row lookups. The first release did a
    # query per row for the worker and another for its snapshots, so a 400-row
    # page issued about 800 queries; this issues three.
    worker_lookup = {w.id: w for w in Worker.query.all()}

    attendance_ids = [row.attendance_id for row in rows]
    snapshots_by_attendance: dict[int, list] = {}
    if attendance_ids:
        snapshot_rows = (EventSnapshot.query
                         .filter(EventSnapshot.attendance_id.in_(attendance_ids))
                         .order_by(EventSnapshot.captured_at.asc()).all())
        for snapshot in snapshot_rows:
            snapshots_by_attendance.setdefault(snapshot.attendance_id, []).append(snapshot)

    clips_by_attendance: dict[int, str] = {}
    if attendance_ids:
        clip_rows = (CCTVRecording.query
                     .filter(CCTVRecording.attendance_id.in_(attendance_ids))
                     .order_by(CCTVRecording.recording_id.asc()).all())
        for clip in clip_rows:
            clips_by_attendance[clip.attendance_id] = clip.recording_path

    sessions = []
    for row in rows:
        worker = worker_lookup.get(row.worker_id)
        worker_code = worker.worker_id if worker else f"W{row.worker_id}"
        snapshots = snapshots_by_attendance.get(row.attendance_id, [])

        in_image = next((s.file_path for s in snapshots if "check_in" in (s.snapshot_type or "")), None)
        out_image = next((s.file_path for s in snapshots if "check_out" in (s.snapshot_type or "")), None)
        # Backward compatibility: snapshots recorded before the type was stored
        # have a plain "photo" type, so fall back to first-as-in, last-as-out.
        if not in_image and snapshots:
            in_image = snapshots[0].file_path
        if not out_image and len(snapshots) > 1:
            out_image = snapshots[-1].file_path

        hours = None
        if row.check_in_time and row.check_out_time:
            hours = round((row.check_out_time - row.check_in_time).total_seconds() / 3600.0, 2)

        sessions.append({
            "attendance_id": row.attendance_id,
            "worker_id": worker_code,
            "worker_name": worker.name if worker else worker_code,
            "date": row.check_in_time.strftime("%d %b %Y") if row.check_in_time else "-",
            "clock_in_time": row.check_in_time.strftime("%H:%M:%S") if row.check_in_time else None,
            "clock_in_image": in_image,
            "clock_out_time": row.check_out_time.strftime("%H:%M:%S") if row.check_out_time else None,
            "clock_out_image": out_image,
            "hours": hours,
            "verified_by_face": bool(row.verified_by_face),
            "match_score": row.check_in_match_score,
            "within_geofence": row.within_geofence,
            "distance_m": row.distance_from_farm_m,
            "clip_path": clips_by_attendance.get(row.attendance_id),
            "_sort_key": row.check_out_time or row.check_in_time,
        })

    sessions.sort(key=lambda item: item["_sort_key"], reverse=True)
    return sessions


def _stream_response(source, overlay: bool = True) -> Response:
    fallback = cctv_engine.fallback_source()
    return Response(
        cctv_engine.frame_generator(source, fallback, overlay_faces=overlay, overlay_motion=overlay),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


def _real_recordings(limit: int = 150):
    """Exclude the legacy `default://` marker rows from the UI."""
    return (CCTVRecording.query
            .filter(~CCTVRecording.recording_path.like("default://%"))
            .order_by(CCTVRecording.recording_id.desc()).limit(limit).all())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: Flask) -> None:

    @app.before_request
    def _enforce_password_change():
        """Lock the dashboard for anyone still on a temporary password.

        Without this, the shipped admin/admin could be left in place forever.
        The allow-list is the minimum needed to actually change it, plus logout
        and the public manual.
        """
        """A signed-in user with a temporary password can only change it."""
        if not session.get("admin_logged_in") or not session.get("must_change_password"):
            return None
        allowed = {"force_password_change", "change_password", "logout", "manual", "static"}
        if (request.endpoint or "") in allowed:
            return None
        return redirect(url_for("force_password_change"))

    # ---- Files ----------------------------------------------------------- #

    # Serves attendance snapshots, enrolment reference crops and event clips
    # from captures/. Sign-in required: these are photographs of workers.
    # The <path:> converter allows the subdirectories, e.g.
    # /captures/clips/clip_20260828_071205_attendance_in.mp4
    @app.route("/captures/<path:filename>")
    @admin_required
    def captured_image(filename):
        return send_from_directory(CAPTURES_DIR, filename)

    @app.route("/worker-camera-stream")
    def worker_camera_stream():
        """Public preview feed for the worker clock-in page."""
        return _stream_response(cctv_engine.primary_source()["source"])

    @app.route("/camera-stream/<int:camera_idx>")
    @admin_required
    def camera_stream(camera_idx: int):
        sources = cctv_engine.get_camera_sources()
        if camera_idx < 0 or camera_idx >= len(sources):
            abort(404)
        return _stream_response(sources[camera_idx]["source"])

    # ---- Login / Logout -------------------------------------------------- #

    @app.context_processor
    def _inject_chart_refresh():
        """Available to every template, so no page can forget to pass it."""
        try:
            seconds = int(_get_setting("chart_refresh_seconds", "0") or 0)
        except (TypeError, ValueError):
            seconds = 0
        return {"chart_refresh_seconds": max(0, seconds)}

    def _clock_context() -> dict:
        """Everything login.html needs to draw the capture point.

        Gathered in one place because the route renders the page from four
        different branches, and an omission in any of them would silently drop
        the card field - the failure would look like the feature not working
        rather than like a bug.
        """
        cards_on = _get_setting("barcode_enabled", "off") == "on"
        return {
            "org_name": _get_setting("org_name", "FMS Farm"),
            "cards_enabled": cards_on,
            "card_require_pin": (not cards_on)
                                or _get_setting("barcode_require_pin", "on") == "on",
            "card_camera": cards_on
                           and _get_setting("barcode_camera_scan", "on") == "on",
        }

    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            mode = request.form.get("mode")

            if mode == "admin":
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                user = User.query.filter_by(username=username).first()
                if user and user.check_password(password):
                    if not user.is_active:
                        flash("That account has been deactivated. Contact an administrator.", "danger")
                        return render_template("login.html", **_clock_context())
                    session["admin_logged_in"] = True
                    session["admin_username"] = username
                    session["admin_user_id"] = user.id
                    session["admin_role"] = normalize_role(user.role)
                    session["must_change_password"] = bool(user.must_change_password)
                    user.last_login_at = datetime.utcnow()
                    db.session.commit()
                    _log_audit("login", f"Admin '{username}' logged in as {session['admin_role']}")
                    if user.must_change_password:
                        return redirect(url_for("force_password_change"))
                    return redirect(url_for("dashboard"))
                flash("Invalid admin credentials.", "danger")

            # --- Worker clock in / clock out -------------------------------
            # No session is created: a worker never signs in to the dashboard.
            # Credentials are checked here, then record_punch does the identity
            # match, the geofence check and the recording.
            elif mode == "worker":
                worker_code = request.form.get("worker_id", "").strip().upper()
                pin = request.form.get("pin", "").strip()
                card_code = request.form.get("card_code", "")
                log_type = request.form.get("log_type", "IN")
                lat, lon = geofence.normalize_coordinates(
                    request.form.get("latitude"), request.form.get("longitude")
                )

                cards_on = _get_setting("barcode_enabled", "off") == "on"
                pin_required = (not cards_on) or _get_setting("barcode_require_pin", "on") == "on"

                # --- Factor one: the card, something the worker HAS ---------
                # A scanned card identifies the worker outright, so the worker
                # number below becomes a fallback rather than the way in. The
                # fallback is kept deliberately: a camera failure must not stop
                # a worker being paid, and neither must a card left at home.
                # Card-less punches are marked in the audit trail so a farm can
                # see how often the third factor was actually skipped.
                worker = None
                via_card = False
                if cards_on and barcode_engine.normalize_scan(card_code):
                    worker, reason = barcode_engine.resolve(card_code)
                    if worker is None:
                        flash(barcode_engine.CARD_REASON_MESSAGES.get(
                            reason, "That card could not be read."), "danger")
                        _log_audit("attendance.rejected",
                                   f"Card refused at capture point: {reason}")
                        return render_template("login.html", **_clock_context())
                    via_card = True
                    # The card wins over anything typed in the worker field, so
                    # a stale value left on a shared terminal cannot redirect a
                    # scan to somebody else's record.
                    worker_code = worker.worker_id

                if worker is None:
                    worker = (Worker.query.filter_by(worker_id=worker_code)
                              .filter(Worker.status == "active").first())

                # --- Factor two: the PIN, something the worker KNOWS --------
                if worker is None or (pin_required and not worker.check_pin(pin)):
                    flash("Worker ID or PIN is incorrect.", "danger")
                    return render_template("login.html", **_clock_context())

                # --- Factor three: the face, something the worker IS --------
                # record_punch does the match, the geofence check and the write.
                outcome = record_punch(app, worker, log_type, lat, lon)
                flash(outcome["message"], outcome["category"])
                if outcome["ok"]:
                    _log_audit("attendance.recorded",
                               f"{outcome['log_type']} for {worker_code} "
                               f"(attendance_id={outcome['attendance_id']}, "
                               f"match={outcome['score']}, "
                               f"card={'scanned' if via_card else 'not used'})")
                else:
                    _log_audit("attendance.rejected",
                               f"{outcome['log_type']} refused for {worker_code}: {outcome['code']}")

        return render_template("login.html", **_clock_context())

    @app.route("/logout")
    def logout():
        _log_audit("logout", f"Admin '{session.get('admin_username', '?')}' logged out")
        session.clear()
        return redirect(url_for("login"))

    @app.route("/profile/password-change", methods=["GET"])
    @admin_required
    def force_password_change():
        return render_template(
            "force_password_change.html",
            active_page="dashboard",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/profile/change-password", methods=["POST"])
    @admin_required
    def change_password():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        username = session.get("admin_username")
        user = User.query.filter_by(username=username).first()

        target = url_for("force_password_change") if session.get("must_change_password") \
            else (request.referrer or url_for("dashboard"))

        if not user or not user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(target)
        if len(new_password) < 8:
            flash("New password must be at least 8 characters.", "danger")
            return redirect(target)
        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(target)
        if new_password == current_password:
            flash("New password must be different from the current one.", "danger")
            return redirect(target)

        user.set_password(new_password)
        user.must_change_password = False
        db.session.commit()
        session["must_change_password"] = False
        _log_audit("user.change_password", f"'{username}' changed own password")
        flash("Password changed successfully.", "success")
        return redirect(url_for("dashboard"))

    # ---- Dashboard -------------------------------------------------------- #

    @app.route("/dashboard")
    @admin_required
    def dashboard():
        workers = Worker.query.order_by(Worker.created_at.desc()).all()
        active_workers_count = sum(1 for w in workers if (w.status or "").lower() == "active")
        attendance_rows = Attendance.query.order_by(Attendance.check_in_time.desc()).limit(400).all()
        sessions = _build_attendance_sessions(attendance_rows)
        today_count = sum(1 for s in sessions if s["_sort_key"] and s["_sort_key"].date() == date.today())

        # sample_counts() is one grouped query returning {worker.id: samples},
        # e.g. {1: 3, 2: 3, 7: 0} - so the "faces enrolled" figure and the
        # per-row badges cost a single query rather than one per worker.
        enrolled = face_engine.sample_counts()
        farm_lat, farm_lon = geofence.farm_centre()

        return render_template(
            "dashboard.html",
            workers=workers,
            active_workers_count=active_workers_count,
            sessions=sessions,
            today_count=today_count,
            camera_sources=cctv_engine.get_camera_sources(),
            enrolled_count=sum(1 for w in workers if enrolled.get(w.id, 0) > 0),
            verification=face_engine.accuracy_snapshot(),
            engine=face_engine.engine_info(),
            sync_stats=sync_engine.queue_stats(),
            open_sessions=sum(1 for s in sessions if s["clock_in_time"] and not s["clock_out_time"]),
            geofence_ready=farm_lat is not None and farm_lon is not None,
            geofence_enforced=geofence.is_enforced(),
            trend=payroll_engine.attendance_trend(14),
            active_page="dashboard",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    # ---- Workers ---------------------------------------------------------- #

    @app.route("/workers", methods=["GET", "POST"])
    @admin_required
    def workers_page():
        if request.method == "POST":
            flash("Form target was outdated. Please retry the action.", "warning")
            return redirect(url_for("workers_page"))

        workers = Worker.query.order_by(Worker.created_at.desc()).all()
        return render_template(
            "workers.html",
            workers=workers,
            face_samples=face_engine.sample_counts(),
            default_rate=payroll_engine.rates()["default_hourly_rate"],
            periods=payroll_engine.PERIODS,
            farm_period=payroll_engine.farm_period(),
            cards_enabled=_get_setting("barcode_enabled", "off") == "on",
            card_source=_get_setting("barcode_source", barcode_engine.DEFAULT_SOURCE),
            card_stats=barcode_engine.stats(),
            active_page="workers",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/workers/add", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def add_worker():
        name = request.form.get("name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        pin = request.form.get("pin", "").strip()
        nrc_number = request.form.get("nrc_number", "").strip()

        if not name or not pin or not phone_number:
            flash("Name, Phone Number, and PIN are all required.", "danger")
            return redirect(url_for("workers_page"))
        if len(pin) < 4:
            flash("PIN must be at least 4 digits.", "danger")
            return redirect(url_for("workers_page"))
        if not _is_pin_unique(pin):
            flash("PIN already exists. Choose a unique PIN for each worker.", "danger")
            return redirect(url_for("workers_page"))
        if nrc_number and Worker.query.filter_by(nrc_number=nrc_number).first():
            flash("NRC number already exists for another worker.", "danger")
            return redirect(url_for("workers_page"))

        enrollment_date = datetime.utcnow()
        raw_date = request.form.get("enrollment_date", "").strip()
        if raw_date:
            parsed = _parse_date(raw_date)
            if not parsed:
                flash("Enrollment date is invalid.", "danger")
                return redirect(url_for("workers_page"))
            enrollment_date = datetime.combine(parsed, datetime.min.time())

        worker_id = _generate_worker_id()
        worker = Worker(
            worker_id=worker_id,
            name=name,
            nrc_number=nrc_number or None,
            phone_number=phone_number,
            address=request.form.get("address", "").strip(),
            emergency_contact=request.form.get("emergency_contact", "").strip(),
            department=request.form.get("department", "").strip(),
            hourly_rate=_float_or_none(request.form.get("hourly_rate")),
            # Blank means "follow the farm default", the same convention the
            # hourly rate uses.
            payroll_period=(request.form.get("payroll_period") or "").strip() or None,
            enrollment_date=enrollment_date,
            status=request.form.get("status", "active").strip().lower() or "active",
            pin_fingerprint=_pin_fingerprint(pin),
        )
        worker.set_pin(pin)
        db.session.add(worker)
        db.session.commit()
        _log_audit("worker.add", f"Added worker {worker_id} - {name}")
        flash(
            f"Worker '{name}' added with ID {worker_id}. "
            "Next step: enrol their face on the Biometric page so they can clock in.",
            "success",
        )
        return redirect(url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/update", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def update_worker(worker_pk):
        worker = Worker.query.get_or_404(worker_pk)
        worker.name = request.form.get("name", "").strip()
        worker.phone_number = request.form.get("phone_number", "").strip()
        worker.address = request.form.get("address", "").strip()
        worker.emergency_contact = request.form.get("emergency_contact", "").strip()
        worker.department = request.form.get("department", "").strip()
        worker.nrc_number = request.form.get("nrc_number", "").strip() or None
        worker.status = request.form.get("status", "active").strip().lower() or "active"
        worker.hourly_rate = _float_or_none(request.form.get("hourly_rate"))
        worker.payroll_period = (request.form.get("payroll_period") or "").strip() or None

        if not worker.name or not worker.phone_number:
            flash("Worker name and phone number are required.", "danger")
            return redirect(url_for("workers_page"))

        if worker.nrc_number:
            existing = Worker.query.filter_by(nrc_number=worker.nrc_number).first()
            if existing and existing.id != worker.id:
                flash("NRC number already exists for another worker.", "danger")
                return redirect(url_for("workers_page"))

        raw_date = request.form.get("enrollment_date", "").strip()
        if raw_date:
            parsed = _parse_date(raw_date)
            if not parsed:
                flash("Enrollment date is invalid.", "danger")
                return redirect(url_for("workers_page"))
            worker.enrollment_date = datetime.combine(parsed, datetime.min.time())

        db.session.commit()
        _log_audit("worker.update", f"Updated worker {worker.worker_id}")
        flash(f"Worker '{worker.worker_id}' updated successfully.", "success")
        return redirect(url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/reset-pin", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def reset_worker_pin(worker_pk):
        worker = Worker.query.get_or_404(worker_pk)
        new_pin = request.form.get("new_pin", "").strip()
        if len(new_pin) < 4:
            flash("New PIN must be at least 4 digits.", "danger")
            return redirect(url_for("workers_page"))
        if not _is_pin_unique(new_pin, exclude_worker_id=worker.worker_id):
            flash("PIN already exists. Choose a unique PIN for each worker.", "danger")
            return redirect(url_for("workers_page"))

        worker.set_pin(new_pin)
        worker.pin_fingerprint = _pin_fingerprint(new_pin)
        db.session.commit()
        _log_audit("worker.reset_pin", f"PIN reset for {worker.worker_id}")
        flash(f"PIN reset successfully for {worker.name} ({worker.worker_id}).", "success")
        return redirect(url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/toggle", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def toggle_worker(worker_pk):
        worker = Worker.query.get_or_404(worker_pk)
        worker.status = "inactive" if (worker.status or "active").lower() == "active" else "active"
        db.session.commit()
        state = "activated" if worker.status == "active" else "deactivated"
        _log_audit("worker.toggle", f"Worker {worker.worker_id} {state}")
        flash(f"Worker '{worker.name}' has been {state}.", "info")
        return redirect(url_for("workers_page"))

    # ---- Face enrolment ---------------------------------------------------- #

    @app.route("/workers/<int:worker_pk>/face/enroll", methods=["POST"])
    @permission_required(BIOMETRIC_MANAGE)
    def enroll_face(worker_pk: int):
        worker = Worker.query.get_or_404(worker_pk)
        target = request.form.get("next") or url_for("biometric_page")
        existing = face_engine.sample_count_for(worker.id)
        if existing >= MAX_ENROLL_SAMPLES:
            flash(f"{worker.name} already has the maximum of {MAX_ENROLL_SAMPLES} samples. "
                  "Clear the enrolment to start again.", "warning")
            return redirect(target)

        # Two ways in. Photo uploads win when present (the supervisor chose
        # the upload modal); otherwise capture live from the attendance camera.
        uploads = [f for f in request.files.getlist("photos") if f and f.filename]
        stored, failures = 0, []

        if uploads:
            import cv2
            import numpy as np
            for upload in uploads[:MAX_ENROLL_SAMPLES - existing]:
                buffer = np.frombuffer(upload.read(), dtype=np.uint8)
                frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if frame is None:
                    failures.append(f"{upload.filename}: not a readable image")
                    continue
                outcome = face_engine.enroll_frame(worker, frame, FACES_DIR)
                if outcome["ok"]:
                    stored += 1
                else:
                    failures.append(f"{upload.filename}: {outcome['reason']}")
        else:
            # Grab several frames and keep the first that yields a usable
            # face: a single frame catches too many blinks and head turns.
            frames, status = cctv_engine.grab_frames(count=6)
            if status != "ok" or not frames:
                cctv_engine.log_health("camera", 0, "offline", device_label="Enrolment camera",
                                       error_code="grab_failed",
                                       error_message="No frames available during enrolment")
                flash("The camera could not be opened. Attach a webcam or upload a photo instead.", "danger")
                return redirect(target)
            for frame in frames:
                outcome = face_engine.enroll_frame(worker, frame, FACES_DIR)
                if outcome["ok"]:
                    stored += 1
                    break
                failures.append(outcome["reason"])

        if stored:
            total = face_engine.sample_count_for(worker.id)
            _log_audit("biometric.enroll",
                       f"Stored {stored} face sample(s) for {worker.worker_id} (total {total})")
            advice = "" if total >= 3 else " Add at least 3 samples for reliable matching."
            flash(f"Enrolled {stored} face sample(s) for {worker.name}. Total: {total}.{advice}", "success")
        else:
            reason = failures[0] if failures else "no_face_detected"
            flash(f"No usable face was captured for {worker.name} ({reason}). "
                  "Face the camera in good light and try again.", "danger")
        return redirect(target)

    @app.route("/workers/<int:worker_pk>/face/clear", methods=["POST"])
    @permission_required(BIOMETRIC_MANAGE)
    def clear_face(worker_pk: int):
        worker = Worker.query.get_or_404(worker_pk)
        removed = face_engine.clear_templates(worker)
        _log_audit("biometric.clear", f"Cleared {removed} face sample(s) for {worker.worker_id}")
        flash(f"Cleared {removed} face sample(s) for {worker.name}. "
              "They cannot clock in until re-enrolled.", "info")
        return redirect(request.form.get("next") or url_for("biometric_page"))

    # ---- Attendance -------------------------------------------------------- #

    # ---- Identity cards --------------------------------------------------- #

    @app.route("/workers/<int:worker_pk>/card/issue", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def issue_worker_card(worker_pk: int):
        worker = Worker.query.get_or_404(worker_pk)
        source = _get_setting("barcode_source", barcode_engine.DEFAULT_SOURCE)
        reissue = request.form.get("reissue") == "1"
        ok, message = barcode_engine.issue_card(db, worker, source, reissue=reissue)
        flash(message, "success" if ok else "warning")
        if ok:
            _log_audit("card.issued",
                       f"Card issued to {worker.worker_id} using source '{source}'"
                       + (" (reissue)" if reissue else ""))
        return redirect(request.referrer or url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/card/void", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def void_worker_card(worker_pk: int):
        worker = Worker.query.get_or_404(worker_pk)
        ok, message = barcode_engine.void_card(db, worker)
        flash(message, "success" if ok else "warning")
        if ok:
            _log_audit("card.voided", f"Card voided for {worker.worker_id}")
        return redirect(request.referrer or url_for("workers_page"))

    @app.route("/workers/cards/issue-all", methods=["POST"])
    @permission_required(WORKER_MANAGE)
    def issue_all_cards():
        """Give a card to every active worker who does not have one.

        Skips rather than fails on a worker the current setting cannot produce a
        value for - typically one with no NRC while the barcode is NRC-derived -
        and reports how many were skipped, so the operator knows to go and fix
        those records rather than assuming the run succeeded for everyone.
        """
        source = _get_setting("barcode_source", barcode_engine.DEFAULT_SOURCE)
        issued = skipped = 0
        for worker in Worker.query.filter(Worker.status == "active").all():
            if worker.card_barcode:
                continue
            ok, _ = barcode_engine.issue_card(db, worker, source)
            issued += 1 if ok else 0
            skipped += 0 if ok else 1
        parts = [f"{issued} card{'s' if issued != 1 else ''} issued"]
        if skipped:
            parts.append(f"{skipped} skipped, most likely missing an NRC while the "
                         f"card setting derives the barcode from it")
        flash(". ".join(parts) + ".", "success" if issued else "warning")
        _log_audit("card.issued.bulk", f"Bulk issue: {issued} issued, {skipped} skipped")
        return redirect(url_for("workers_page"))

    @app.route("/workers/cards")
    @admin_required
    def print_cards():
        """A printable sheet of cards: one worker, a selected set, or everyone.

        `who` is 'all', 'uncarded', or absent when specific worker ids are
        passed. Cards are laid out to a standard credit-card footprint so a
        farm can print onto card stock and cut, or print on paper and laminate.
        """
        who = request.args.get("who", "")
        ids = [int(v) for v in request.args.getlist("id") if v.isdigit()]

        # Two ways to get a two-sided card out of a printer, and they fail
        # differently. "fold" prints the two faces side by side to be cut as one
        # piece and folded, which any printer can do. "duplex" prints fronts and
        # backs on separate pages for double-sided printing, which gives a
        # single-thickness card but depends on the printer feeding straight.
        layout = request.args.get("layout", "fold").strip().lower()
        if layout not in ("fold", "duplex"):
            layout = "fold"

        query = Worker.query.filter(Worker.status == "active")
        if ids:
            query = query.filter(Worker.id.in_(ids))
        elif who == "uncarded":
            query = query.filter(Worker.card_barcode.is_(None))
        workers = query.order_by(Worker.worker_id.asc()).all()

        symbology = _get_setting("barcode_symbology", barcode_engine.DEFAULT_SYMBOLOGY)
        cards, missing = [], []
        for worker in workers:
            if not worker.card_barcode:
                missing.append(worker)
                continue
            if (worker.card_status or "active").lower() == "void":
                missing.append(worker)
                continue
            photo = face_engine.profile_photo_for(worker)
            cards.append({
                "worker": worker,
                "value": worker.card_barcode,
                "svg": barcode_engine.render_svg(worker.card_barcode, symbology),
                # The captures route serves paths relative to the captures
                # directory, so the prefix is stripped once here rather than in
                # the template.
                "photo": photo[len("captures/"):] if photo else None,
            })

        # Duplex needs the backs laid out in the mirror of the fronts: a sheet
        # flipped on its long edge arrives with its columns reversed. Getting
        # that wrong is exactly the failure that puts one worker's barcode on
        # another worker's card, so it is computed here, once, rather than left
        # to the template.
        #
        # A short final row is padded with blanks *before* reversing. Without
        # the padding, a row holding a single card would put that card in the
        # left column of both pages - and after the flip it would land behind
        # nothing at all.
        duplex_pages = []
        if layout == "duplex":
            per_row, rows_per_page = 2, 5
            per_page = per_row * rows_per_page
            for start in range(0, len(cards), per_page):
                chunk = cards[start:start + per_page]
                rows = []
                for i in range(0, len(chunk), per_row):
                    row = chunk[i:i + per_row]
                    row = row + [None] * (per_row - len(row))
                    rows.append({"fronts": row, "backs": list(reversed(row))})
                duplex_pages.append(rows)

        # The two layout links keep whatever selection the page was opened
        # with, so switching layout never silently changes which workers print.
        switch_args = {k: v for k, v in request.args.lists() if k != "layout"}

        return render_template(
            "cards_print.html",
            cards=cards,
            duplex_pages=duplex_pages,
            layout=layout,
            fold_url=url_for("print_cards", layout="fold", **switch_args),
            duplex_url=url_for("print_cards", layout="duplex", **switch_args),
            missing=missing,
            symbology=symbology,
            photos_enrolled=sum(1 for c in cards if c["photo"]),
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/attendance")
    @admin_required
    def attendance_page():
        attendance_rows = Attendance.query.order_by(Attendance.check_in_time.desc()).limit(400).all()
        sessions = _build_attendance_sessions(attendance_rows)
        verified = sum(1 for s in sessions if s["verified_by_face"])
        return render_template(
            "attendance.html",
            sessions=sessions,
            attendance_stats={
                "total": len(sessions),
                "complete": sum(1 for s in sessions if s["clock_in_time"] and s["clock_out_time"]),
                "in_progress": sum(1 for s in sessions if s["clock_in_time"] and not s["clock_out_time"]),
                "out_only": sum(1 for s in sessions if not s["clock_in_time"] and s["clock_out_time"]),
                "today": sum(1 for s in sessions if s["_sort_key"] and s["_sort_key"].date() == date.today()),
                "verified": verified,
                "verified_rate": round((verified / len(sessions)) * 100, 1) if sessions else 0.0,
            },
            active_page="attendance",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/attendance/refresh-summaries", methods=["POST"])
    @permission_required(ATTENDANCE_MANAGE)
    def refresh_summaries():
        day_to = _parse_date(request.form.get("to", ""), date.today())
        day_from = _parse_date(request.form.get("from", ""), day_to - timedelta(days=30))
        touched = payroll_engine.refresh_range(day_from, day_to)
        _log_audit("attendance.summaries_refreshed",
                   f"Rebuilt {touched} daily summaries from {day_from} to {day_to}")
        flash(f"Rebuilt {touched} daily summary row(s) from {day_from} to {day_to}.", "success")
        return redirect(request.referrer or url_for("attendance_page"))

    # ---- Settings ---------------------------------------------------------- #

    # ---- Analytics -------------------------------------------------------- #

    @app.route("/analytics")
    @admin_required
    def analytics():
        """Trends across weeks, which the dashboard's "right now" view cannot show.

        The window is a query parameter rather than a setting because a manager
        asks different questions over different spans: a fortnight for "what is
        happening", a quarter for "what is the pattern".
        """
        try:
            days = int(request.args.get("days", reports_engine.DEFAULT_WINDOW_DAYS))
        except (TypeError, ValueError):
            days = reports_engine.DEFAULT_WINDOW_DAYS
        days = max(7, min(days, 365))

        return render_template(
            "analytics.html",
            report=reports_engine.full_report(days),
            days=days,
            window_options=[14, 28, 56, 90],
            active_page="analytics",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/settings", methods=["GET", "POST"])
    @admin_required
    def settings():
        if request.method == "POST":
            if not can(SETTINGS_MANAGE):
                flash("Only an administrator can change system settings.", "danger")
                return redirect(url_for("settings"))

            threshold = request.form.get("face_match_threshold", "35").strip()
            try:
                threshold_value = float(threshold)
                if not 0 <= threshold_value <= 100:
                    raise ValueError
            except ValueError:
                flash("Face match threshold must be a number between 0 and 100.", "danger")
                return redirect(url_for("settings"))

            lat, lon = geofence.normalize_coordinates(
                request.form.get("farm_latitude"), request.form.get("farm_longitude")
            )
            if (request.form.get("farm_latitude") or request.form.get("farm_longitude")) and lat is None:
                flash("Farm coordinates are not valid. Use decimal degrees, e.g. -15.4067 and 28.2871.", "danger")
                return redirect(url_for("settings"))

            _save_settings({
                "org_name": request.form.get("org_name", "").strip(),
                "face_match_threshold": str(threshold_value),
                "face_verification_required": "on" if request.form.get("face_verification_required") else "off",
                "face_require_eyes": "on" if request.form.get("face_require_eyes") else "off",
                "farm_latitude": "" if lat is None else str(lat),
                "farm_longitude": "" if lon is None else str(lon),
                "geofence_radius_m": request.form.get("geofence_radius_m", "500").strip() or "500",
                "geofence_enforce": "on" if request.form.get("geofence_enforce") else "off",
                "payroll_period": payroll_engine.normalize_period(
                    request.form.get("payroll_period")),
                "standard_day_hours": request.form.get("standard_day_hours", "8").strip() or "8",
                "overtime_multiplier": request.form.get("overtime_multiplier", "1.5").strip() or "1.5",
                "napsa_rate": request.form.get("napsa_rate", "0.05").strip() or "0.05",
                "nhima_rate": request.form.get("nhima_rate", "0.01").strip() or "0.01",
                "default_hourly_rate": request.form.get("default_hourly_rate", "15").strip() or "15",
                "shift_start_time": request.form.get("shift_start_time", "07:00").strip() or "07:00",
                "shift_end_time": request.form.get("shift_end_time", "17:00").strip() or "17:00",
                "clip_recording_enabled": "on" if request.form.get("clip_recording_enabled") else "off",
                "clip_seconds": request.form.get("clip_seconds", "6").strip() or "6",
                "chart_refresh_seconds": (request.form.get("chart_refresh_seconds") or "0").strip(),
                "barcode_enabled": "on" if request.form.get("barcode_enabled") else "off",
                "barcode_source": (request.form.get("barcode_source") or "").strip()
                                  if (request.form.get("barcode_source") or "").strip()
                                     in barcode_engine.SOURCES
                                  else barcode_engine.DEFAULT_SOURCE,
                "barcode_symbology": (request.form.get("barcode_symbology") or "").strip()
                                     if (request.form.get("barcode_symbology") or "").strip()
                                        in barcode_engine.SYMBOLOGIES
                                     else barcode_engine.DEFAULT_SYMBOLOGY,
                "barcode_require_pin": "on" if request.form.get("barcode_require_pin") else "off",
                "barcode_camera_scan": "on" if request.form.get("barcode_camera_scan") else "off",
            })
            _log_audit("settings.save", "System settings updated")
            flash("Settings saved.", "success")
            return redirect(url_for("settings"))

        return render_template(
            "settings.html",
            settings={s.key: s.value for s in Setting.query.all()},
            engine=face_engine.engine_info(),
            periods=payroll_engine.PERIODS,
            card_sources=barcode_engine.SOURCES,
            card_symbologies=barcode_engine.SYMBOLOGIES,
            card_stats=barcode_engine.stats(),
            active_page="settings",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/settings/api-key/regenerate", methods=["POST"])
    @permission_required(SETTINGS_MANAGE)
    def regenerate_api_key():
        _save_settings({"api_key": secrets.token_urlsafe(24)})
        _log_audit("settings.api_key", "API key regenerated")
        flash("API key regenerated. Update any client that used the old key.", "warning")
        return redirect(url_for("settings"))

    # ---- Users -------------------------------------------------------------- #

    @app.route("/users")
    @permission_required(USER_MANAGE)
    def users_page():
        return render_template(
            "users.html",
            users=User.query.order_by(User.created_at.desc()).all(),
            workers=Worker.query.order_by(Worker.worker_id.asc()).all(),
            active_page="users",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/users/add", methods=["POST"])
    @permission_required(USER_MANAGE)
    def add_user():
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("name", "").strip()
        if not username or not name:
            flash("Username and Name are required.", "danger")
            return redirect(url_for("users_page"))
        if User.query.filter_by(username=username).first():
            flash(f"Username '{username}' already exists.", "danger")
            return redirect(url_for("users_page"))

        password = _generate_password(10)
        user = User(
            username=username,
            name=name,
            email=request.form.get("email", "").strip(),
            phone=request.form.get("phone", "").strip(),
            role=normalize_role(request.form.get("role", "supervisor")),
            linked_worker_id=request.form.get("linked_worker_id", type=int),
            must_change_password=True,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        _log_audit("user.add", f"Added user '{username}' with role {user.role}")
        flash(f"User '{username}' created as {user.role}. Temporary password: {password} "
              "(they must change it at first login).", "success")
        return redirect(url_for("users_page"))

    @app.route("/users/<int:user_pk>/update", methods=["POST"])
    @permission_required(USER_MANAGE)
    def update_user(user_pk: int):
        user = User.query.get_or_404(user_pk)
        new_role = normalize_role(request.form.get("role", "supervisor"))

        admin_count = User.query.filter_by(role="admin", is_active=True).count()
        if user.role == "admin" and new_role != "admin" and admin_count <= 1:
            flash("This is the last administrator. Promote another user before changing this role.", "danger")
            return redirect(url_for("users_page"))

        user.name = request.form.get("name", "").strip()
        user.email = request.form.get("email", "").strip()
        user.phone = request.form.get("phone", "").strip()
        user.role = new_role
        user.linked_worker_id = request.form.get("linked_worker_id", type=int)
        if not user.name:
            flash("Name is required.", "danger")
            return redirect(url_for("users_page"))

        db.session.commit()
        _log_audit("user.update", f"Updated user '{user.username}' (role {user.role})")
        flash(f"User '{user.username}' updated.", "success")
        return redirect(url_for("users_page"))

    @app.route("/users/<int:user_pk>/reset-password", methods=["POST"])
    @permission_required(USER_MANAGE)
    def reset_user_password(user_pk: int):
        user = User.query.get_or_404(user_pk)
        password = _generate_password(10)
        user.set_password(password)
        user.must_change_password = True
        db.session.commit()
        _log_audit("user.reset_password", f"Reset password for '{user.username}'")
        flash(f"Password for '{user.username}' reset to: {password} "
              "(they must change it at next login).", "success")
        return redirect(url_for("users_page"))

    @app.route("/users/<int:user_pk>/toggle", methods=["POST"])
    @permission_required(USER_MANAGE)
    def toggle_user(user_pk: int):
        user = User.query.get_or_404(user_pk)
        if user.id == session.get("admin_user_id"):
            flash("You cannot deactivate your own account.", "danger")
            return redirect(url_for("users_page"))
        if user.role == "admin" and user.is_active and \
                User.query.filter_by(role="admin", is_active=True).count() <= 1:
            flash("This is the last active administrator and cannot be deactivated.", "danger")
            return redirect(url_for("users_page"))

        user.is_active = not user.is_active
        db.session.commit()
        state = "activated" if user.is_active else "deactivated"
        _log_audit("user.toggle", f"User '{user.username}' {state}")
        flash(f"User '{user.username}' {state}.", "info")
        return redirect(url_for("users_page"))

    # ---- Audit log and data hub --------------------------------------------- #

    @app.route("/audit-log")
    @admin_required
    def audit_log_page():
        return render_template(
            "audit_log.html",
            logs=AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(500).all(),
            active_page="audit_log",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/tables-hub")
    @admin_required
    def tables_hub_page():
        return render_template(
            "tables_hub.html",
            active_page="tables_hub",
            org_name=_get_setting("org_name", "FMS Farm"),
        )

    @app.route("/tables-hub/<string:table_key>")
    @admin_required
    def tables_hub_table_page(table_key: str):
        registry = {
            "cctv-feeds": (CCTVFeed, "CCTV Feeds"),
            "biometric-devices": (BiometricDevice, "Biometric Devices"),
            "payroll": (Payroll, "Payroll"),
            "face-templates": (FaceTemplate, "Face Templates"),
            "biometric-transactions": (BiometricTransaction, "Biometric Transactions"),
            "cctv-recordings": (CCTVRecording, "CCTV Recordings"),
            "event-snapshots": (EventSnapshot, "Event Snapshots"),
            "offline-sync-queue": (OfflineSyncQueue, "Offline Sync Queue"),
            "cloud-sync-metadata": (CloudSyncMetadata, "Cloud Sync Metadata"),
            "daily-attendance-summary": (DailyAttendanceSummary, "Daily Attendance Summary"),
            "hardware-health-logs": (HardwareHealthLog, "Hardware Health Logs"),
        }
        if table_key not in registry:
            abort(404)

        model, title = registry[table_key]
        columns = [c.name for c in model.__table__.columns]
        first_col = list(model.__table__.columns)[0]
        rows = model.query.order_by(first_col.desc()).limit(300).all()
        data_rows = []
        for row in rows:
            record = {}
            for col in columns:
                value = getattr(row, col, None)
                # Face templates hold raw pixel bytes (40,000 per row); print
                # the size instead of flooding the page.
                if isinstance(value, (bytes, bytearray)):
                    value = f"<{len(value)} bytes>"
                record[col] = value
            data_rows.append(record)

        return render_template(
            "table_records.html",
            active_page="tables_hub",
            org_name=_get_setting("org_name", "FMS Farm"),
            table_title=title,
            columns=columns,
            rows=data_rows,
            table_key=table_key,
        )

    # ---- Exports ------------------------------------------------------------ #

    @app.route("/export/<string:export_key>.csv")
    @admin_required
    def export_csv(export_key: str):
        if export_key not in exports.EXPORTS:
            abort(404)
        filename, builder = exports.EXPORTS[export_key]
        _log_audit("export.csv", f"Exported {filename}")
        return Response(
            builder(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    # ---- CCTV ---------------------------------------------------------------- #

    @app.route("/cctv")
    @admin_required
    def cctv_page():
        _ensure_default_cctv_entries()
        return render_template(
            "cctv.html",
            active_page="cctv",
            org_name=_get_setting("org_name", "FMS Farm"),
            feeds=CCTVFeed.query.order_by(CCTVFeed.feed_id.desc()).all(),
            recordings=_real_recordings(),
            camera_sources=cctv_engine.get_camera_sources(),
            health_logs=HardwareHealthLog.query.order_by(
                HardwareHealthLog.log_id.desc()).limit(25).all(),
            settings={s.key: s.value for s in Setting.query.all()},
        )

    @app.route("/config/cctv-feeds", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def add_cctv_feed():
        camera_name = request.form.get("camera_name", "").strip()
        if not camera_name:
            flash("Camera name is required.", "danger")
            return redirect(url_for("cctv_page"))
        row = CCTVFeed(
            camera_name=camera_name,
            camera_location=request.form.get("camera_location", "").strip(),
            rtsp_url=request.form.get("rtsp_url", "").strip(),
            status="offline",
        )
        db.session.add(row)
        db.session.commit()
        _log_audit("config.cctv_feed.add", f"Added CCTV feed '{camera_name}'")
        flash("CCTV feed saved. Use Test to confirm it is reachable, then it appears in the live views.",
              "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv-feeds/<int:feed_id>/update", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def update_cctv_feed(feed_id: int):
        feed = CCTVFeed.query.get_or_404(feed_id)
        camera_name = request.form.get("camera_name", "").strip()
        if not camera_name:
            flash("Camera name is required.", "danger")
            return redirect(url_for("cctv_page"))

        feed.camera_name = camera_name
        feed.camera_location = request.form.get("camera_location", "").strip()
        feed.rtsp_url = request.form.get("rtsp_url", "").strip()
        status = request.form.get("status", "offline").strip().lower() or "offline"
        feed.status = status
        if status == "online":
            feed.last_heartbeat = datetime.utcnow()

        db.session.commit()
        _log_audit("config.cctv_feed.update", f"Updated CCTV feed '{feed.camera_name}' (id={feed.feed_id})")
        flash("CCTV feed updated.", "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv-feeds/<int:feed_id>/deactivate", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def deactivate_cctv_feed(feed_id: int):
        feed = CCTVFeed.query.get_or_404(feed_id)
        feed.status = "inactive"
        feed.is_primary = False
        db.session.commit()
        _log_audit("config.cctv_feed.deactivate", f"Deactivated CCTV feed id={feed.feed_id}")
        flash("CCTV feed deactivated and removed from the live views.", "info")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv-feeds/<int:feed_id>/primary", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def set_primary_feed(feed_id: int):
        feed = CCTVFeed.query.get_or_404(feed_id)
        CCTVFeed.query.update({CCTVFeed.is_primary: False})
        feed.is_primary = True
        if (feed.status or "").lower() == "inactive":
            feed.status = "offline"
        db.session.commit()
        _log_audit("config.cctv_feed.primary", f"Feed {feed.feed_id} set as attendance camera")
        flash(f"'{feed.camera_name}' is now the attendance camera used for verification and snapshots.",
              "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv-feeds/<int:feed_id>/test", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def test_cctv_feed(feed_id: int):
        feed = CCTVFeed.query.get_or_404(feed_id)
        outcome = cctv_engine.probe_feed(feed)
        _log_audit("cctv.health_check", f"Feed {feed.feed_id} probed: {outcome['status']}")
        if outcome["status"] == "online":
            flash(f"'{feed.camera_name}' responded in {outcome['response_time_ms']} ms.", "success")
        else:
            flash(f"'{feed.camera_name}' did not return frames. Check the URL, power and network.",
                  "danger")
        return redirect(url_for("cctv_page"))

    @app.route("/cctv/health-check", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def cctv_health_check():
        feeds = CCTVFeed.query.filter(CCTVFeed.rtsp_url.isnot(None)).all()
        results = [cctv_engine.probe_feed(feed) for feed in feeds]
        online = sum(1 for r in results if r["status"] == "online")
        _log_audit("cctv.health_check", f"Probed {len(results)} feeds, {online} online")
        flash(f"Checked {len(results)} camera(s): {online} online, {len(results) - online} offline.",
              "info" if online else "warning")
        return redirect(url_for("cctv_page"))

    @app.route("/cctv/record-now", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def record_now():
        seconds = _float_or_none(request.form.get("seconds")) or 10.0
        primary = cctv_engine.primary_source()
        cctv_engine.record_clip(
            app, primary["source"], CLIPS_DIR, seconds=min(60.0, max(3.0, seconds)),
            camera_id=primary.get("feed_id"), trigger_type="manual",
        )
        _log_audit("cctv.record_now", f"Manual {seconds:.0f}s clip requested on '{primary['name']}'")
        flash(f"Recording a {seconds:.0f} second clip from '{primary['name']}'. "
              "It appears in Recordings when finished.", "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv/settings", methods=["POST"])
    @permission_required(CCTV_MANAGE)
    def save_cctv_settings():
        camera_index = request.form.get("camera_index", "0").strip() or "0"
        camera_sources_raw = request.form.get("camera_sources", "").strip()

        if camera_sources_raw:
            try:
                parsed = json.loads(camera_sources_raw)
                if not isinstance(parsed, list):
                    raise ValueError("Camera sources must be a JSON array")
            except (json.JSONDecodeError, ValueError):
                flash("Camera sources must be a valid JSON array.", "danger")
                return redirect(url_for("cctv_page"))

        _save_settings({"camera_index": camera_index, "camera_sources": camera_sources_raw})
        _ensure_default_cctv_entries()
        _log_audit("cctv.settings.save", "Updated CCTV settings")
        flash("CCTV settings saved.", "success")
        return redirect(url_for("cctv_page"))

    # ---- Biometric (enrolment) ---------------------------------------------- #

    @app.route("/biometric")
    @admin_required
    def biometric_page():
        workers = Worker.query.order_by(Worker.worker_id.asc()).all()
        counts = face_engine.sample_counts()
        samples = {}
        for row in FaceTemplate.query.order_by(FaceTemplate.face_id.asc()).all():
            samples.setdefault(row.worker_id, []).append(row)

        return render_template(
            "biometric.html",
            active_page="biometric",
            org_name=_get_setting("org_name", "FMS Farm"),
            devices=BiometricDevice.query.order_by(BiometricDevice.created_at.desc()).limit(200).all(),
            workers=workers,
            face_samples=counts,
            sample_rows=samples,
            enrolled_count=sum(1 for w in workers if counts.get(w.id, 0) > 0),
            pending_count=sum(1 for w in workers
                              if counts.get(w.id, 0) == 0 and (w.status or "") == "active"),
            transactions=BiometricTransaction.query.order_by(
                BiometricTransaction.timestamp.desc()).limit(50).all(),
            worker_lookup={w.id: w for w in workers},
            verification=face_engine.accuracy_snapshot(),
            engine=face_engine.engine_info(),
            threshold=match_threshold(),
            max_samples=MAX_ENROLL_SAMPLES,
        )

    @app.route("/config/biometric-devices", methods=["POST"])
    @permission_required(BIOMETRIC_MANAGE)
    def add_biometric_device():
        device_name = request.form.get("device_name", "").strip()
        if not device_name:
            flash("Device name is required.", "danger")
            return redirect(url_for("biometric_page"))
        db.session.add(BiometricDevice(
            device_name=device_name,
            device_serial=request.form.get("device_serial", "").strip() or None,
            device_type=request.form.get("device_type", "camera").strip().lower() or "camera",
            location=request.form.get("location", "").strip(),
        ))
        db.session.commit()
        _log_audit("config.biometric_device.add", f"Added biometric device '{device_name}'")
        flash("Biometric device saved.", "success")
        return redirect(url_for("biometric_page"))

    @app.route("/config/biometric-devices/<int:device_id>/update", methods=["POST"])
    @permission_required(BIOMETRIC_MANAGE)
    def update_biometric_device(device_id: int):
        device = BiometricDevice.query.get_or_404(device_id)
        device_name = request.form.get("device_name", "").strip()
        if not device_name:
            flash("Device name is required.", "danger")
            return redirect(url_for("biometric_page"))

        device.device_name = device_name
        device.device_serial = request.form.get("device_serial", "").strip() or None
        device.device_type = request.form.get("device_type", "camera").strip().lower() or "camera"
        device.ip_address = request.form.get("ip_address", "").strip() or None
        device.usb_port = request.form.get("usb_port", "").strip() or None
        device.location = request.form.get("location", "").strip()
        status = request.form.get("status", "offline").strip().lower() or "offline"
        device.status = status
        if status == "online":
            device.last_heartbeat = datetime.utcnow()

        db.session.commit()
        _log_audit("config.biometric_device.update", f"Updated device id={device.device_id}")
        flash("Biometric device updated.", "success")
        return redirect(url_for("biometric_page"))

    @app.route("/config/biometric-devices/<int:device_id>/deactivate", methods=["POST"])
    @permission_required(BIOMETRIC_MANAGE)
    def deactivate_biometric_device(device_id: int):
        device = BiometricDevice.query.get_or_404(device_id)
        device.status = "inactive"
        db.session.commit()
        _log_audit("config.biometric_device.deactivate", f"Deactivated device id={device.device_id}")
        flash("Biometric device deactivated.", "info")
        return redirect(url_for("biometric_page"))

    # ---- Payroll ------------------------------------------------------------- #

    @app.route("/payroll")
    @admin_required
    def payroll_page():
        workers = Worker.query.order_by(Worker.worker_id.asc()).all()
        today = date.today()
        # Default the picker to the most recent Sunday.
        # Default the picker to the most recent Sunday, which is the usual
        # pay week ending. Python weekday(): Monday 0 ... Sunday 6, so
        # (weekday + 1) % 7 is the number of days back to the last Sunday -
        # on a Sunday that is 0, i.e. today.
        default_week_ending = today - timedelta(days=(today.weekday() + 1) % 7)
        return render_template(
            "payroll.html",
            active_page="payroll",
            org_name=_get_setting("org_name", "FMS Farm"),
            workers=workers,
            worker_lookup={w.id: w for w in workers},
            payroll_rows=Payroll.query.order_by(
                Payroll.week_ending.desc(), Payroll.payroll_id.desc()).limit(200).all(),
            rates=payroll_engine.rates(),
            default_week_ending=default_week_ending.isoformat(),
            periods=payroll_engine.PERIODS,
            farm_period=payroll_engine.farm_period(),
            period_label=payroll_engine.period_label,
            worker_period=payroll_engine.worker_period,
        )

    @app.route("/payroll/generate", methods=["POST"])
    @permission_required(PAYROLL_MANAGE)
    def generate_payroll_page():
        anchor = _parse_date(request.form.get("week_ending", ""))
        if not anchor:
            flash("Choose a valid date for the period.", "danger")
            return redirect(url_for("payroll_page"))
        # Which cycle to run. Defaults to the farm-wide setting, so a farm with
        # one cycle never has to think about this control at all.
        period_type = payroll_engine.normalize_period(
            request.form.get("payroll_period") or payroll_engine.farm_period())

        outcome = payroll_engine.generate_period(anchor, period_type)
        label = outcome["label"]

        _log_audit("payroll.generate",
                   f"Generated {outcome['period_type']} payroll for {label} "
                   f"({outcome['period_start']} to {outcome['period_end']}): "
                   f"{outcome['created']} created, {outcome['updated']} updated, "
                   f"{outcome['skipped_overlap']} blocked by an overlapping paid period")

        if outcome["created"] or outcome["updated"]:
            note = (f"{label}: {outcome['created']} created, {outcome['updated']} updated "
                    f"from recorded attendance.")
            if outcome["skipped_no_hours"]:
                note += f" {outcome['skipped_no_hours']} had no hours."
            if outcome["skipped_other_cycle"]:
                note += (f" {outcome['skipped_other_cycle']} are on a different pay "
                         f"cycle and were not touched.")
            if outcome["skipped_already_paid"]:
                note += f" {outcome['skipped_already_paid']} already paid."
            flash(note, "success")
        elif outcome["skipped_other_cycle"] and not outcome["rows"]:
            flash(f"No active worker is on the {outcome['period_type']} cycle, "
                  f"so nothing was generated for {label}.", "warning")
        else:
            flash(f"No attendance hours found for {label}, so nothing was generated.",
                  "warning")

        # The overlap guard is reported separately and loudly: it means somebody
        # would have been paid twice for the same days, which is not a detail to
        # bury at the end of a success message.
        for clash in outcome["conflicts"]:
            flash(f"{clash['worker_id']} {clash['name']} was skipped: "
                  f"{clash['paid_period']} is already paid and covers some of "
                  f"these days. Paying both would pay the same day twice.", "danger")

        return redirect(url_for("payroll_page"))

    @app.route("/config/payroll", methods=["POST"])
    @permission_required(PAYROLL_MANAGE)
    def add_payroll_record():
        worker_pk = request.form.get("worker_id", type=int)
        week_ending = _parse_date(request.form.get("week_ending", ""))
        if not worker_pk or not week_ending:
            flash("Worker and a valid week ending date are required.", "danger")
            return redirect(url_for("payroll_page"))

        worker = Worker.query.get_or_404(worker_pk)
        if Payroll.query.filter_by(worker_id=worker_pk, week_ending=week_ending).first():
            flash(f"A payroll row already exists for {worker.name} for week ending {week_ending}.",
                  "warning")
            return redirect(url_for("payroll_page"))

        total_hours = _float_or_none(request.form.get("total_hours")) or 0.0
        overtime_hours = _float_or_none(request.form.get("overtime_hours")) or 0.0
        hourly_rate = _float_or_none(request.form.get("hourly_rate")) or payroll_engine.worker_rate(worker)
        figures = payroll_engine.compute_pay(total_hours, overtime_hours, hourly_rate)

        db.session.add(Payroll(
            worker_id=worker_pk,
            week_ending=week_ending,
            total_hours=figures["total_hours"],
            overtime_hours=figures["overtime_hours"],
            hourly_rate=figures["hourly_rate"],
            overtime_pay=figures["overtime_pay"],
            gross_pay=figures["gross_pay"],
            napsa_rate=figures["napsa_rate"],
            nhima_rate=figures["nhima_rate"],
            napsa_deduction=figures["napsa_deduction"],
            nhima_deduction=figures["nhima_deduction"],
            net_pay=figures["net_pay"],
            computed_from_attendance=False,
            generated_at=datetime.utcnow(),
            paid_status="pending",
        ))
        db.session.commit()
        _log_audit("config.payroll.add", f"Added manual payroll row for worker_id={worker_pk}")
        flash(f"Payroll row saved. Gross ZMW {figures['gross_pay']:.2f}, "
              f"net ZMW {figures['net_pay']:.2f} (deductions calculated automatically).", "success")
        return redirect(url_for("payroll_page"))

    @app.route("/config/payroll/<int:payroll_id>/update", methods=["POST"])
    @permission_required(PAYROLL_MANAGE)
    def update_payroll_record(payroll_id: int):
        row = Payroll.query.get_or_404(payroll_id)
        worker_pk = request.form.get("worker_id", type=int)
        week_ending = _parse_date(request.form.get("week_ending", ""))
        if not worker_pk or not week_ending:
            flash("Worker and a valid week ending date are required.", "danger")
            return redirect(url_for("payroll_page"))

        payment_date = None
        raw_payment = request.form.get("payment_date", "").strip()
        if raw_payment:
            payment_date = _parse_date(raw_payment)
            if not payment_date:
                flash("Payment date format is invalid.", "danger")
                return redirect(url_for("payroll_page"))

        worker = Worker.query.get_or_404(worker_pk)
        hourly_rate = _float_or_none(request.form.get("hourly_rate")) or payroll_engine.worker_rate(worker)
        figures = payroll_engine.compute_pay(
            _float_or_none(request.form.get("total_hours")) or 0.0,
            _float_or_none(request.form.get("overtime_hours")) or 0.0,
            hourly_rate,
        )

        row.worker_id = worker_pk
        row.week_ending = week_ending
        row.total_hours = figures["total_hours"]
        row.overtime_hours = figures["overtime_hours"]
        row.hourly_rate = figures["hourly_rate"]
        row.overtime_pay = figures["overtime_pay"]
        row.gross_pay = figures["gross_pay"]
        row.napsa_rate = figures["napsa_rate"]
        row.nhima_rate = figures["nhima_rate"]
        row.napsa_deduction = figures["napsa_deduction"]
        row.nhima_deduction = figures["nhima_deduction"]
        row.net_pay = figures["net_pay"]
        row.computed_from_attendance = False
        row.paid_status = request.form.get("paid_status", "pending").strip().lower() or "pending"
        row.payment_date = payment_date

        db.session.commit()
        _log_audit("config.payroll.update", f"Updated payroll row id={row.payroll_id}")
        flash(f"Payroll row updated. Net pay recalculated to ZMW {figures['net_pay']:.2f}.", "success")
        return redirect(url_for("payroll_page"))

    @app.route("/config/payroll/<int:payroll_id>/deactivate", methods=["POST"])
    @permission_required(PAYROLL_MANAGE)
    def deactivate_payroll_record(payroll_id: int):
        row = Payroll.query.get_or_404(payroll_id)
        row.paid_status = "inactive"
        db.session.commit()
        _log_audit("config.payroll.deactivate", f"Deactivated payroll row id={row.payroll_id}")
        flash("Payroll record deactivated.", "info")
        return redirect(url_for("payroll_page"))

    # ---- Cloud sync ---------------------------------------------------------- #

    @app.route("/cloud-sync", methods=["GET", "POST"])
    @admin_required
    def cloud_sync_page():
        if request.method == "POST":
            if not can(SYNC_MANAGE):
                flash("Your role is not permitted to change cloud settings.", "danger")
                return redirect(url_for("cloud_sync_page"))

            # Validate the service-account JSON before saving. The first
            # release stored three loose fields and assembled a credential
            # dictionary with no private_key, so it could never authenticate;
            # requiring the whole file makes that failure impossible.
            credentials_raw = request.form.get("firebase_credentials_json", "").strip()
            if credentials_raw:
                try:
                    parsed = json.loads(credentials_raw)
                    if not isinstance(parsed, dict) or "private_key" not in parsed:
                        raise ValueError
                except (json.JSONDecodeError, ValueError):
                    flash("Paste the full service-account JSON downloaded from Firebase "
                          "(it must contain a private_key field).", "danger")
                    return redirect(url_for("cloud_sync_page"))

            _save_settings({
                "firebase_bucket": request.form.get("firebase_bucket", "").strip(),
                "firebase_project_id": request.form.get("firebase_project_id", "").strip(),
                "firebase_credentials_json": credentials_raw,
            })
            _log_audit("cloud_sync.settings.save", "Updated cloud sync settings")
            flash("Cloud sync settings saved.", "success")
            return redirect(url_for("cloud_sync_page"))

        return render_template(
            "cloud_sync.html",
            active_page="cloud_sync",
            org_name=_get_setting("org_name", "FMS Farm"),
            metadata_rows=CloudSyncMetadata.query.order_by(
                CloudSyncMetadata.sync_id.desc()).limit(200).all(),
            queue_rows=OfflineSyncQueue.query.order_by(
                OfflineSyncQueue.sync_id.desc()).limit(200).all(),
            stats=sync_engine.queue_stats(),
            settings={s.key: s.value for s in Setting.query.all()},
        )

    @app.route("/cloud-sync/drain", methods=["POST"])
    @permission_required(SYNC_MANAGE)
    def cloud_sync_drain():
        outcome = sync_engine.drain(BASE_DIR)
        _log_audit("cloud_sync.drain",
                   f"Attempted {outcome['attempted']}, synced {outcome['synced']}, "
                   f"failed {outcome['failed']}")
        if outcome["reason"] == "not_configured":
            flash("Cloud sync is not configured, so nothing was uploaded. "
                  f"{outcome['skipped']} item(s) are waiting in the queue.", "warning")
        elif outcome["synced"]:
            flash(f"Uploaded {outcome['synced']} queued item(s). "
                  f"{outcome['failed']} still failing.", "success")
        else:
            flash(f"No items were uploaded. Attempted {outcome['attempted']}, "
                  f"failed {outcome['failed']}.", "warning")
        return redirect(url_for("cloud_sync_page"))

    # ---- Manual --------------------------------------------------------------- #

    @app.route("/manual")
    def manual():
        return render_template(
            "manual.html",
            active_page="manual",
            org_name=_get_setting("org_name", "FMS Farm"),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    # Debug is OFF unless explicitly asked for. The Werkzeug debugger allows
    # arbitrary code execution through the browser, so `debug=True` on a farm
    # network - or during a public demonstration - is a remote shell.
    debug_enabled = os.environ.get("FMS_DEBUG", "").strip().lower() in ("1", "true", "on", "yes")
    app.run(
        debug=debug_enabled,
        host=os.environ.get("FMS_HOST", "0.0.0.0"),
        port=int(os.environ.get("FMS_PORT", "8010")),
    )
