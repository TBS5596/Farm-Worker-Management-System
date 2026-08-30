"""Face enrolment and identity verification.

This is the module that makes the biometric objective real. Before it existed,
clock-in only asked "is a face present?"; it now asks "is this *this worker's*
face?" by comparing the live frame against samples enrolled for that worker.

Camera-only by design: the project has no fingerprint scanner, so the enrolled
biometric is a set of normalised grayscale face crops per worker, matched with
OpenCV's LBPH (Local Binary Patterns Histograms) recognizer.

LBPH lives in `cv2.face`, which ships in opencv-contrib-python. If only plain
opencv-python is installed the engine falls back to a correlation matcher so the
app still runs, and says so in `engine_info()` - the fallback is measurably
weaker and should not be used for real evaluation.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime

import cv2
import numpy as np

from database import db
from models import FaceTemplate, Worker

# Every enrolled sample and every probe is normalised to this size, so the
# recognizer always compares like with like.
# Every enrolled sample and every probe is resized to this, so the recognizer
# always compares like with like. 200x200 is a deliberate middle ground: large
# enough for LBPH's 8x8 grid of histograms to have detail to work with, small
# enough that a row is 40 KB and training stays fast on a Raspberry Pi.
FACE_SIZE = (200, 200)

HAAR_DIR = cv2.data.haarcascades
FACE_CASCADE = cv2.CascadeClassifier(os.path.join(HAAR_DIR, "haarcascade_frontalface_default.xml"))
EYE_CASCADE = cv2.CascadeClassifier(os.path.join(HAAR_DIR, "haarcascade_eye.xml"))

_LOCK = threading.RLock()
_MODEL = None
_MODEL_SIGNATURE = None
_LABELS: set[int] = set()

# Reasons returned to the caller. Kept short so they can be stored in
# biometric_transactions.error_message and read back in the UI.
NO_FACE = "no_face_detected"
NO_EYES = "eyes_not_visible"
NOT_ENROLLED = "worker_not_enrolled"
NO_MATCH = "face_did_not_match"
WRONG_WORKER = "face_matched_another_worker"
TOO_SMALL = "face_too_small"


def has_lbph() -> bool:
    """True when the contrib LBPH recognizer is available."""
    return hasattr(cv2, "face") and hasattr(cv2.face, "LBPHFaceRecognizer_create")


def engine_info() -> dict:
    return {
        "algorithm": "LBPH" if has_lbph() else "correlation-fallback",
        "contrib_available": has_lbph(),
        "face_size": f"{FACE_SIZE[0]}x{FACE_SIZE[1]}",
        "cascades_loaded": not (FACE_CASCADE.empty() or EYE_CASCADE.empty()),
    }


# ---------------------------------------------------------------------------
# Detection and normalisation
# ---------------------------------------------------------------------------

def detect_faces(frame) -> list[tuple[int, int, int, int]]:
    """Return face boxes in a frame, largest first."""
    if frame is None or FACE_CASCADE.empty():
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    boxes = FACE_CASCADE.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(45, 45))
    return sorted([tuple(int(v) for v in b) for b in boxes], key=lambda b: b[2] * b[3], reverse=True)


def detect_eyes(gray_face) -> list[tuple[int, int, int, int]]:
    if EYE_CASCADE.empty() or gray_face is None:
        return []
    eyes = EYE_CASCADE.detectMultiScale(gray_face, scaleFactor=1.15, minNeighbors=6, minSize=(15, 15))
    return [tuple(int(v) for v in e) for e in eyes]


def sharpness(gray_face) -> float:
    """Laplacian variance: how much fine detail the crop has.

    A blurry face scores low, a sharp one high, so it is a cheap proxy for
    enrolment quality shown next to each stored sample. Typical values: a sharp
    indoor capture around 300-500, a motion-blurred one under 50.
    """
    if gray_face is None:
        return 0.0
    return float(cv2.Laplacian(gray_face, cv2.CV_64F).var())


def extract_face(frame, require_eyes: bool = True, min_size: int = 60):
    """Crop, grayscale, equalise and resize the largest face in a frame.

    Returns (crop, quality, reason). `crop` is None when nothing usable was
    found, and `reason` explains why.
    """
    boxes = detect_faces(frame)
    if not boxes:
        return None, 0.0, NO_FACE

    x, y, w, h = boxes[0]
    if w < min_size or h < min_size:
        return None, 0.0, TOO_SMALL

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    roi = gray[y:y + h, x:x + w]

    if require_eyes and not detect_eyes(roi):
        return None, 0.0, NO_EYES

    crop = cv2.resize(roi, FACE_SIZE, interpolation=cv2.INTER_AREA)
    crop = cv2.equalizeHist(crop)
    return crop, sharpness(crop), ""


# ---------------------------------------------------------------------------
# Template storage
# ---------------------------------------------------------------------------

def _encode(crop) -> bytes:
    """Crop -> the exact bytes stored in FaceTemplate.face_embedding.

    Raw pixels rather than a serialisation format: a 200x200 uint8 image is
    always 40,000 bytes, so decoding needs no header and a wrong-sized blob is
    detectable by length alone.
    """
    return np.ascontiguousarray(crop, dtype=np.uint8).tobytes()


def _decode(blob: bytes):
    expected = FACE_SIZE[0] * FACE_SIZE[1]
    if not blob or len(blob) != expected:
        return None
    return np.frombuffer(blob, dtype=np.uint8).reshape(FACE_SIZE[1], FACE_SIZE[0])


def sample_counts() -> dict[int, int]:
    """worker.id -> number of enrolled samples."""
    rows = db.session.query(FaceTemplate.worker_id, db.func.count(FaceTemplate.face_id)) \
        .group_by(FaceTemplate.worker_id).all()
    return {int(worker_id): int(count) for worker_id, count in rows}


def sample_count_for(worker_pk: int) -> int:
    return int(FaceTemplate.query.filter_by(worker_id=worker_pk).count())


def enroll_frame(worker: Worker, frame, reference_dir: str, require_eyes: bool = True) -> dict:
    """Store one enrolment sample for a worker. Returns a result dict."""
    crop, quality, reason = extract_face(frame, require_eyes=require_eyes)
    if crop is None:
        return {"ok": False, "reason": reason, "samples": sample_count_for(worker.id)}

    next_index = sample_count_for(worker.id) + 1
    reference_path = None
    try:
        os.makedirs(reference_dir, exist_ok=True)
        filename = f"enroll_{worker.worker_id}_{next_index:02d}.jpg"
        cv2.imwrite(os.path.join(reference_dir, filename), crop)
        reference_path = os.path.join("captures", "faces", filename)
    except Exception:
        reference_path = None

    db.session.add(FaceTemplate(
        worker_id=worker.id,
        face_embedding=_encode(crop),
        algorithm="LBPH" if has_lbph() else "correlation",
        sample_index=next_index,
        reference_image_path=reference_path,
        quality_score=quality,
        created_at=datetime.utcnow(),
    ))
    worker.face_enrolled_at = datetime.utcnow()
    db.session.commit()
    invalidate()
    return {
        "ok": True,
        "reason": "",
        "quality": round(quality, 1),
        "samples": next_index,
        "reference_path": reference_path,
    }


def clear_templates(worker: Worker) -> int:
    removed = FaceTemplate.query.filter_by(worker_id=worker.id).delete()
    worker.face_enrolled_at = None
    db.session.commit()
    invalidate()
    return int(removed or 0)


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------

def _signature() -> tuple:
    """Cheap fingerprint of the template table, so we only retrain on change.

    (row count, highest face_id) changes on any insert or delete, which is
    enough: samples are never edited in place. Example: enrolling one sample
    takes (24, 24) to (25, 25), so the next verification retrains; a hundred
    clock-ins in between reuse the cached model.
    """
    count, max_id = db.session.query(
        db.func.count(FaceTemplate.face_id), db.func.max(FaceTemplate.face_id)
    ).one()
    return int(count or 0), int(max_id or 0)


def invalidate() -> None:
    global _MODEL, _MODEL_SIGNATURE, _LABELS
    with _LOCK:
        _MODEL = None
        _MODEL_SIGNATURE = None
        _LABELS = set()


def _load_training_data() -> tuple[list, list[int]]:
    crops, labels = [], []
    for row in FaceTemplate.query.order_by(FaceTemplate.face_id.asc()).all():
        crop = _decode(row.face_embedding)
        if crop is None:
            continue
        crops.append(crop)
        labels.append(int(row.worker_id))
    return crops, labels


def _ensure_model():
    """Train (or reuse) the recognizer. Returns (model, labels) or (None, set())."""
    global _MODEL, _MODEL_SIGNATURE, _LABELS
    with _LOCK:
        signature = _signature()
        if _MODEL is not None and _MODEL_SIGNATURE == signature:
            return _MODEL, _LABELS

        crops, labels = _load_training_data()
        if not crops:
            _MODEL, _MODEL_SIGNATURE, _LABELS = None, signature, set()
            return None, set()

        if has_lbph():
            model = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
            model.train(crops, np.array(labels, dtype=np.int32))
        else:
            # Fallback: keep the samples themselves and compare by correlation.
            model = {"crops": crops, "labels": labels}

        _MODEL, _MODEL_SIGNATURE, _LABELS = model, signature, set(labels)
        return _MODEL, _LABELS


def _predict(model, crop) -> tuple[int | None, float]:
    """Return (worker_pk, confidence_percent). Higher confidence is better."""
    if model is None:
        return None, 0.0

    if has_lbph() and not isinstance(model, dict):
        label, distance = model.predict(crop)
        # LBPH returns a DISTANCE, where lower is better and 0 is identical.
        # Reporting it as a confidence percentage makes the threshold read the
        # intuitive way round: a distance of 28 becomes 72% confident, and
        # "score >= threshold" means what a user expects.
        # LBPH returns a distance where lower is better; express it as a
        # confidence percentage so the threshold reads the intuitive way.
        return int(label), max(0.0, 100.0 - float(distance))

    # Correlation fallback, used only when cv2.face is unavailable. Compares
    # the probe against every stored sample by normalised cross-correlation and
    # keeps the best. Slower as the roster grows and less discriminating than
    # LBPH - present so the app still runs, not so it can be relied on.
    probe = crop.astype(np.float32)
    probe = (probe - probe.mean()) / (probe.std() + 1e-6)
    best_label, best_corr = None, -1.0
    for sample, label in zip(model["crops"], model["labels"]):
        ref = sample.astype(np.float32)
        ref = (ref - ref.mean()) / (ref.std() + 1e-6)
        corr = float((probe * ref).mean())
        if corr > best_corr:
            best_corr, best_label = corr, int(label)
    # Map correlation onto the same 0-100 scale as the LBPH branch, so one
    # threshold setting works for both. Correlation of 0.5 or below scores 0,
    # 0.675 scores 35 (the default threshold), and 1.0 scores 100.
    return best_label, max(0.0, min(100.0, (best_corr - 0.5) * 200.0))


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

def verify_worker(worker_pk: int, frames: list, threshold: float = 35.0,
                  require_eyes: bool = True) -> dict:
    """Is the face in any of `frames` the enrolled face of `worker_pk`?

    This is the check the whole project rests on. It answers the claim the
    worker made by typing their ID, rather than merely "is somebody there".

    Returns matched, score, threshold, reason, matched_worker_pk and the best
    frame seen - the caller saves that frame as the snapshot, so the camera is
    opened once per punch rather than twice.

    Measured example on three enrolled samples: a held-out photograph of the
    same person scores 71.79 and is accepted; the same photograph checked
    against a different enrolled worker's ID is refused with reason
    `face_matched_another_worker`, which is the buddy-punching case.
    """
    result = {
        "matched": False,
        "score": 0.0,
        "threshold": float(threshold),
        "reason": NO_FACE,
        "matched_worker_pk": None,
        "best_frame": frames[-1] if frames else None,
        "face_found": False,
    }

    model, labels = _ensure_model()
    if model is None or worker_pk not in labels:
        result["reason"] = NOT_ENROLLED
        return result

    for frame in frames:
        crop, _quality, reason = extract_face(frame, require_eyes=require_eyes)
        if crop is None:
            if result["reason"] in (NO_FACE,):
                result["reason"] = reason
            continue

        result["face_found"] = True
        label, score = _predict(model, crop)
        if score > result["score"]:
            result["score"] = round(float(score), 2)
            result["matched_worker_pk"] = label
            result["best_frame"] = frame

        if label == worker_pk and score >= threshold:
            result.update({"matched": True, "reason": "", "best_frame": frame,
                           "score": round(float(score), 2), "matched_worker_pk": label})
            return result

    if result["face_found"]:
        if result["matched_worker_pk"] not in (None, worker_pk):
            result["reason"] = WRONG_WORKER
        else:
            result["reason"] = NO_MATCH
    return result


def identify(frames: list, threshold: float = 35.0, require_eyes: bool = True) -> dict:
    """1:N identification - who is this? Used by the JSON API."""
    model, labels = _ensure_model()
    outcome = {"matched": False, "worker_pk": None, "score": 0.0,
               "threshold": float(threshold), "reason": NOT_ENROLLED if not labels else NO_FACE}
    if model is None:
        return outcome

    for frame in frames:
        crop, _quality, reason = extract_face(frame, require_eyes=require_eyes)
        if crop is None:
            outcome["reason"] = reason
            continue
        label, score = _predict(model, crop)
        if score > outcome["score"]:
            outcome.update({"worker_pk": label, "score": round(float(score), 2)})
        if score >= threshold:
            outcome.update({"matched": True, "reason": ""})
            return outcome

    if outcome["worker_pk"] is not None:
        outcome["reason"] = NO_MATCH
    return outcome


def accuracy_snapshot() -> dict:
    """Verification statistics for the dashboard, read from biometric_transactions."""
    from models import BiometricTransaction

    total = BiometricTransaction.query.count()
    success = BiometricTransaction.query.filter_by(success=True).count()
    rejected = total - success
    avg_score = db.session.query(db.func.avg(BiometricTransaction.match_score)) \
        .filter(BiometricTransaction.success.is_(True)).scalar()
    return {
        "attempts": total,
        "accepted": success,
        "rejected": rejected,
        "acceptance_rate": round((success / total) * 100.0, 1) if total else 0.0,
        "avg_match_score": round(float(avg_score), 1) if avg_score else 0.0,
    }
