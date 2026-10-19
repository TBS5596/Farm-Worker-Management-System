"""Resetting a forgotten PIN at the terminal.

A forgotten PIN is the commonest reason a worker is turned away at the gate,
and the remedy used to be "find somebody with a dashboard login". Letting the
terminal settle it is a convenience; letting the WRONG person settle it would
be a credential handed out to anyone who can read a worker number off a card.

So the thing these tests are really guarding is one sentence from the module:
a reset must never be an easier door than the clock-in it protects. Nearly
every test below is a way the reset should refuse, and each refusal is checked
for its own reason rather than a generic failure, because the worker standing
at the terminal needs to be told which problem is theirs.
"""

import numpy as np
import pytest

import app as app_module
import attendance_service
import barcode_engine
import cctv_engine
import face_engine
import pin_reset
from database import db
from models import AuditLog, FaceTemplate, Worker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_face(seed: int):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 60, size=face_engine.FACE_SIZE, dtype=np.uint8)
    gradient = np.linspace(40 + seed * 20, 200 - seed * 10,
                           face_engine.FACE_SIZE[0], dtype=np.uint8)
    return np.clip(base + gradient[None, :], 0, 255).astype(np.uint8)


def _enrol(worker, count=2, seed=7):
    for index in range(1, count + 1):
        db.session.add(FaceTemplate(
            worker_id=worker.id,
            face_embedding=face_engine._encode(_synthetic_face(seed)),
            algorithm="LBPH",
            sample_index=index,
            quality_score=100.0,
        ))
    db.session.commit()
    face_engine.invalidate()


@pytest.fixture(autouse=True)
def _clean_throttle():
    """The throttle is process memory, so it would leak between tests."""
    pin_reset._ATTEMPTS.clear()
    yield
    pin_reset._ATTEMPTS.clear()


@pytest.fixture()
def camera(monkeypatch):
    """Pretend the gate camera is present and returning frames."""
    frames = [np.zeros((240, 320, 3), dtype=np.uint8)] * 4
    monkeypatch.setattr(cctv_engine, "grab_frames",
                        lambda count=8, **kw: (frames, "ok"))
    return frames


@pytest.fixture()
def face(monkeypatch):
    """Decide what the face check says, without needing a real face."""
    def _set(matched=True, score=88.0, reason=""):
        monkeypatch.setattr(pin_reset, "verify_face",
                            lambda *a, **kw: {"matched": matched, "score": score,
                                              "reason": reason or face_engine.NO_MATCH,
                                              "best_frame": None})
    return _set


@pytest.fixture()
def pin_face_mode(setting):
    """PIN + face: a worker number and a face, no card. The common farm."""
    for key, value in attendance_service.settings_for_mode("pin_face").items():
        setting(key, value)
    setting("pin_reset_enabled", "on")


def _audit_actions():
    return [row.action for row in AuditLog.query.all()]


# ---------------------------------------------------------------------------
# Whether the reset is offered at all
# ---------------------------------------------------------------------------

def test_reset_is_available_when_the_farm_checks_faces(pin_face_mode):
    ok, why = pin_reset.available()

    assert ok is True
    assert why == ""


def test_reset_is_withdrawn_when_the_farm_switches_it_off(pin_face_mode, setting):
    setting("pin_reset_enabled", "off")

    ok, why = pin_reset.available()

    assert ok is False
    assert why == pin_reset.DISABLED


def test_reset_is_impossible_without_a_face_check(setting):
    """The rule, applied honestly rather than fudged.

    Card + PIN has nothing that proves who is standing there, so there is
    nothing to reset a PIN against. Offering a reset anyway would mean a new
    PIN for anyone holding the card - which is precisely the attack the PIN
    exists to stop.
    """
    for key, value in attendance_service.settings_for_mode("card_pin").items():
        setting(key, value)
    setting("pin_reset_enabled", "on")

    ok, why = pin_reset.available()

    assert ok is False
    assert why == pin_reset.NO_FACE_FACTOR


def test_the_page_explains_itself_when_it_cannot_help(client, setting):
    for key, value in attendance_service.settings_for_mode("card_pin").items():
        setting(key, value)

    body = client.get("/pin-reset").get_data(as_text=True)

    assert "supervisor" in body.lower()


