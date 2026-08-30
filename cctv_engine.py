"""Camera, streaming, clip recording and hardware health.

Two things changed here versus the first release:

1. A camera registered on the CCTV page is now actually watchable. Previously
   `cctv_feeds.rtsp_url` was stored and ignored, and streams came only from the
   `camera_sources` setting. Feeds and streams are now one list.
2. Attendance events record a short video clip, so "access recorded footage"
   is backed by real files in `cctv_recordings` instead of a marker row.
"""

from __future__ import annotations

import os
import sys
import json
import time
import threading
from datetime import datetime

import cv2
import numpy as np

from database import db
from models import CCTVFeed, CCTVRecording, HardwareHealthLog, Setting

BUILTIN_PREFIX = "builtin://"


# ---------------------------------------------------------------------------
# Settings access (kept local so this module has no app.py import cycle)
# ---------------------------------------------------------------------------

def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def coerce_source(source_value):
    """Turn a stored source string into what cv2.VideoCapture expects.

        "0"                          -> 0      (USB device index, an int)
        "builtin://0"                -> 0      (this machine's own camera)
        "rtsp://10.0.0.5:554/stream" -> unchanged string (network camera)

    The int/string distinction matters: OpenCV treats an integer as a local
    device and a string as a URL or file.
    """
    if isinstance(source_value, int):
        return source_value
    text = str(source_value or "").strip()
    if text.startswith(BUILTIN_PREFIX):
        text = text[len(BUILTIN_PREFIX):].strip()
    if text.isdigit():
        return int(text)
    return text


# ---------------------------------------------------------------------------
# Source resolution
# ---------------------------------------------------------------------------

def get_camera_sources() -> list[dict]:
    """Every watchable camera, attendance camera first.

    Order matters: index 0 is what /camera-stream/0 serves AND what attendance
    verification uses, so the primary feed must come first.

    Sources are merged from two places - registered CCTV feed rows (the normal
    way) and the `camera_sources` JSON setting (for anything not worth
    registering) - and de-duplicated, since the same webcam is often both.

    Always returns at least one entry, falling back to the built-in camera
    index, so the UI never shows an empty camera list.
    """
    sources: list[dict] = []
    seen: set[str] = set()

    for feed in CCTVFeed.query.order_by(CCTVFeed.is_primary.desc(), CCTVFeed.feed_id.asc()).all():
        if (feed.status or "").lower() in ("inactive", "disabled"):
            continue
        raw = (feed.rtsp_url or "").strip()
        if not raw:
            continue
        source = coerce_source(raw)
        key = str(source)
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "name": feed.camera_name or f"Camera {feed.feed_id}",
            "type": "builtin" if raw.startswith(BUILTIN_PREFIX) else (
                "rtsp" if str(raw).lower().startswith(("rtsp://", "http://", "https://")) else "usb"
            ),
            "source": source,
            "feed_id": feed.feed_id,
            "location": feed.camera_location or "",
        })

    configured = _setting("camera_sources", "").strip()
    if configured:
        try:
            parsed = json.loads(configured)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            for idx, item in enumerate(parsed):
                if not isinstance(item, dict):
                    continue
                raw = item.get("source")
                if raw is None or str(raw).strip() == "":
                    continue
                source = coerce_source(raw)
                key = str(source)
                if key in seen:
                    continue
                seen.add(key)
                sources.append({
                    "name": str(item.get("name", f"Camera {idx + 1}")).strip() or f"Camera {idx + 1}",
                    "type": str(item.get("type", "usb")).strip().lower() or "usb",
                    "source": source,
                    "feed_id": None,
                    "location": str(item.get("location", "")).strip(),
                })

    if not sources:
        sources.append({
            "name": "Built-in Camera",
            "type": "builtin",
            "source": coerce_source(_setting("camera_index", "0")),
            "feed_id": None,
            "location": "Local Device",
        })

    return sources


def primary_source() -> dict:
    return get_camera_sources()[0]


def fallback_source():
    return coerce_source(_setting("camera_index", "0"))


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def open_camera(source):
    """Open a VideoCapture using the best backend for the current platform."""
    if sys.platform.startswith("linux") and isinstance(source, int):
        # Avoid the noisy FFMPEG fallback on hosts with no /dev/video*.
        if not os.path.exists(f"/dev/video{source}"):
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
        cap.release()
        cap = cv2.VideoCapture(source)
    return cap


