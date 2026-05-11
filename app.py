import os
import sys
import cv2
import json
import time
import numpy as np
import hashlib
import secrets
import string
from datetime import datetime, date
from functools import wraps
from geopy.point import Point

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, flash, send_from_directory, Response, abort
)

from database import db
from models import (
    Setting,
    User,
    Worker,
    Attendance,
    AuditLog,
    CCTVFeed,
    Payroll,
    BiometricDevice,
    FaceTemplate,
    BiometricTransaction,
    CCTVRecording,
    EventSnapshot,
    OfflineSyncQueue,
    CloudSyncMetadata,
    DailyAttendanceSummary,
    HardwareHealthLog,
)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
CAPTURES_DIR = os.path.join(BASE_DIR, "captures")

FACE_CASCADE = cv2.CascadeClassifier(
    os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
)
EYE_CASCADE = cv2.CascadeClassifier(
    os.path.join(cv2.data.haarcascades, "haarcascade_eye.xml")
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.urandom(32)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(BASE_DIR, 'fms.db')}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()
        _seed_defaults()

    os.makedirs(CAPTURES_DIR, exist_ok=True)

    # Register routes
    _register_routes(app)

    return app


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def _seed_defaults() -> None:
    """Create default admin user and settings rows if they don't exist."""
    if not User.query.filter_by(username="admin").first():
        admin = User(username="admin", name="System Administrator", email="admin@example.com", phone="0000000000")
        admin.set_password("admin")
        db.session.add(admin)

    default_settings = {
        "org_name": "FMS Farm",
        "camera_index": "0",
        "camera_sources": "",
        "firebase_api_key": "",
        "firebase_bucket": "",
        "firebase_project_id": "",
    }
    for key, value in default_settings.items():
        if not Setting.query.filter_by(key=key).first():
            db.session.add(Setting(key=key, value=value))

    db.session.commit()
    _ensure_default_cctv_entries()


