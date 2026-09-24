"""JSON API (v1).

The proposal assigns "backend API development, creating the endpoints that
connect all system modules" - the first release had none, which also meant there
was nothing to test in Postman and no way for a mobile client to talk to the
system. Every endpoint below is read-only except the two marked POST.

Authentication: send `X-API-Key: <key>` (Settings -> API key), or call from a
signed-in browser session.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session

import attendance_service
import cctv_engine
import face_engine
import payroll_engine
import sync_engine
from database import db
from models import (
    Attendance,
    BiometricTransaction,
    CCTVFeed,
    CCTVRecording,
    DailyAttendanceSummary,
    Payroll,
    Setting,
    Worker,
)
from paths import BASE_DIR

# Versioned prefix from the start: a mobile client shipped to a farm cannot be
# updated in step with the server, so /api/v1 has to keep working when /api/v2
# arrives.
api = Blueprint("api", __name__, url_prefix="/api/v1")


def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def api_key_required(f):
    """Allow either an API key header or a signed-in browser session.

    The session path is what lets the dashboard's own pages call these
    endpoints without embedding the key in HTML. The key path is for Postman
    and any future mobile client:

        curl -H "X-API-Key: $KEY" http://localhost:8010/api/v1/workers

    Anyone holding the key can read worker and attendance data, so Settings
    offers a regenerate button.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("admin_logged_in"):
            return f(*args, **kwargs)
        expected = _setting("api_key")
        supplied = request.headers.get("X-API-Key", "")
        if expected and supplied and supplied == expected:
            return f(*args, **kwargs)
        return jsonify({"ok": False, "error": "unauthorised",
                        "detail": "Send X-API-Key or use a signed-in session."}), 401
    return decorated


def _parse_date(raw: str | None, fallback: date | None = None) -> date | None:
    if not raw:
        return fallback
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        return fallback


def _worker_json(worker: Worker, samples: int = 0) -> dict:
    return {
        "id": worker.id,
        "worker_id": worker.worker_id,
        "name": worker.name,
        "department": worker.department,
        "phone_number": worker.phone_number,
        "status": worker.status,
        "hourly_rate": worker.hourly_rate,
        "face_enrolled": samples > 0,
        "face_samples": samples,
        "enrolled_at": worker.face_enrolled_at.isoformat() if worker.face_enrolled_at else None,
    }


# ---------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------

@api.get("/health")
def health():
    """Open endpoint: is the service up, and is it actually able to work?

    Deliberately unauthenticated, because Docker's HEALTHCHECK polls it and a
    container health probe cannot hold a secret. It exposes counts and
    capability, never worker data.

    Also the quickest way to spot the packaging trap: `face_engine.algorithm`
    reads "LBPH" when opencv-contrib-python is correctly installed and
    "correlation-fallback" when it is not.
    """
    sources = cctv_engine.get_camera_sources()
    return jsonify({
        "ok": True,
        "service": "fms",
        "time": datetime.utcnow().isoformat(),
        "workers": Worker.query.count(),
        "open_sessions": Attendance.query.filter(Attendance.check_out_time.is_(None)).count(),
        "cameras": len(sources),
        "face_engine": face_engine.engine_info(),
    })


@api.get("/verification/stats")
@api_key_required
def verification_stats():
    return jsonify({"ok": True, "data": face_engine.accuracy_snapshot()})


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

@api.get("/workers")
@api_key_required
def list_workers():
    counts = face_engine.sample_counts()
    workers = Worker.query.order_by(Worker.worker_id.asc()).all()
    return jsonify({"ok": True, "count": len(workers),
                    "data": [_worker_json(w, counts.get(w.id, 0)) for w in workers]})


@api.get("/workers/<worker_code>")
@api_key_required
def get_worker(worker_code: str):
    worker = Worker.query.filter_by(worker_id=worker_code.strip()).first()
    if not worker:
        return jsonify({"ok": False, "error": "not_found"}), 404
    return jsonify({"ok": True, "data": _worker_json(worker, face_engine.sample_count_for(worker.id))})


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