def open_best_camera(source=None):
    """Open the given source, falling back to the configured built-in index.

    Returns (capture, opened_source) - capture may be closed if nothing worked.
    """
    target = primary_source()["source"] if source is None else source
    cap = open_camera(target)
    if cap.isOpened():
        return cap, target

    cap.release()
    alternative = fallback_source()
    if str(alternative) != str(target):
        cap = open_camera(alternative)
        if cap.isOpened():
            return cap, alternative
    return cap, target


def grab_frames(count: int = 6, source=None, warmup: int = 3, delay: float = 0.06):
    """Open the camera once and return several frames.

    `warmup` discards the first few frames: a webcam's first exposures are
    usually dark or badly white-balanced, and a face is much harder to detect
    in them. `delay` spaces the kept frames slightly apart so they are not
    three copies of the same blink.

    Returns (frames, status) where status is "ok" or "camera_error".

    This replaces opening the camera twice per punch - once to verify, once to
    photograph - which fought over a single webcam and caused intermittent
    verification failures.
    """
    cap, used_source = open_best_camera(source)
    if not cap.isOpened():
        cap.release()
        return [], "camera_error"

    try:
        for _ in range(max(0, warmup)):
            cap.read()
        frames = []
        for _ in range(max(1, count)):
            ok, frame = cap.read()
            if ok and frame is not None:
                frames.append(frame)
            if delay:
                time.sleep(delay)
        if not frames:
            return [], "camera_error"
        return frames, "ok"
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Overlays for the live view
# ---------------------------------------------------------------------------

def detect_faces_and_eyes(frame) -> list[dict]:
    from face_engine import detect_faces, detect_eyes

    if frame is None:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    detections = []
    for (x, y, w, h) in detect_faces(frame):
        detections.append({"face": (x, y, w, h), "eyes": detect_eyes(gray[y:y + h, x:x + w])})
    return detections


def draw_detections(frame, detections: list[dict]) -> None:
    for item in detections:
        x, y, w, h = item["face"]
        cv2.rectangle(frame, (x, y), (x + w, y + h), (40, 220, 40), 2)
        cv2.putText(frame, "Face", (x, max(20, y - 8)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.55, (40, 220, 40), 2, cv2.LINE_AA)
        for (ex, ey, ew, eh) in item["eyes"]:
            cv2.rectangle(frame, (x + ex, y + ey), (x + ex + ew, y + ey + eh), (255, 160, 20), 2)


def detect_motion_regions(prev_gray, frame) -> tuple:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)
    if prev_gray is None:
        return [], gray

    delta = cv2.absdiff(prev_gray, gray)
    thresh = cv2.threshold(delta, 25, 255, cv2.THRESH_BINARY)[1]
    thresh = cv2.dilate(thresh, None, iterations=2)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    boxes = []
    for contour in contours:
        if cv2.contourArea(contour) < 1800:
            continue
        boxes.append(tuple(int(v) for v in cv2.boundingRect(contour)))
    return boxes, gray