def _ensure_default_cctv_entries() -> None:
    """Ensure built-in camera has baseline feed and recording rows."""
    camera_index = _get_setting("camera_index", "0").strip() or "0"
    builtin_url = f"builtin://{camera_index}"
    builtin_name = f"Built-in Camera {camera_index}"

    feed = CCTVFeed.query.filter_by(rtsp_url=builtin_url).first()
    if not feed:
        feed = CCTVFeed(
            camera_name=builtin_name,
            camera_location="Local Device",
            rtsp_url=builtin_url,
            status="online",
            last_heartbeat=datetime.utcnow(),
        )
        db.session.add(feed)
        db.session.flush()

    marker_path = f"default://builtin-camera-{camera_index}"
    existing_marker = CCTVRecording.query.filter_by(
        camera_id=feed.feed_id,
        recording_path=marker_path,
    ).first()
    if not existing_marker:
        now = datetime.utcnow()
        db.session.add(CCTVRecording(
            camera_id=feed.feed_id,
            recording_path=marker_path,
            start_time=now,
            end_time=now,
            file_size_bytes=0,
            storage_location="local",
            uploaded_to_cloud=False,
        ))

    db.session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def _generate_password(length: int = 8) -> str:
    """Generate a random alphanumeric password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _log_audit(action: str, details: str = "") -> None:
    """Write an audit log entry. Safe to call inside any request context."""
    try:
        username = session.get("admin_username", "system")
        ip = request.remote_addr or "—"
    except RuntimeError:
        username, ip = "system", "—"
    try:
        db.session.add(AuditLog(
            username=username, action=action, details=details, ip_address=ip
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _normalize_coordinates(lat_raw, lon_raw) -> tuple[float | None, float | None]:
    """Validate and normalize frontend latitude/longitude using geopy."""
    if lat_raw in (None, "") or lon_raw in (None, ""):
        return None, None
    try:
        point = Point(float(lat_raw), float(lon_raw))
        return float(point.latitude), float(point.longitude)
    except Exception:
        return None, None


def _pin_fingerprint(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def _is_pin_unique(pin: str, exclude_worker_id: str | None = None) -> bool:
    fp = _pin_fingerprint(pin)
    query = Worker.query.filter_by(pin_fingerprint=fp)
    if exclude_worker_id:
        query = query.filter(Worker.worker_id != exclude_worker_id)
    return query.first() is None


def _generate_worker_id() -> str:
    max_seq = 0
    for row in Worker.query.with_entities(Worker.worker_id).all():
        existing_id = (row.worker_id or "").strip()
        if existing_id.isdigit():
            max_seq = max(max_seq, int(existing_id))

    next_seq = max_seq + 1
    if next_seq > 9999:
        raise ValueError("Worker ID sequence exceeded 4 digits")

    while True:
        candidate = f"{next_seq:04d}"
        if not Worker.query.filter_by(worker_id=candidate).first():
            return candidate
        next_seq += 1


def _coerce_camera_source(source_value):
    if isinstance(source_value, int):
        return source_value
    source_text = str(source_value).strip()
    if source_text.isdigit():
        return int(source_text)
    return source_text


def _get_camera_sources() -> list[dict]:
    """Return configured camera sources or fallback to the built-in camera."""
    configured = _get_setting("camera_sources", "").strip()
    sources: list[dict] = []

    if configured:
        try:
            parsed = json.loads(configured)
            if isinstance(parsed, list):
                for idx, item in enumerate(parsed):
                    if not isinstance(item, dict):
                        continue
                    source = item.get("source")
                    if source is None or str(source).strip() == "":
                        continue
                    source_type = str(item.get("type", "usb")).strip().lower() or "usb"
                    name = str(item.get("name", f"Camera {idx + 1}")).strip() or f"Camera {idx + 1}"
                    sources.append({
                        "name": name,
                        "type": source_type,
                        "source": _coerce_camera_source(source),
                    })
        except json.JSONDecodeError:
            sources = []

    if not sources:
        sources.append({
            "name": "Built-in Camera",
            "type": "builtin",
            "source": _coerce_camera_source(_get_setting("camera_index", "0")),
        })

    return sources


def _verify_face_on_camera(timeout_seconds: float = 3.0, required_hits: int = 2) -> bool:
    """Validate worker presence by requiring repeated face+eye detections."""
    try:
        primary_source = _get_camera_sources()[0]["source"]
        cap = _open_camera(primary_source)
        if not cap.isOpened():
            cap.release()
            fallback_source = _coerce_camera_source(_get_setting("camera_index", "0"))
            cap = _open_camera(fallback_source)
        if not cap.isOpened():
            cap.release()
            return False

        start = time.time()
        hits = 0
        while time.time() - start < timeout_seconds:
            ok, frame = cap.read()
            if not ok:
                continue
            detections = _detect_faces_and_eyes(frame)
            valid = any(len(item.get("eyes", [])) > 0 for item in detections)
            if valid:
                hits += 1
                if hits >= required_hits:
                    cap.release()
                    return True
        cap.release()
        return False
    except Exception:
        return False


def _capture_photo(worker_id: str, require_face: bool = False) -> tuple[str | None, str]:
    """Capture a single frame from a camera source and save it locally.

    Returns (relative_path, status) where status is one of:
      - "ok"
      - "no_face"
      - "camera_error"
    """
    try:
        primary_source = _get_camera_sources()[0]["source"]
        cap = _open_camera(primary_source)
        if not cap.isOpened():
            cap.release()
            fallback_source = _coerce_camera_source(_get_setting("camera_index", "0"))
            cap = _open_camera(fallback_source)
        if not cap.isOpened():
            cap.release()
            return None, "camera_error"

        # Capture a clean, raw frame from camera buffer without drawing overlays.
        ret, frame = cap.read()
        for _ in range(2):
            ok, newer = cap.read()
            if ok:
                ret, frame = ok, newer
        cap.release()

        if not ret:
            return None, "camera_error"

        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{worker_id}_{timestamp_str}.jpg"
        filepath = os.path.join(CAPTURES_DIR, filename)
        cv2.imwrite(filepath, frame)
        return os.path.join("captures", filename), "ok"
    except Exception:
        return None, "camera_error"


def _upload_to_firebase(local_path: str) -> str | None:
    """Upload a file to Firebase Storage and return the public URL.
    Returns None if Firebase is not configured or upload fails.
    """
    api_key = _get_setting("firebase_api_key")
    bucket = _get_setting("firebase_bucket")
    if not api_key or not bucket:
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, storage

        if not firebase_admin._apps:
            cred = credentials.Certificate({
                "type": "service_account",
                "project_id": _get_setting("firebase_project_id"),
                "private_key_id": "placeholder",
                "private_key": api_key,
                "client_email": f"firebase-adminsdk@{_get_setting('firebase_project_id')}.iam.gserviceaccount.com",
                "token_uri": "https://oauth2.googleapis.com/token",
            })
            firebase_admin.initialize_app(cred, {"storageBucket": bucket})

        bucket_obj = storage.bucket()
        blob_name = os.path.basename(local_path)
        blob = bucket_obj.blob(f"captures/{blob_name}")
        blob.upload_from_filename(local_path)
        blob.make_public()
        return blob.public_url
    except Exception:
        return None


def _build_attendance_sessions(rows: list[Attendance]) -> list:
    """Build display sessions from Attendance rows, newest first."""
    sessions = []
    for row in rows:
        worker = Worker.query.get(row.worker_id)
        worker_code = worker.worker_id if worker else f"W{row.worker_id}"
        worker_name = worker.name if worker else worker_code

        snapshots = EventSnapshot.query.filter_by(attendance_id=row.attendance_id).order_by(EventSnapshot.captured_at.asc()).all()
        in_image = next((s.file_path for s in snapshots if "check_in" in (s.snapshot_type or "")), None)
        out_image = next((s.file_path for s in snapshots if "check_out" in (s.snapshot_type or "")), None)

        # Backward-compatible fallback: if typed snapshots are not present,
        # use first as check-in and last as check-out when available.
        if not in_image and snapshots:
            in_image = snapshots[0].file_path
        if not out_image and len(snapshots) > 1:
            out_image = snapshots[-1].file_path

        sort_key = row.check_out_time or row.check_in_time
        sessions.append({
            "worker_id": worker_code,
            "worker_name": worker_name,
            "date": row.check_in_time.strftime("%d %b %Y") if row.check_in_time else "—",
            "clock_in_time": row.check_in_time.strftime("%H:%M:%S") if row.check_in_time else None,
            "clock_in_image": in_image,
            "clock_out_time": row.check_out_time.strftime("%H:%M:%S") if row.check_out_time else None,
            "clock_out_image": out_image,
            "_sort_key": sort_key,
        })

    sessions.sort(key=lambda s: s["_sort_key"], reverse=True)
    return sessions


def _open_camera(source):
    """Open a VideoCapture using the best backend for the current platform."""
    if sys.platform.startswith("linux") and isinstance(source, int):
        # On Linux, avoid FFMPEG fallback for integer device indexes because
        # hosts without /dev/video* emit noisy "index out of range" errors.
        device_path = f"/dev/video{source}"
        if not os.path.exists(device_path):
            return cv2.VideoCapture()

        cap = cv2.VideoCapture(source, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            return cv2.VideoCapture()
        return cap

    if sys.platform == "darwin":
        backend = cv2.CAP_AVFOUNDATION
    elif sys.platform == "win32":
        backend = cv2.CAP_DSHOW
    else:
        backend = cv2.CAP_V4L2
    cap = cv2.VideoCapture(source, backend)
    if not cap.isOpened():
        # Try without a backend hint as last resort
        cap.release()
        cap = cv2.VideoCapture(source)
    return cap


def _detect_faces_and_eyes(frame) -> list[dict]:
    """Return face and eye bounding boxes for the provided frame."""
    if FACE_CASCADE.empty() or EYE_CASCADE.empty():
        return []

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.2,
        minNeighbors=5,
        minSize=(45, 45),
    )

    detections = []
    for (x, y, w, h) in faces:
        roi_gray = gray[y:y + h, x:x + w]
        eyes = EYE_CASCADE.detectMultiScale(
            roi_gray,
            scaleFactor=1.15,
            minNeighbors=6,
            minSize=(15, 15),
        )
        detections.append({
            "face": (x, y, w, h),
            "eyes": eyes,
        })
    return detections


def _draw_detections(frame, detections: list[dict]) -> None:
    """Overlay face and eye boxes directly on a frame."""
    for item in detections:
        x, y, w, h = item["face"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (40, 220, 40), 2)
        cv2.putText(
            frame,
            "Face",
            (x, max(20, y - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (40, 220, 40),
            2,
            cv2.LINE_AA,
        )
        for (ex, ey, ew, eh) in item["eyes"]:
            cv2.rectangle(frame, (x + ex, y + ey), (x + ex + ew, y + ey + eh), (255, 160, 20), 2)


def _detect_motion_regions(prev_gray, frame) -> tuple:
    """Detect movement regions between frames and return (boxes, current_gray)."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if prev_gray is None:
        return [], gray

    frame_delta = cv2.absdiff(prev_gray, gray)
    thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        if cv2.contourArea(contour) < 1800:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        boxes.append((x, y, w, h))

    return boxes, gray


