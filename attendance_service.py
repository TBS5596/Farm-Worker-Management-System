"""The clock-in / clock-out pipeline.

One implementation shared by the web page and the JSON API, so the two can
never drift apart. The order of operations matters:

    identity -> location -> snapshot -> attendance row -> clip -> summary

Identity is checked first because a punch that cannot be attributed to a known
worker should never reach the attendance table at all.
"""

from __future__ import annotations

import os
from datetime import datetime

import cv2

import cctv_engine
import face_engine
import geofence
import payroll_engine
import sync_engine
from database import db
from models import Attendance, BiometricTransaction, EventSnapshot, Setting, Worker
from paths import BASE_DIR, CAPTURES_DIR, CLIPS_DIR, ensure_dirs


def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def _flag(key: str, default: str = "on") -> bool:
    return (_setting(key, default) or default).strip().lower() in ("on", "1", "true", "yes")


def match_threshold() -> float:
    """The configured minimum match confidence, as a percentage.

    Higher is stricter. 35 is a sensible starting point: raise it if the wrong
    worker is ever accepted, lower it if genuine workers are turned away.
    """
    try:
        return float(_setting("face_match_threshold", "35"))
    except ValueError:
        return 35.0


def log_transaction(worker_pk: int | None, transaction_type: str, success: bool,
                    score: float | None = None, threshold: float | None = None,
                    error_message: str | None = None) -> None:
    """Every verification attempt is recorded, accepted or not.

    This table is the evidence base for reporting false accepts and rejects.
    """
    try:
        db.session.add(BiometricTransaction(
            worker_id=worker_pk,
            transaction_type=transaction_type,
            modality="face",
            success=success,
            match_score=score,
            threshold_used=threshold,
            error_message=error_message,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


# Machine reasons from face_engine turned into something a worker standing at
# the terminal can act on. The wording matters: "your face did not match" tells
# them to try again, while "the face at the camera belongs to a different
# worker" tells a supervisor that somebody tried to punch for a colleague.
REASON_MESSAGES = {
    face_engine.NO_FACE: "No face was detected. Stand closer to the camera and try again.",
    face_engine.NO_EYES: "Your eyes were not clearly visible. Remove sunglasses or hats and try again.",
    face_engine.TOO_SMALL: "You are too far from the camera. Move closer and try again.",
    face_engine.NOT_ENROLLED: "Your face is not enrolled yet. Ask your supervisor to enrol you on the Biometric page.",
    face_engine.NO_MATCH: "Your face did not match the enrolled record for that Worker ID.",
    face_engine.WRONG_WORKER: "The face at the camera belongs to a different worker. Each worker must clock in personally.",
    "camera_error": "The camera could not be opened. Attendance was not recorded.",
}


def save_snapshot_frame(frame, worker_code: str) -> tuple[str | None, str]:
    """Write one clean frame (no overlays) to captures/. Returns (relative_path, status)."""
    if frame is None:
        return None, "camera_error"
    ensure_dirs()
    filename = f"{worker_code}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jpg"
    try:
        cv2.imwrite(os.path.join(CAPTURES_DIR, filename), frame)
    except Exception:
        return None, "camera_error"
    return os.path.join("captures", filename), "ok"


def record_punch(app, worker: Worker, log_type: str, lat: float | None, lon: float | None,
                 frames: list | None = None) -> dict:
    """Verify and record one attendance event.

    Returns {ok, code, message, category, attendance_id, score, geofence, ...}.
    Callers handle flashing, auditing and HTTP shape.
    """
    # Anything that is not an explicit "OUT" is treated as a clock-in, so a
    # malformed request can never silently close somebody's session.
    log_type = "OUT" if str(log_type).upper() == "OUT" else "IN"
    threshold = match_threshold()
    require_face = _flag("face_verification_required", "on")
    require_eyes = _flag("face_require_eyes", "on")

    result = {
        "ok": False, "code": "", "message": "", "category": "danger",
        "attendance_id": None, "score": None, "threshold": threshold,
        "geofence": None, "snapshot": None, "log_type": log_type,
    }

    # ---- Camera --------------------------------------------------------- #
    # One camera open per punch, yielding eight frames used for BOTH the
    # identity check and the snapshot. The first release opened the camera
    # twice - once to verify, once to photograph - and on a machine with a
    # single webcam the second open failed or returned a stale frame, which is
    # what made verification fail intermittently.
    #
    # `frames` is passed in by the tests, which have no camera.
    if frames is None:
        frames, capture_status = cctv_engine.grab_frames(count=8)
        if capture_status != "ok" or not frames:
            cctv_engine.log_health("camera", 0, "offline", device_label="Attendance camera",
                                   error_code="grab_failed",
                                   error_message="No frames available during attendance")
            log_transaction(worker.id, f"face_verify_{log_type.lower()}", False,
                            threshold=threshold, error_message="camera_error")
            result.update({"code": "camera_error", "message": REASON_MESSAGES["camera_error"]})
            return result

    # ---- Identity ------------------------------------------------------- #
    verification = face_engine.verify_worker(worker.id, frames, threshold=threshold,
                                             require_eyes=require_eyes)
    result["score"] = verification["score"]

    if require_face and not verification["matched"]:
        log_transaction(worker.id, f"face_verify_{log_type.lower()}", False,
                        score=verification["score"], threshold=threshold,
                        error_message=verification["reason"])
        result.update({
            "code": verification["reason"],
            "message": REASON_MESSAGES.get(verification["reason"],
                                           "Face verification failed. Please try again."),
        })
        return result

    log_transaction(worker.id, f"face_verify_{log_type.lower()}", bool(verification["matched"]),
                    score=verification["score"], threshold=threshold,
                    error_message=None if verification["matched"] else verification["reason"])

    # ---- Location ------------------------------------------------------- #
    fence = geofence.evaluate(lat, lon)
    result["geofence"] = fence
    if fence["enforce"] and fence["configured"]:
        if not fence["has_position"]:
            result.update({"code": "location_missing",
                           "message": "Location sharing is required to clock in. Enable location and try again."})
            return result
        if not fence["within"]:
            result.update({
                "code": "outside_geofence",
                "message": (f"You are {fence['distance_m']:.0f} m from the farm, outside the "
                            f"{fence['radius_m']:.0f} m clock-in zone."),
            })
            return result

    # ---- Snapshot ------------------------------------------------------- #
    relative_path, snapshot_status = save_snapshot_frame(verification["best_frame"], worker.worker_id)
    if snapshot_status != "ok" or not relative_path:
        result.update({"code": "capture_failed",
                       "message": "Camera capture failed. Attendance was not recorded."})
        return result

    # ---- Attendance row -------------------------------------------------- #
    now = datetime.utcnow()
    if log_type == "OUT":
        row = (Attendance.query
               .filter_by(worker_id=worker.id)
               .filter(Attendance.check_out_time.is_(None))
               .order_by(Attendance.check_in_time.desc())
               .first())
        if not row:
            result.update({"code": "no_open_session",
                           "message": "No open check-in found. Please clock in first."})
            return result
        row.check_out_time = now
        row.check_out_match_score = verification["score"]
        if lat is not None:
            row.latitude = lat
        if lon is not None:
            row.longitude = lon
    else:
        open_row = (Attendance.query
                    .filter_by(worker_id=worker.id)
                    .filter(Attendance.check_out_time.is_(None))
                    .first())
        if open_row:
            result.update({"code": "already_clocked_in", "category": "warning",
                           "message": "You are already clocked in. Clock out before clocking in again."})
            return result

        row = Attendance(
            worker_id=worker.id,
            check_in_time=now,
            latitude=lat,
            longitude=lon,
            verified_by_face=bool(verification["matched"]),
            check_in_match_score=verification["score"],
            within_geofence=fence["within"],
            distance_from_farm_m=fence["distance_m"],
        )
        db.session.add(row)
        db.session.flush()

    primary = cctv_engine.primary_source()
    snapshot = EventSnapshot(
        attendance_id=row.attendance_id,
        camera_id=primary.get("feed_id"),
        snapshot_type="photo_check_in" if log_type == "IN" else "photo_check_out",
        file_path=relative_path,
    )
    db.session.add(snapshot)
    row.verified_by_cctv = True
    db.session.commit()

    # ---- Cloud (or queue for later) -------------------------------------- #
    stored_path, sync_note = sync_engine.upload_or_queue(
        os.path.join(BASE_DIR, relative_path), relative_path,
        snapshot_id=snapshot.snapshot_id, worker_id=worker.id,
    )
    if stored_path != relative_path:
        snapshot.cloud_url = stored_path
        db.session.commit()

    # ---- Event clip ------------------------------------------------------ #
    if _flag("clip_recording_enabled", "on"):
        try:
            cctv_engine.record_clip(
                app, primary["source"], CLIPS_DIR,
                seconds=float(_setting("clip_seconds", "6") or 6),
                camera_id=primary.get("feed_id"),
                attendance_id=row.attendance_id,
                trigger_type=f"attendance_{log_type.lower()}",
            )
        except Exception:
            pass

    # ---- Daily summary --------------------------------------------------- #
    try:
        payroll_engine.rebuild_day(worker.id, row.check_in_time.date())
    except Exception:
        db.session.rollback()

    result.update({
        "ok": True,
        "code": "recorded",
        "category": "success",
        "attendance_id": row.attendance_id,
        "snapshot": relative_path,
        "sync_note": sync_note,
        "message": (f"Welcome, {worker.name}! Clock-{log_type} recorded at "
                    f"{now.strftime('%H:%M:%S')} (face match {verification['score']:.0f}%)."),
    })
    return result