@api.get("/attendance")
@api_key_required
def list_attendance():
    day_from = _parse_date(request.args.get("from"), date.today() - timedelta(days=30))
    day_to = _parse_date(request.args.get("to"), date.today())
    worker_code = (request.args.get("worker") or "").strip()

    query = Attendance.query.filter(
        Attendance.check_in_time >= datetime.combine(day_from, datetime.min.time()),
        Attendance.check_in_time < datetime.combine(day_to + timedelta(days=1), datetime.min.time()),
    )
    if worker_code:
        worker = Worker.query.filter_by(worker_id=worker_code).first()
        if not worker:
            return jsonify({"ok": False, "error": "worker_not_found"}), 404
        query = query.filter(Attendance.worker_id == worker.id)

    workers = {w.id: w for w in Worker.query.all()}
    rows = query.order_by(Attendance.check_in_time.desc()).limit(1000).all()
    data = []
    for row in rows:
        worker = workers.get(row.worker_id)
        data.append({
            "attendance_id": row.attendance_id,
            "worker_id": worker.worker_id if worker else row.worker_id,
            "worker_name": worker.name if worker else None,
            "check_in": row.check_in_time.isoformat() if row.check_in_time else None,
            "check_out": row.check_out_time.isoformat() if row.check_out_time else None,
            "verified_by_face": bool(row.verified_by_face),
            "match_score": row.check_in_match_score,
            "snapshot_captured": bool(row.verified_by_cctv),
            "within_geofence": row.within_geofence,
            "distance_from_farm_m": row.distance_from_farm_m,
        })
    return jsonify({"ok": True, "from": day_from.isoformat(), "to": day_to.isoformat(),
                    "count": len(data), "data": data})


@api.post("/attendance/clock")
@api_key_required
def clock():
    """Record a punch through the same pipeline as the web page.

        POST /api/v1/attendance/clock
        {"worker_id": "0001", "pin": "1000", "log_type": "IN",
         "latitude": -15.4067, "longitude": 28.2871}

    Identity is still verified from the server's own camera - the API cannot
    bypass the face match, which is why there is no image parameter. Returns
    422 with a `code` such as "face_did_not_match" or "outside_geofence" when
    the punch is refused, and 401 for bad credentials.
    """
    payload = request.get_json(silent=True) or request.form
    worker_code = str(payload.get("worker_id", "")).strip().upper()
    pin = str(payload.get("pin", "")).strip()
    log_type = str(payload.get("log_type", "IN")).strip().upper()

    worker = Worker.query.filter_by(worker_id=worker_code).filter(Worker.status == "active").first()
    if not worker or not worker.check_pin(pin):
        return jsonify({"ok": False, "error": "invalid_credentials"}), 401

    lat, lon = None, None
    try:
        from geofence import normalize_coordinates
        lat, lon = normalize_coordinates(payload.get("latitude"), payload.get("longitude"))
    except Exception:
        pass

    outcome = attendance_service.record_punch(
        current_app._get_current_object(), worker, log_type, lat, lon
    )
    status = 200 if outcome["ok"] else 422
    return jsonify({
        "ok": outcome["ok"],
        "code": outcome["code"],
        "message": outcome["message"],
        "attendance_id": outcome["attendance_id"],
        "match_score": outcome["score"],
        "threshold": outcome["threshold"],
        "geofence": outcome["geofence"],
    }), status


@api.get("/summary/daily")
@api_key_required
def daily_summary():
    day_from = _parse_date(request.args.get("from"), date.today() - timedelta(days=14))
    day_to = _parse_date(request.args.get("to"), date.today())
    workers = {w.id: w for w in Worker.query.all()}
    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.summary_date >= day_from)
            .filter(DailyAttendanceSummary.summary_date <= day_to)
            .order_by(DailyAttendanceSummary.summary_date.desc()).all())
    return jsonify({"ok": True, "count": len(rows), "data": [{
        "date": r.summary_date.isoformat(),
        "worker_id": workers[r.worker_id].worker_id if r.worker_id in workers else r.worker_id,
        "total_hours": r.total_hours,
        "overtime_hours": r.overtime_hours,
        "late_minutes": r.late_minutes,
        "early_departure_minutes": r.early_departure_minutes,
        "verified_by_face": bool(r.verified_by_face),
    } for r in rows]})


@api.get("/attendance/trend")
@api_key_required
def trend():
    days = request.args.get("days", type=int) or 14
    return jsonify({"ok": True, "data": payroll_engine.attendance_trend(days)})


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------

@api.get("/payroll")
@api_key_required
def list_payroll():
    week_ending = _parse_date(request.args.get("week_ending"))
    query = Payroll.query
    if week_ending:
        query = query.filter(Payroll.week_ending == week_ending)
    workers = {w.id: w for w in Worker.query.all()}
    rows = query.order_by(Payroll.week_ending.desc()).limit(500).all()
    return jsonify({"ok": True, "count": len(rows), "currency": "ZMW", "data": [{
        "payroll_id": r.payroll_id,
        "worker_id": workers[r.worker_id].worker_id if r.worker_id in workers else r.worker_id,
        "week_ending": r.week_ending.isoformat() if r.week_ending else None,
        "total_hours": r.total_hours,
        "overtime_hours": r.overtime_hours,
        "hourly_rate": r.hourly_rate,
        "gross_pay": r.gross_pay,
        "napsa_deduction": r.napsa_deduction,
        "nhima_deduction": r.nhima_deduction,
        "net_pay": r.net_pay,
        "source": "computed" if r.computed_from_attendance else "manual",
        "paid_status": r.paid_status,
    } for r in rows]})