def _draw_motion_regions(frame, boxes: list[tuple]) -> None:
    """Draw movement boxes on frame for live camera feedback."""
    for (x, y, w, h) in boxes:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 185, 255), 2)
        cv2.putText(
            frame,
            "Motion",
            (x, max(20, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 185, 255),
            2,
            cv2.LINE_AA,
        )


def _build_camera_unavailable_frame(message: str):
    """Create a readable fallback frame when a camera cannot be opened."""
    frame = np.zeros((420, 760, 3), dtype=np.uint8)
    frame[:, :] = (22, 28, 36)

    cv2.putText(
        frame,
        "Camera Stream Unavailable",
        (36, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        (245, 245, 245),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        message,
        (36, 170),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (180, 210, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "Tip: attach a webcam or set a valid RTSP/USB camera source in CCTV settings.",
        (36, 220),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (180, 180, 180),
        1,
        cv2.LINE_AA,
    )
    return frame


def _camera_frame_generator(source, fallback_source, overlay_faces: bool = False, overlay_motion: bool = False):
    """Yield clean MJPEG frames from a camera source with built-in fallback."""
    cap = _open_camera(source)
    if not cap.isOpened():
        cap.release()
        cap = _open_camera(fallback_source)
        if not cap.isOpened():
            cap.release()
            while True:
                frame = _build_camera_unavailable_frame("No camera device detected on this host")
                ok, buffer = cv2.imencode(".jpg", frame)
                if ok:
                    frame_bytes = buffer.tobytes()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
                    )
                time.sleep(1.0)

    # Warm up: discard the first few frames so the sensor stabilises
    for _ in range(3):
        cap.read()

    prev_gray = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if overlay_motion:
                boxes, prev_gray = _detect_motion_regions(prev_gray, frame)
                _draw_motion_regions(frame, boxes)

            if overlay_faces:
                detections = _detect_faces_and_eyes(frame)
                _draw_detections(frame, detections)

            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            frame_bytes = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
            )
            time.sleep(0.04)
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in to access the dashboard.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _register_routes(app: Flask) -> None:

    # ---- Serve captured images ------------------------------------------ #

    @app.route("/captures/<path:filename>")
    @admin_required
    def captured_image(filename):
        return send_from_directory(CAPTURES_DIR, filename)

    @app.route("/worker-camera-stream")
    def worker_camera_stream():
        """Public preview feed for worker clock-in page."""
        sources = _get_camera_sources()
        source = sources[0]["source"]
        fallback_source = _coerce_camera_source(_get_setting("camera_index", "0"))
        return Response(
            _camera_frame_generator(source, fallback_source, overlay_faces=True, overlay_motion=True),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    # ---- Login / Logout -------------------------------------------------- #

    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            mode = request.form.get("mode")  # "admin" or "worker"

            if mode == "admin":
                username = request.form.get("username", "").strip()
                password = request.form.get("password", "")
                user = User.query.filter_by(username=username).first()
                if user and user.check_password(password):
                    session["admin_logged_in"] = True
                    session["admin_username"] = username
                    _log_audit("login", f"Admin '{username}' logged in")
                    return redirect(url_for("dashboard"))
                flash("Invalid admin credentials.", "danger")

            elif mode == "worker":
                worker_id = request.form.get("worker_id", "").strip().upper()
                pin = request.form.get("pin", "").strip()
                log_type = request.form.get("log_type", "IN")  # "IN" or "OUT"
                lat, lon = _normalize_coordinates(
                    request.form.get("latitude"),
                    request.form.get("longitude"),
                )

                worker = Worker.query.filter_by(worker_id=worker_id).filter(Worker.status == "active").first()
                if not worker or not worker.check_pin(pin):
                    flash("Worker ID or PIN is incorrect.", "danger")
                    return render_template("login.html", org_name=_get_setting("org_name", "FMS Farm"))

                face_verified = False
                if log_type == "IN":
                    face_verified = _verify_face_on_camera()
                    if not face_verified:
                        _log_audit("attendance.verification_failed", f"Face verification failed for {worker_id}")
                        flash("Face verification failed. Please position your face clearly and try again.", "danger")
                        return render_template("login.html", org_name=_get_setting("org_name", "FMS Farm"))

                # Capture clean snapshot (no live feed overlays).
                local_path, capture_status = _capture_photo(worker_id, require_face=False)
                if capture_status != "ok" or not local_path:
                    _log_audit(
                        "attendance.capture_failed",
                        f"Capture failed for {worker_id} during {log_type}",
                    )
                    flash(
                        "Camera capture failed. Attendance was not recorded. Please try again.",
                        "danger",
                    )
                    return render_template("login.html", org_name=_get_setting("org_name", "FMS Farm"))

                image_path = local_path  # default to local

                if local_path:
                    firebase_url = _upload_to_firebase(os.path.join(BASE_DIR, local_path))
                    if firebase_url:
                        image_path = firebase_url

                if log_type == "OUT":
                    attendance_row = (
                        Attendance.query
                        .filter_by(worker_id=worker.id)
                        .filter(Attendance.check_out_time.is_(None))
                        .order_by(Attendance.check_in_time.desc())
                        .first()
                    )
                    if not attendance_row:
                        flash("No open check-in found. Please clock in first.", "danger")
                        return render_template("login.html", org_name=_get_setting("org_name", "FMS Farm"))
                    attendance_row.check_out_time = datetime.utcnow()
                    if lat is not None:
                        attendance_row.latitude = lat
                    if lon is not None:
                        attendance_row.longitude = lon
                else:
                    attendance_row = Attendance(
                        worker_id=worker.id,
                        check_in_time=datetime.utcnow(),
                        latitude=lat,
                        longitude=lon,
                        verified_by_cctv=face_verified,
                    )
                    db.session.add(attendance_row)
                    db.session.flush()

                db.session.add(EventSnapshot(
                    attendance_id=attendance_row.attendance_id,
                    snapshot_type="photo_check_in" if log_type == "IN" else "photo_check_out",
                    file_path=image_path,
                ))
                db.session.commit()
                _log_audit("attendance.recorded", f"Recorded {log_type} for {worker_id} (attendance_id={attendance_row.attendance_id})")

                flash(
                    f"Welcome, {worker.name}! Clock-{log_type} recorded at "
                    f"{datetime.utcnow().strftime('%H:%M:%S')}",
                    "success",
                )

        org_name = _get_setting("org_name", "FMS Farm")
        return render_template("login.html", org_name=org_name)

    @app.route("/logout")
    def logout():
        _log_audit("logout", f"Admin '{session.get('admin_username', '?')}' logged out")
        session.clear()
        return redirect(url_for("login"))

    # ---- Dashboard ------------------------------------------------------- #

    @app.route("/dashboard")
    @admin_required
    def dashboard():
        workers = Worker.query.order_by(Worker.created_at.desc()).all()
        active_workers_count = sum(1 for w in workers if (w.status or "").lower() == "active")
        attendance_rows = Attendance.query.order_by(Attendance.check_in_time.asc()).limit(400).all()
        sessions = _build_attendance_sessions(attendance_rows)
        today_count = sum(1 for s in sessions if s["_sort_key"].date() == date.today())
        camera_sources = _get_camera_sources()
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template(
            "dashboard.html",
            workers=workers,
            active_workers_count=active_workers_count,
            sessions=sessions,
            today_count=today_count,
            camera_sources=camera_sources,
            active_page="dashboard",
            org_name=org_name,
        )

    @app.route("/workers", methods=["GET", "POST"])
    @admin_required
    def workers_page():
        if request.method == "POST":
            # Compatibility path for stale cached forms posting back to /workers.
            flash("Form target was outdated. Please retry the action.", "warning")
            return redirect(url_for("workers_page"))

        workers = Worker.query.order_by(Worker.created_at.desc()).all()
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template(
            "workers.html",
            workers=workers,
            active_page="workers",
            org_name=org_name,
        )

    @app.route("/attendance")
    @admin_required
    def attendance_page():
        attendance_rows = Attendance.query.order_by(Attendance.check_in_time.asc()).limit(400).all()
        sessions = _build_attendance_sessions(attendance_rows)
        complete_count = sum(1 for s in sessions if s["clock_in_time"] and s["clock_out_time"])
        in_progress_count = sum(1 for s in sessions if s["clock_in_time"] and not s["clock_out_time"])
        out_only_count = sum(1 for s in sessions if (not s["clock_in_time"]) and s["clock_out_time"])
        today_count = sum(1 for s in sessions if s["_sort_key"] and s["_sort_key"].date() == date.today())
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template(
            "attendance.html",
            sessions=sessions,
            attendance_stats={
                "total": len(sessions),
                "complete": complete_count,
                "in_progress": in_progress_count,
                "out_only": out_only_count,
                "today": today_count,
            },
            active_page="attendance",
            org_name=org_name,
        )

    # ---- Worker management ---------------------------------------------- #

    @app.route("/workers/add", methods=["POST"])
    @admin_required
    def add_worker():
        name = request.form.get("name", "").strip()
        phone_number = request.form.get("phone_number", "").strip()
        address = request.form.get("address", "").strip()
        emergency_contact = request.form.get("emergency_contact", "").strip()
        pin = request.form.get("pin", "").strip()
        department = request.form.get("department", "").strip()
        nrc_number = request.form.get("nrc_number", "").strip()
        status = request.form.get("status", "active").strip().lower() or "active"
        enrollment_date_raw = request.form.get("enrollment_date", "").strip()

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
        if enrollment_date_raw:
            try:
                enrollment_date = datetime.strptime(enrollment_date_raw, "%Y-%m-%d")
            except ValueError:
                flash("Enrollment date is invalid.", "danger")
                return redirect(url_for("workers_page"))

        worker_id = _generate_worker_id()
        worker = Worker(
            worker_id=worker_id,
            name=name,
            nrc_number=nrc_number or None,
            phone_number=phone_number,
            address=address,
            emergency_contact=emergency_contact,
            department=department,
            enrollment_date=enrollment_date,
            status=status,
            pin_fingerprint=_pin_fingerprint(pin),
        )
        worker.set_pin(pin)
        db.session.add(worker)
        db.session.commit()
        _log_audit("worker.add", f"Added worker {worker_id} — {name}")
        flash(f"Worker '{name}' added successfully. Generated ID: {worker_id}", "success")
        return redirect(url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/update", methods=["POST"])
    @admin_required
    def update_worker(worker_pk):
        worker = Worker.query.get_or_404(worker_pk)
        worker.name = request.form.get("name", "").strip()
        worker.phone_number = request.form.get("phone_number", "").strip()
        worker.address = request.form.get("address", "").strip()
        worker.emergency_contact = request.form.get("emergency_contact", "").strip()
        worker.department = request.form.get("department", "").strip()
        worker.nrc_number = request.form.get("nrc_number", "").strip() or None
        worker.status = request.form.get("status", "active").strip().lower() or "active"
        enrollment_date_raw = request.form.get("enrollment_date", "").strip()

        if not worker.name or not worker.phone_number:
            flash("Worker name and phone number are required.", "danger")
            return redirect(url_for("workers_page"))

        if worker.nrc_number:
            existing = Worker.query.filter_by(nrc_number=worker.nrc_number).first()
            if existing and existing.id != worker.id:
                flash("NRC number already exists for another worker.", "danger")
                return redirect(url_for("workers_page"))

        if enrollment_date_raw:
            try:
                worker.enrollment_date = datetime.strptime(enrollment_date_raw, "%Y-%m-%d")
            except ValueError:
                flash("Enrollment date is invalid.", "danger")
                return redirect(url_for("workers_page"))

        db.session.commit()
        _log_audit("worker.update", f"Updated worker {worker.worker_id}")
        flash(f"Worker '{worker.worker_id}' updated successfully.", "success")
        return redirect(url_for("workers_page"))

    @app.route("/workers/<int:worker_pk>/reset-pin", methods=["POST"])
    @admin_required
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
    @admin_required
    def toggle_worker(worker_pk):
        worker = Worker.query.get_or_404(worker_pk)
        worker.status = "inactive" if (worker.status or "active").lower() == "active" else "active"
        db.session.commit()
        status = "activated" if worker.status == "active" else "deactivated"
        _log_audit("worker.toggle", f"Worker {worker.worker_id} {status}")
        flash(f"Worker '{worker.name}' has been {status}.", "info")
        return redirect(url_for("workers_page"))

    # ---- Settings -------------------------------------------------------- #

    @app.route("/settings", methods=["GET", "POST"])
    @admin_required
    def settings():
        if request.method == "POST":
            keys = ["org_name"]
            for key in keys:
                value = request.form.get(key, "").strip()
                row = Setting.query.filter_by(key=key).first()
                if row:
                    row.value = value
                else:
                    db.session.add(Setting(key=key, value=value))

            db.session.commit()
            _log_audit("settings.save", "Settings updated")
            flash("Settings saved.", "success")
            return redirect(url_for("settings"))

        all_settings = {s.key: s.value for s in Setting.query.all()}
        return render_template(
            "settings.html",
            settings=all_settings,
            active_page="settings",
            org_name=_get_setting("org_name"),
        )

    # ---- User management ------------------------------------------------- #

    @app.route("/users")
    @admin_required
    def users_page():
        users = User.query.order_by(User.created_at.desc()).all()
        workers = Worker.query.order_by(Worker.worker_id.asc()).all()
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template("users.html", users=users, workers=workers, active_page="users", org_name=org_name)

    @app.route("/users/add", methods=["POST"])
    @admin_required
    def add_user():
        username = request.form.get("username", "").strip().lower()
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "supervisor").strip().lower() or "supervisor"
        linked_worker_id = request.form.get("linked_worker_id", type=int)
        if not username or not name:
            flash("Username and Name are required.", "danger")
            return redirect(url_for("users_page"))
        if User.query.filter_by(username=username).first():
            flash(f"Username '{username}' already exists.", "danger")
            return redirect(url_for("users_page"))
        password = _generate_password()
        user = User(
            username=username,
            name=name,
            email=email,
            phone=phone,
            role=role,
            linked_worker_id=linked_worker_id,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        _log_audit("user.add", f"Added user '{username}'")
        flash(f"User '{username}' created. Default password: {password}", "success")
        return redirect(url_for("users_page"))

    @app.route("/users/<int:user_pk>/update", methods=["POST"])
    @admin_required
    def update_user(user_pk: int):
        user = User.query.get_or_404(user_pk)

        user.name = request.form.get("name", "").strip()
        user.email = request.form.get("email", "").strip()
        user.phone = request.form.get("phone", "").strip()
        user.role = request.form.get("role", "supervisor").strip().lower() or "supervisor"
        user.linked_worker_id = request.form.get("linked_worker_id", type=int)
        if not user.name:
            flash("Name is required.", "danger")
            return redirect(url_for("users_page"))
        db.session.commit()
        _log_audit("user.update", f"Updated user '{user.username}'")
        flash(f"User '{user.username}' updated.", "success")
        return redirect(url_for("users_page"))

    @app.route("/users/<int:user_pk>/reset-password", methods=["POST"])
    @admin_required
    def reset_user_password(user_pk: int):
        user = User.query.get_or_404(user_pk)

        password = _generate_password()
        user.set_password(password)
        db.session.commit()
        _log_audit("user.reset_password", f"Reset password for '{user.username}'")
        flash(f"Password for '{user.username}' reset. New password: {password}", "success")
        return redirect(url_for("users_page"))

    # ---- Change own password --------------------------------------------- #

    @app.route("/profile/change-password", methods=["POST"])
    @admin_required
    def change_password():
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        username = session.get("admin_username")
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(current_password):
            flash("Current password is incorrect.", "danger")
            return redirect(request.referrer or url_for("dashboard"))
        if len(new_password) < 6:
            flash("New password must be at least 6 characters.", "danger")
            return redirect(request.referrer or url_for("dashboard"))
        if new_password != confirm_password:
            flash("New passwords do not match.", "danger")
            return redirect(request.referrer or url_for("dashboard"))
        user.set_password(new_password)
        db.session.commit()
        _log_audit("user.change_password", f"'{username}' changed own password")
        flash("Password changed successfully.", "success")
        return redirect(request.referrer or url_for("dashboard"))

    # ---- Audit log ------------------------------------------------------- #

    @app.route("/audit-log")
    @admin_required
    def audit_log_page():
        logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(500).all()
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template("audit_log.html", logs=logs, active_page="audit_log", org_name=org_name)

    @app.route("/tables-hub")
    @admin_required
    def tables_hub_page():
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template(
            "tables_hub.html",
            active_page="tables_hub",
            org_name=org_name,
        )

    @app.route("/cctv")
    @admin_required
    def cctv_page():
        _ensure_default_cctv_entries()
        feeds = CCTVFeed.query.order_by(CCTVFeed.feed_id.desc()).all()
        recordings = CCTVRecording.query.order_by(CCTVRecording.recording_id.desc()).limit(150).all()
        settings = {s.key: s.value for s in Setting.query.all()}
        return render_template(
            "cctv.html",
            active_page="cctv",
            org_name=_get_setting("org_name", "FMS Farm"),
            feeds=feeds,
            recordings=recordings,
            settings=settings,
        )

    @app.route("/biometric")
    @admin_required
    def biometric_page():
        devices = BiometricDevice.query.order_by(BiometricDevice.created_at.desc()).limit(200).all()
        return render_template(
            "biometric.html",
            active_page="biometric",
            org_name=_get_setting("org_name", "FMS Farm"),
            devices=devices,
        )

    @app.route("/payroll")
    @admin_required
    def payroll_page():
        workers = Worker.query.order_by(Worker.worker_id.asc()).all()
        worker_lookup = {w.id: w for w in workers}
        payroll_rows = Payroll.query.order_by(Payroll.payroll_id.desc()).limit(200).all()
        return render_template(
            "payroll.html",
            active_page="payroll",
            org_name=_get_setting("org_name", "FMS Farm"),
            workers=workers,
            worker_lookup=worker_lookup,
            payroll_rows=payroll_rows,
        )

    @app.route("/cloud-sync", methods=["GET", "POST"])
    @admin_required
    def cloud_sync_page():
        if request.method == "POST":
            keys = ["firebase_api_key", "firebase_bucket", "firebase_project_id"]
            for key in keys:
                value = request.form.get(key, "").strip()
                row = Setting.query.filter_by(key=key).first()
                if row:
                    row.value = value
                else:
                    db.session.add(Setting(key=key, value=value))
            db.session.commit()
            _log_audit("cloud_sync.settings.save", "Updated cloud sync settings")
            flash("Cloud sync settings saved.", "success")
            return redirect(url_for("cloud_sync_page"))

        metadata_rows = CloudSyncMetadata.query.order_by(CloudSyncMetadata.sync_id.desc()).limit(200).all()
        queue_rows = OfflineSyncQueue.query.order_by(OfflineSyncQueue.sync_id.desc()).limit(200).all()
        settings = {s.key: s.value for s in Setting.query.all()}
        return render_template(
            "cloud_sync.html",
            active_page="cloud_sync",
            org_name=_get_setting("org_name", "FMS Farm"),
            metadata_rows=metadata_rows,
            queue_rows=queue_rows,
            settings=settings,
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
        data_rows = [{col: getattr(row, col, None) for col in columns} for row in rows]
        return render_template(
            "table_records.html",
            active_page="tables_hub",
            org_name=_get_setting("org_name", "FMS Farm"),
            table_title=title,
            columns=columns,
            rows=data_rows,
            table_key=table_key,
        )

    @app.route("/config/cctv-feeds", methods=["POST"])
    @admin_required
    def add_cctv_feed():
        camera_name = request.form.get("camera_name", "").strip()
        if not camera_name:
            flash("Camera name is required.", "danger")
            return redirect(url_for("tables_hub_page"))
        row = CCTVFeed(
            camera_name=camera_name,
            camera_location=request.form.get("camera_location", "").strip(),
            rtsp_url=request.form.get("rtsp_url", "").strip(),
            status="offline",
        )
        db.session.add(row)
        db.session.commit()
        _log_audit("config.cctv_feed.add", f"Added CCTV feed '{camera_name}'")
        flash("CCTV feed saved.", "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv-feeds/<int:feed_id>/update", methods=["POST"])
    @admin_required
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
    @admin_required
    def deactivate_cctv_feed(feed_id: int):
        feed = CCTVFeed.query.get_or_404(feed_id)
        feed.status = "inactive"
        db.session.commit()
        _log_audit("config.cctv_feed.deactivate", f"Deactivated CCTV feed '{feed.camera_name}' (id={feed.feed_id})")
        flash("CCTV feed deactivated.", "info")
        return redirect(url_for("cctv_page"))

    @app.route("/config/cctv/settings", methods=["POST"])
    @admin_required
    def save_cctv_settings():
        camera_index = request.form.get("camera_index", "0").strip() or "0"
        camera_sources_raw = request.form.get("camera_sources", "").strip()

        if camera_sources_raw:
            try:
                parsed = json.loads(camera_sources_raw)
                if not isinstance(parsed, list):
                    raise ValueError("Camera sources must be a JSON array")
            except (json.JSONDecodeError, ValueError):
                flash("Camera sources must be valid JSON array format.", "danger")
                return redirect(url_for("cctv_page"))

        for key, value in {
            "camera_index": camera_index,
            "camera_sources": camera_sources_raw,
        }.items():
            row = Setting.query.filter_by(key=key).first()
            if row:
                row.value = value
            else:
                db.session.add(Setting(key=key, value=value))

        db.session.commit()
        _ensure_default_cctv_entries()
        _log_audit("cctv.settings.save", "Updated CCTV settings")
        flash("CCTV settings saved.", "success")
        return redirect(url_for("cctv_page"))

    @app.route("/config/biometric-devices", methods=["POST"])
    @admin_required
    def add_biometric_device():
        device_name = request.form.get("device_name", "").strip()
        if not device_name:
            flash("Device name is required.", "danger")
            return redirect(url_for("tables_hub_page"))
        row = BiometricDevice(
            device_name=device_name,
            device_serial=request.form.get("device_serial", "").strip() or None,
            location=request.form.get("location", "").strip(),
        )
        db.session.add(row)
        db.session.commit()
        _log_audit("config.biometric_device.add", f"Added biometric device '{device_name}'")
        flash("Biometric device saved.", "success")
        return redirect(url_for("biometric_page"))

    @app.route("/config/biometric-devices/<int:device_id>/update", methods=["POST"])
    @admin_required
    def update_biometric_device(device_id: int):
        device = BiometricDevice.query.get_or_404(device_id)
        device_name = request.form.get("device_name", "").strip()
        if not device_name:
            flash("Device name is required.", "danger")
            return redirect(url_for("biometric_page"))

        device.device_name = device_name
        device.device_serial = request.form.get("device_serial", "").strip() or None
        device.device_type = request.form.get("device_type", "fingerprint").strip().lower() or "fingerprint"
        device.ip_address = request.form.get("ip_address", "").strip() or None
        device.usb_port = request.form.get("usb_port", "").strip() or None
        device.location = request.form.get("location", "").strip()
        status = request.form.get("status", "offline").strip().lower() or "offline"
        device.status = status
        if status == "online":
            device.last_heartbeat = datetime.utcnow()

        db.session.commit()
        _log_audit("config.biometric_device.update", f"Updated biometric device '{device.device_name}' (id={device.device_id})")
        flash("Biometric device updated.", "success")
        return redirect(url_for("biometric_page"))

    @app.route("/config/biometric-devices/<int:device_id>/deactivate", methods=["POST"])
    @admin_required
    def deactivate_biometric_device(device_id: int):
        device = BiometricDevice.query.get_or_404(device_id)
        device.status = "inactive"
        db.session.commit()
        _log_audit("config.biometric_device.deactivate", f"Deactivated biometric device '{device.device_name}' (id={device.device_id})")
        flash("Biometric device deactivated.", "info")
        return redirect(url_for("biometric_page"))

    @app.route("/config/payroll", methods=["POST"])
    @admin_required
    def add_payroll_record():
        worker_pk = request.form.get("worker_id", type=int)
        week_ending_raw = request.form.get("week_ending", "").strip()
        if not worker_pk or not week_ending_raw:
            flash("Worker and week ending are required.", "danger")
            return redirect(url_for("payroll_page"))
        try:
            week_ending = datetime.strptime(week_ending_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Week ending date format is invalid.", "danger")
            return redirect(url_for("payroll_page"))
        row = Payroll(
            worker_id=worker_pk,
            week_ending=week_ending,
            total_hours=request.form.get("total_hours", type=float),
            hourly_rate=request.form.get("hourly_rate", type=float),
            gross_pay=request.form.get("gross_pay", type=float),
            paid_status="pending",
        )
        db.session.add(row)
        db.session.commit()
        _log_audit("config.payroll.add", f"Added payroll row for worker_id={worker_pk}")
        flash("Payroll record saved.", "success")
        return redirect(url_for("payroll_page"))

    @app.route("/config/payroll/<int:payroll_id>/update", methods=["POST"])
    @admin_required
    def update_payroll_record(payroll_id: int):
        row = Payroll.query.get_or_404(payroll_id)
        worker_pk = request.form.get("worker_id", type=int)
        week_ending_raw = request.form.get("week_ending", "").strip()
        if not worker_pk or not week_ending_raw:
            flash("Worker and week ending are required.", "danger")
            return redirect(url_for("payroll_page"))
        try:
            week_ending = datetime.strptime(week_ending_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Week ending date format is invalid.", "danger")
            return redirect(url_for("payroll_page"))

        payment_date_raw = request.form.get("payment_date", "").strip()
        payment_date = None
        if payment_date_raw:
            try:
                payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
            except ValueError:
                flash("Payment date format is invalid.", "danger")
                return redirect(url_for("payroll_page"))

        row.worker_id = worker_pk
        row.week_ending = week_ending
        row.total_hours = request.form.get("total_hours", type=float)
        row.hourly_rate = request.form.get("hourly_rate", type=float)
        row.gross_pay = request.form.get("gross_pay", type=float)
        row.napsa_deduction = request.form.get("napsa_deduction", type=float)
        row.nhima_deduction = request.form.get("nhima_deduction", type=float)
        row.net_pay = request.form.get("net_pay", type=float)
        row.paid_status = request.form.get("paid_status", "pending").strip().lower() or "pending"
        row.payment_date = payment_date

        db.session.commit()
        _log_audit("config.payroll.update", f"Updated payroll row id={row.payroll_id}")
        flash("Payroll record updated.", "success")
        return redirect(url_for("payroll_page"))

    @app.route("/config/payroll/<int:payroll_id>/deactivate", methods=["POST"])
    @admin_required
    def deactivate_payroll_record(payroll_id: int):
        row = Payroll.query.get_or_404(payroll_id)
        row.paid_status = "inactive"
        db.session.commit()
        _log_audit("config.payroll.deactivate", f"Deactivated payroll row id={row.payroll_id}")
        flash("Payroll record deactivated.", "info")
        return redirect(url_for("payroll_page"))

    # ---- Manual ---------------------------------------------------------- #

    @app.route("/manual")
    def manual():
        org_name = _get_setting("org_name", "FMS Farm")
        return render_template("manual.html", active_page="manual", org_name=org_name)

    @app.route("/camera-stream/<int:camera_idx>")
    @admin_required
    def camera_stream(camera_idx: int):
        sources = _get_camera_sources()
        if camera_idx < 0 or camera_idx >= len(sources):
            abort(404)

        source = sources[camera_idx]["source"]
        # Resolve fallback here (inside app context) so the generator
        # never needs to touch the database.
        fallback_source = _coerce_camera_source(_get_setting("camera_index", "0"))
        return Response(
            _camera_frame_generator(source, fallback_source, overlay_faces=True, overlay_motion=True),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=6000)