def test_the_clockin_page_offers_the_reset(client, pin_face_mode):
    body = client.get("/").get_data(as_text=True)

    assert "/pin-reset" in body


def test_the_admin_pane_points_at_the_help_page(client):
    """Administrators get an explanation, not a self-service reset."""
    body = client.get("/").get_data(as_text=True)

    assert "/account-help" in body


def test_account_help_names_the_two_real_routes(client):
    body = client.get("/account-help").get_data(as_text=True).lower()

    assert "another administrator" in body
    assert "reset_admin.py" in body


# ---------------------------------------------------------------------------
# Finding the worker
# ---------------------------------------------------------------------------

def test_an_unknown_worker_number_is_refused(pin_face_mode):
    worker, reason = pin_reset.resolve("NOBODY", "")

    assert worker is None
    assert reason == pin_reset.UNKNOWN


def test_a_blank_worker_number_is_refused(pin_face_mode):
    worker, reason = pin_reset.resolve("", "")

    assert worker is None
    assert reason == pin_reset.UNKNOWN


def test_a_deactivated_worker_cannot_reset(pin_face_mode, make_worker):
    """Someone off the register must not be able to re-open their own account."""
    left = make_worker(name="Musonda Banda", pin="1234", status="inactive")
    _enrol(left)

    worker, reason = pin_reset.resolve(left.worker_id, "")

    assert worker is None
    assert reason == pin_reset.INACTIVE


def test_a_worker_with_no_enrolled_face_cannot_reset(pin_face_mode, make_worker):
    """No enrolment means no proof, and a reset without proof is a giveaway."""
    worker = make_worker(name="Mwiza Tembo", pin="1234")

    found, reason = pin_reset.resolve(worker.worker_id, "")

    assert found is None
    assert reason == pin_reset.NOT_ENROLLED


def test_an_enrolled_active_worker_is_found(pin_face_mode, make_worker):
    worker = make_worker(name="Kondwani Zulu", pin="1234")
    _enrol(worker)

    found, reason = pin_reset.resolve(worker.worker_id, "")

    assert found is not None
    assert found.id == worker.id
    assert reason == ""


# ---------------------------------------------------------------------------
# The card, where the farm uses one
# ---------------------------------------------------------------------------

def test_a_card_farm_insists_on_the_card(setting, make_worker):
    """The gate asks for the card, so the reset asks for it too.

    Without this the reset would be a door that skips a factor the clock-in
    insists on - exactly the asymmetry the module exists to prevent.
    """
    for key, value in attendance_service.settings_for_mode("card_pin_face").items():
        setting(key, value)
    worker = make_worker(name="Chipo Mwale", pin="1234")
    _enrol(worker)

    found, reason = pin_reset.resolve(worker.worker_id, "")

    assert found is None
    assert reason == pin_reset.CARD_REQUIRED


def test_a_card_nobody_holds_is_refused(setting, make_worker):
    for key, value in attendance_service.settings_for_mode("card_pin_face").items():
        setting(key, value)
    worker = make_worker(name="Lubasi Nyambe", pin="1234")
    _enrol(worker)

    found, reason = pin_reset.resolve("", "FMS-ZZZZ-ZZZZ")

    assert found is None
    assert reason == pin_reset.CARD_UNKNOWN


def test_a_card_belonging_to_somebody_else_is_refused(setting, make_worker):
    """Typed number and scanned card must agree, or neither is believed."""
    for key, value in attendance_service.settings_for_mode("card_pin_face").items():
        setting(key, value)
    mine = make_worker(name="Thandiwe Kunda", pin="1234")
    theirs = make_worker(name="Kabwe Mulenga", pin="5678")
    _enrol(mine)
    _enrol(theirs, seed=11)
    barcode_engine.issue_card(db, theirs, "card_number")
    value = theirs.card_barcode

    found, reason = pin_reset.resolve(mine.worker_id, value)

    assert found is None
    assert reason == pin_reset.CARD_MISMATCH


def test_a_valid_card_identifies_its_holder(setting, make_worker):
    for key, value in attendance_service.settings_for_mode("card_pin_face").items():
        setting(key, value)
    worker = make_worker(name="Bwalya Chanda", pin="1234")
    _enrol(worker)
    barcode_engine.issue_card(db, worker, "card_number")
    value = worker.card_barcode

    found, reason = pin_reset.resolve("", value)

    assert found is not None
    assert found.id == worker.id
    assert reason == ""