def draw_motion_regions(frame, boxes: list[tuple]) -> None:
    for (x, y, w, h) in boxes:
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 185, 255), 2)
        cv2.putText(frame, "Motion", (x, max(20, y - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 185, 255), 2, cv2.LINE_AA)


def build_unavailable_frame(message: str):
    frame = np.zeros((420, 760, 3), dtype=np.uint8)
    frame[:, :] = (22, 28, 36)
    cv2.putText(frame, "Camera Stream Unavailable", (36, 120), cv2.FONT_HERSHEY_SIMPLEX,
                0.95, (245, 245, 245), 2, cv2.LINE_AA)
    cv2.putText(frame, message, (36, 170), cv2.FONT_HERSHEY_SIMPLEX,
                0.62, (180, 210, 255), 2, cv2.LINE_AA)
    cv2.putText(frame, "Tip: attach a webcam or set a valid RTSP/USB source on the CCTV page.",
                (36, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)
    return frame


def frame_generator(source, fallback, overlay_faces: bool = False, overlay_motion: bool = False):
    """Yield MJPEG parts. Must not touch the database - it runs outside a request."""
    cap = open_camera(source)
    if not cap.isOpened():
        cap.release()
        cap = open_camera(fallback)
        if not cap.isOpened():
            cap.release()
            while True:
                frame = build_unavailable_frame("No camera device detected on this host")
                ok, buffer = cv2.imencode(".jpg", frame)
                if ok:
                    yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
                time.sleep(1.0)

    for _ in range(3):
        cap.read()

    prev_gray = None
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if overlay_motion:
                boxes, prev_gray = detect_motion_regions(prev_gray, frame)
                draw_motion_regions(frame, boxes)
            if overlay_faces:
                draw_detections(frame, detect_faces_and_eyes(frame))

            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
            time.sleep(0.04)
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Clip recording
# ---------------------------------------------------------------------------

def record_clip(app, source, clips_dir: str, seconds: float = 8.0, fps: float = 12.0,
                camera_id: int | None = None, attendance_id: int | None = None,
                trigger_type: str = "attendance") -> None:
    """Record a short clip in a background thread and register it.

    Deliberately short: continuous recording would fill a Raspberry Pi's SD card
    in hours, while an event clip is what a supervisor actually needs to review.

    Runs in a daemon thread so the worker is not left standing at the terminal
    while six seconds of video is written. That thread needs `app` because it
    outlives the request and has to push its own application context to write
    the cctv_recordings row.

    Files land in captures/clips/ named by time and trigger, e.g.
    clip_20260828_071205_attendance_in.mp4
    """
    def _worker():
        cap = open_camera(source)
        if not cap.isOpened():
            cap.release()
            with app.app_context():
                log_health("camera", camera_id or 0, "offline",
                           error_code="clip_open_failed",
                           error_message=f"Could not open {source} for clip recording")
            return

        started = datetime.utcnow()
        filename = f"clip_{started.strftime('%Y%m%d_%H%M%S')}_{trigger_type}.mp4"
        path = os.path.join(clips_dir, filename)
        writer = None
        try:
            os.makedirs(clips_dir, exist_ok=True)
            ok, frame = cap.read()
            if not ok or frame is None:
                return
            height, width = frame.shape[:2]
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
            if not writer.isOpened():
                return

            deadline = time.time() + max(1.0, seconds)
            frame_interval = 1.0 / max(1.0, fps)
            writer.write(frame)
            while time.time() < deadline:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                writer.write(frame)
                time.sleep(frame_interval)
        except Exception:
            return
        finally:
            if writer is not None:
                writer.release()
            cap.release()

        ended = datetime.utcnow()
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0

        with app.app_context():
            db.session.add(CCTVRecording(
                camera_id=camera_id,
                attendance_id=attendance_id,
                trigger_type=trigger_type,
                recording_path=os.path.join("captures", "clips", filename),
                start_time=started,
                end_time=ended,
                duration_seconds=(ended - started).total_seconds(),
                file_size_bytes=size,
                storage_location="local",
                uploaded_to_cloud=False,
            ))
            db.session.commit()

    threading.Thread(target=_worker, daemon=True, name="fms-clip-recorder").start()


# ---------------------------------------------------------------------------
# Hardware health
# ---------------------------------------------------------------------------

def log_health(device_type: str, device_id: int, status: str, device_label: str | None = None,
               error_code: str | None = None, error_message: str | None = None,
               response_time_ms: int | None = None) -> None:
    try:
        db.session.add(HardwareHealthLog(
            device_type=device_type,
            device_id=int(device_id or 0),
            device_label=device_label,
            status=status,
            error_code=error_code,
            error_message=error_message,
            response_time_ms=response_time_ms,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def probe_feed(feed: CCTVFeed) -> dict:
    """Try to open a feed, update its heartbeat and log the result."""
    source = coerce_source(feed.rtsp_url or "")
    started = time.time()
    cap = open_camera(source)
    opened = cap.isOpened()
    read_ok = False
    if opened:
        read_ok, _frame = cap.read()
    cap.release()
    elapsed_ms = int((time.time() - started) * 1000)

    status = "online" if (opened and read_ok) else "offline"
    feed.status = status
    feed.last_heartbeat = datetime.utcnow() if status == "online" else feed.last_heartbeat
    db.session.commit()

    log_health(
        "camera", feed.feed_id, status,
        device_label=feed.camera_name,
        error_code=None if status == "online" else "open_failed",
        error_message=None if status == "online" else f"Could not read frames from {feed.rtsp_url}",
        response_time_ms=elapsed_ms,
    )
    return {"feed_id": feed.feed_id, "camera_name": feed.camera_name,
            "status": status, "response_time_ms": elapsed_ms}
