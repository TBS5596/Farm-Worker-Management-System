"""Letting a worker who has forgotten their PIN prove who they are and set a new one.

A forgotten PIN is the commonest way a worker is turned away at the gate, and
until now the only remedy was to find somebody with a dashboard login. The
system already holds a stronger proof of identity than the PIN - the worker's
enrolled face - so it can settle the question at the terminal.

THE RULE THIS MODULE IS BUILT AROUND
------------------------------------
A reset must never be an easier door than the clock-in it protects.

Face alone would be a weaker door, and measurably so: the system has no
liveness detection (a declared limitation), so a photograph of a worker can
sometimes pass the face check. Where a farm requires card + PIN + face to
clock in, letting a photograph alone reset the PIN would hand an attacker the
account with one of the three factors.

So the reset requires **every factor the farm's own clock-in mode requires,
except the PIN** - which is the thing being replaced. Card + PIN + face at the
gate means card + face to reset: the attacker still needs the physical card
*and* the face, which is exactly what they needed before.

It follows that a farm whose clock-in does not use the face check has no
self-service reset at all, because it has nothing to prove identity with. That
is not a gap to fill later; it is the same rule applied honestly, and such a
farm is told to see a supervisor.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta

import attendance_service
import barcode_engine
import face_engine
from database import db
from models import Setting, Worker

#: Farms that want resets to stay with a supervisor turn this off.
SETTING = "pin_reset_enabled"
DEFAULT = "on"

#: A reset is rate-limited harder than a sign-in: it changes a credential
#: rather than merely using one, and nobody forgets their PIN three times in
#: a quarter of an hour.
MAX_ATTEMPTS = 3
ATTEMPT_WINDOW = timedelta(minutes=15)

#: How long a passed face check stays good for while the worker types a new
#: PIN. Long enough to type one on a terminal in the sun, short enough that an
#: unattended screen is not an open door.
GRANT_SECONDS = 180

MIN_PIN_LENGTH = 4

_LOCK = threading.Lock()
_ATTEMPTS: dict[str, list[datetime]] = {}

# Reasons, in the project's convention: distinct causes get distinct names, so
# the person at the terminal is told which problem they have rather than that
# "it did not work".
DISABLED = "reset_disabled"
NO_FACE_FACTOR = "no_face_factor"
UNKNOWN = "worker_unknown"
INACTIVE = "worker_inactive"
NOT_ENROLLED = "worker_not_enrolled"
CARD_REQUIRED = "card_required"
CARD_UNKNOWN = "card_unknown"
CARD_MISMATCH = "card_mismatch"
THROTTLED = "too_many_attempts"
CAMERA = "camera_error"

MESSAGES = {
    DISABLED: "PIN resets are done by a supervisor on this farm. Please see your supervisor.",
    NO_FACE_FACTOR: "This farm does not use the face check, so a PIN cannot be reset here. "
                    "Please see your supervisor.",
    UNKNOWN: "That worker number was not recognised.",
    INACTIVE: "That worker is no longer on the register. Please see your supervisor.",
    NOT_ENROLLED: "Your face is not enrolled, so your identity cannot be checked here. "
                  "Please see your supervisor.",
    CARD_REQUIRED: "Scan your card as well, because this farm's clock-in uses it.",
    CARD_UNKNOWN: "That card was not recognised.",
    CARD_MISMATCH: "That card belongs to a different worker.",
    THROTTLED: "Too many attempts. Wait 15 minutes, or ask your supervisor to reset it for you.",
    CAMERA: "The camera is not available, so your identity cannot be checked. "
            "Please see your supervisor.",
}


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

def _setting(key: str, default: str) -> str:
    row = Setting.query.filter_by(key=key).first()
    if row and row.value not in (None, ""):
        return row.value
    return default


def enabled() -> bool:
    return _setting(SETTING, DEFAULT).strip().lower() == "on"


def required_factors() -> dict:
    """What the reset asks for, derived from the farm's clock-in mode.

    Derived rather than configured separately, so the two cannot drift apart.
    A farm that tightens its clock-in tightens its resets in the same move,
    which is the only arrangement where the reset cannot become the weak door.
    """
    mode = attendance_service.CLOCKIN_MODES[attendance_service.clockin_mode()]
    card, _pin, face = mode["factors"]
    return {"card": bool(card), "face": bool(face), "mode": mode}


def available() -> tuple[bool, str]:
    """Can a worker reset their own PIN on this farm at all?"""
    if not enabled():
        return False, DISABLED
    if not required_factors()["face"]:
        return False, NO_FACE_FACTOR
    return True, ""


# --------------------------------------------------------------------------- #
# Throttle
# --------------------------------------------------------------------------- #

def recent_attempts(key: str) -> int:
    with _LOCK:
        cutoff = datetime.utcnow() - ATTEMPT_WINDOW
        kept = [t for t in _ATTEMPTS.get(key, []) if t > cutoff]
        _ATTEMPTS[key] = kept
        return len(kept)


def record_attempt(key: str) -> None:
    with _LOCK:
        _ATTEMPTS.setdefault(key, []).append(datetime.utcnow())


def clear_attempts(key: str) -> None:
    with _LOCK:
        _ATTEMPTS.pop(key, None)


# --------------------------------------------------------------------------- #
# The reset itself
# --------------------------------------------------------------------------- #

def resolve(worker_code: str, card_value: str) -> tuple[Worker | None, str]:
    """Find the worker, enforcing whatever the farm's clock-in mode requires."""
    needs = required_factors()
    code = (worker_code or "").strip().upper()
    card = barcode_engine.normalize_scan(card_value or "")

    worker = None
    if card:
        worker, reason = barcode_engine.resolve(card)
        if worker is None:
            return None, CARD_UNKNOWN if reason != "worker_inactive" else INACTIVE
        if code and (worker.worker_id or "").upper() != code:
            return None, CARD_MISMATCH
    elif needs["card"]:
        # The gate asks for the card, so the reset does too - otherwise the
        # reset is a door that skips a factor the clock-in insists on.
        return None, CARD_REQUIRED
    else:
        if not code:
            return None, UNKNOWN
        worker = Worker.query.filter(
            db.func.upper(Worker.worker_id) == code).first()
        if worker is None:
            return None, UNKNOWN

    if (worker.status or "").lower() != "active":
        return None, INACTIVE
    if face_engine.sample_count_for(worker.id) <= 0:
        return None, NOT_ENROLLED
    return worker, ""