# ---------------------------------------------------------------------------
# The face check
# ---------------------------------------------------------------------------

def test_a_wrong_face_does_not_get_a_new_pin(client, pin_face_mode, make_worker,
                                             camera, face):
    worker = make_worker(name="Musonda Banda", pin="1234")
    _enrol(worker)
    face(matched=False, score=11.0)

    response = client.post("/pin-reset", data={"worker_id": worker.worker_id})

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert "pin_reset_worker" not in session
    assert "worker.pin_reset_refused" in _audit_actions()


def test_a_dead_camera_refuses_rather_than_waving_through(client, pin_face_mode,
                                                          make_worker, monkeypatch):
    """The failure mode that matters: no camera must mean no reset.

    A check that silently passes when its evidence is missing is worse than no
    check, because the farm believes it has one.
    """
    worker = make_worker(name="Mwiza Tembo", pin="1234")
    _enrol(worker)
    monkeypatch.setattr(cctv_engine, "grab_frames",
                        lambda count=8, **kw: ([], "camera_unavailable"))

    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    with client.session_transaction() as session:
        assert "pin_reset_worker" not in session


def test_a_matching_face_opens_the_second_stage(client, pin_face_mode, make_worker,
                                                camera, face):
    worker = make_worker(name="Kondwani Zulu", pin="1234")
    _enrol(worker)
    face(matched=True, score=91.0)

    response = client.post("/pin-reset", data={"worker_id": worker.worker_id})

    assert response.status_code == 200
    with client.session_transaction() as session:
        assert session["pin_reset_worker"] == worker.id
    assert "worker.pin_reset_verified" in _audit_actions()


# ---------------------------------------------------------------------------
# The throttle
# ---------------------------------------------------------------------------

def test_three_failures_stop_a_fourth_attempt(client, pin_face_mode, make_worker,
                                              camera, face):
    """A reset changes a credential, so it is rate-limited harder than a punch."""
    worker = make_worker(name="Chipo Mwale", pin="1234")
    _enrol(worker)
    face(matched=False, score=9.0)

    for _ in range(pin_reset.MAX_ATTEMPTS):
        client.post("/pin-reset", data={"worker_id": worker.worker_id})

    face(matched=True, score=95.0)
    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    # Even a face that would have passed is not looked at while the window
    # is closed, so no grant is issued.
    with client.session_transaction() as session:
        assert "pin_reset_worker" not in session


def test_a_success_clears_the_count(client, pin_face_mode, make_worker, camera, face):
    """A worker who mistypes once and then succeeds is not left half-locked."""
    worker = make_worker(name="Lubasi Nyambe", pin="1234")
    _enrol(worker)
    face(matched=False, score=5.0)
    client.post("/pin-reset", data={"worker_id": worker.worker_id})
    face(matched=True, score=92.0)

    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    assert pin_reset.recent_attempts(worker.worker_id.upper()) == 0


# ---------------------------------------------------------------------------
# Choosing the new PIN
# ---------------------------------------------------------------------------

def test_a_short_pin_is_rejected(app_context, make_worker):
    worker = make_worker(name="Thandiwe Kunda", pin="1234")

    assert "at least" in pin_reset.pin_problem(worker, "12", "12")


def test_a_non_numeric_pin_is_rejected(app_context, make_worker):
    worker = make_worker(name="Kabwe Mulenga", pin="1234")

    assert "digits" in pin_reset.pin_problem(worker, "abcd", "abcd")


def test_two_different_pins_are_rejected(app_context, make_worker):
    worker = make_worker(name="Bwalya Chanda", pin="1234")

    assert "did not match" in pin_reset.pin_problem(worker, "4321", "4322")


def test_a_pin_another_worker_holds_is_rejected_without_naming_them(app_context,
                                                                   make_worker):
    """Refused, but the refusal must not disclose whose PIN it is."""
    mine = make_worker(name="Musonda Banda", pin="1234")
    theirs = make_worker(name="Mwiza Tembo", pin="4321")

    problem = pin_reset.pin_problem(mine, "4321", "4321")

    assert "already in use" in problem
    assert theirs.name not in problem
    assert theirs.worker_id not in problem