@api.post("/payroll/generate")
@api_key_required
def generate_payroll():
    """Generate one pay period from recorded attendance.

        POST /api/v1/payroll/generate   {"week_ending": "2026-08-23"}
        POST /api/v1/payroll/generate   {"week_ending": "2026-09-23",
                                         "period_type": "monthly"}

    `period_type` is optional and defaults to the farm-wide cycle in Settings.
    The date parameter keeps its original name so clients written before other
    cycles existed keep working; for weekly and fortnightly it is the last day
    of the period, and for semi-monthly and monthly it is any day inside it.

    Only workers on the requested cycle are touched.

    Idempotent in the ways that matter: a period already marked paid is
    skipped, and so is any worker whose days are already covered by a
    different paid period, so a retry after a network timeout cannot rewrite
    settled pay or pay the same day twice.
    """
    payload = request.get_json(silent=True) or request.form
    anchor = _parse_date(payload.get("week_ending") or payload.get("period_end"))
    if not anchor:
        return jsonify({"ok": False, "error": "week_ending_required",
                        "detail": "Supply week_ending as YYYY-MM-DD."}), 400

    requested = (payload.get("period_type") or "").strip().lower()
    if requested and requested not in payroll_engine.PERIODS:
        return jsonify({"ok": False, "error": "unknown_period_type",
                        "detail": "period_type must be one of: "
                                  + ", ".join(payroll_engine.PERIODS)}), 400

    outcome = payroll_engine.generate_period(anchor, requested or None)
    return jsonify({"ok": True, "data": outcome})


# ---------------------------------------------------------------------------
# CCTV, biometrics, sync
# ---------------------------------------------------------------------------

@api.get("/cctv/feeds")
@api_key_required
def list_feeds():
    feeds = CCTVFeed.query.order_by(CCTVFeed.feed_id.asc()).all()
    return jsonify({"ok": True, "count": len(feeds), "data": [{
        "feed_id": f.feed_id,
        "camera_name": f.camera_name,
        "camera_location": f.camera_location,
        "rtsp_url": f.rtsp_url,
        "status": f.status,
        "is_primary": bool(f.is_primary),
        "last_heartbeat": f.last_heartbeat.isoformat() if f.last_heartbeat else None,
    } for f in feeds], "stream_sources": [
        {"index": i, "name": s["name"], "type": s["type"]}
        for i, s in enumerate(cctv_engine.get_camera_sources())
    ]})


@api.get("/cctv/recordings")
@api_key_required
def list_recordings():
    """Stored clips, newest first.

    Filters out the legacy `default://` marker row the first release seeded,
    which was never a real file.
    """
    rows = (CCTVRecording.query
            .filter(~CCTVRecording.recording_path.like("default://%"))
            .order_by(CCTVRecording.recording_id.desc()).limit(200).all())
    return jsonify({"ok": True, "count": len(rows), "data": [{
        "recording_id": r.recording_id,
        "camera_id": r.camera_id,
        "attendance_id": r.attendance_id,
        "trigger_type": r.trigger_type,
        "path": r.recording_path,
        "start_time": r.start_time.isoformat() if r.start_time else None,
        "duration_seconds": r.duration_seconds,
        "file_size_bytes": r.file_size_bytes,
    } for r in rows]})


@api.get("/biometric/transactions")
@api_key_required
def list_transactions():
    rows = (BiometricTransaction.query
            .order_by(BiometricTransaction.timestamp.desc()).limit(300).all())
    workers = {w.id: w for w in Worker.query.all()}
    return jsonify({"ok": True, "count": len(rows), "data": [{
        "transaction_id": r.transaction_id,
        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        "worker_id": workers[r.worker_id].worker_id if r.worker_id in workers else r.worker_id,
        "type": r.transaction_type,
        "modality": r.modality,
        "success": bool(r.success),
        "match_score": r.match_score,
        "threshold": r.threshold_used,
        "reason": r.error_message,
    } for r in rows]})


@api.get("/sync/queue")
@api_key_required
def sync_queue():
    return jsonify({"ok": True, "data": sync_engine.queue_stats()})


@api.post("/sync/drain")
@api_key_required
def sync_drain():
    return jsonify({"ok": True, "data": sync_engine.drain(BASE_DIR)})