def verify_face(worker: Worker, frames, threshold: float, require_eyes: bool) -> dict:
    """The same check the gate makes, against the same enrolled templates."""
    return face_engine.verify_worker(worker.id, frames, threshold=threshold,
                                     require_eyes=require_eyes)


def pin_fingerprint(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def pin_problem(worker: Worker, new_pin: str, confirm: str) -> str:
    """Why this PIN cannot be used, or an empty string if it can."""
    new_pin = (new_pin or "").strip()
    if len(new_pin) < MIN_PIN_LENGTH:
        return f"Your new PIN must be at least {MIN_PIN_LENGTH} digits."
    if not new_pin.isdigit():
        return "Your PIN must be digits only."
    if new_pin != (confirm or "").strip():
        return "The two PINs did not match. Type the same one twice."
    taken = (Worker.query
             .filter(Worker.pin_fingerprint == pin_fingerprint(new_pin))
             .filter(Worker.id != worker.id)
             .first())
    if taken is not None:
        # Said without naming who holds it: that would leak another worker's
        # PIN to whoever guessed it.
        return "That PIN is already in use. Please choose a different one."
    return ""


def apply(worker: Worker, new_pin: str) -> None:
    worker.set_pin(new_pin)
    worker.pin_fingerprint = pin_fingerprint(new_pin)
    db.session.commit()