def test_a_good_pin_is_accepted(app_context, make_worker):
    worker = make_worker(name="Kondwani Zulu", pin="1234")

    assert pin_reset.pin_problem(worker, "8520", "8520") == ""


def test_applying_the_pin_changes_what_the_gate_accepts(app_context, make_worker):
    worker = make_worker(name="Chipo Mwale", pin="1234")

    pin_reset.apply(worker, "8520")

    assert worker.check_pin("8520") is True
    assert worker.check_pin("1234") is False
    assert worker.pin_fingerprint == pin_reset.pin_fingerprint("8520")


# ---------------------------------------------------------------------------
# End to end, and the grant that makes it safe
# ---------------------------------------------------------------------------

def test_the_whole_reset_from_the_terminal(client, pin_face_mode, make_worker,
                                           camera, face):
    worker = make_worker(name="Lubasi Nyambe", pin="1234")
    _enrol(worker)
    face(matched=True, score=90.0)

    client.post("/pin-reset", data={"worker_id": worker.worker_id})
    response = client.post("/pin-reset/set",
                           data={"new_pin": "8520", "confirm_pin": "8520"},
                           follow_redirects=True)

    assert response.status_code == 200
    changed = Worker.query.get(worker.id)
    assert changed.check_pin("8520") is True
    assert "worker.pin_reset" in _audit_actions()


def test_setting_a_pin_without_passing_the_face_check_is_refused(client, pin_face_mode,
                                                                 make_worker):
    """The hole worth closing: the second stage is not a page you can just open."""
    worker = make_worker(name="Thandiwe Kunda", pin="1234")
    _enrol(worker)

    client.post("/pin-reset/set", data={"new_pin": "8520", "confirm_pin": "8520"},
                follow_redirects=True)

    assert Worker.query.get(worker.id).check_pin("1234") is True


def test_the_grant_expires(client, pin_face_mode, make_worker, camera, face):
    """An unattended terminal must not stay open on somebody else's account."""
    from datetime import datetime, timedelta

    worker = make_worker(name="Kabwe Mulenga", pin="1234")
    _enrol(worker)
    face(matched=True, score=90.0)
    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    with client.session_transaction() as session:
        session["pin_reset_until"] = (
            datetime.utcnow() - timedelta(seconds=1)).isoformat()

    client.post("/pin-reset/set", data={"new_pin": "8520", "confirm_pin": "8520"},
                follow_redirects=True)

    assert Worker.query.get(worker.id).check_pin("1234") is True


def test_a_worker_deactivated_mid_reset_is_dropped(client, pin_face_mode, make_worker,
                                                   camera, face):
    worker = make_worker(name="Bwalya Chanda", pin="1234")
    _enrol(worker)
    face(matched=True, score=90.0)
    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    worker.status = "inactive"
    db.session.commit()
    client.post("/pin-reset/set", data={"new_pin": "8520", "confirm_pin": "8520"},
                follow_redirects=True)

    assert Worker.query.get(worker.id).check_pin("1234") is True


def test_a_switched_off_reset_refuses_the_post_too(client, pin_face_mode, setting,
                                                   make_worker, camera, face):
    """Hiding the link is not security; the route itself has to refuse."""
    worker = make_worker(name="Musonda Banda", pin="1234")
    _enrol(worker)
    face(matched=True, score=90.0)
    setting("pin_reset_enabled", "off")

    client.post("/pin-reset", data={"worker_id": worker.worker_id})

    with client.session_transaction() as session:
        assert "pin_reset_worker" not in session


# ---------------------------------------------------------------------------
# The setting, from the page that offers it
# ---------------------------------------------------------------------------

def test_settings_page_shows_the_switch(client, signed_in, pin_face_mode):
    signed_in("admin")

    body = client.get("/settings").get_data(as_text=True)

    assert "pin_reset_enabled" in body


def test_turning_the_switch_off_is_recorded(client, signed_in, pin_face_mode):
    """A change to who may reset a credential belongs in the audit trail."""
    signed_in("admin")

    client.post("/settings", data={"org_name": "Test Farm",
                                   "clockin_mode": "pin_face",
                                   "portal_mode": "pin_face"},
                follow_redirects=True)

    assert pin_reset.enabled() is False
    assert "settings.pin_reset" in _audit_actions()
