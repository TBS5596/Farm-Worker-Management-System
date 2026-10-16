"""Test fixtures.

The database URI is set before `app` is imported, so the suite never touches the
real `fms.db`.

The same care is taken with the captures directory. Identity cards read a
worker's enrolment photograph off disk, and the fallback that recovers one from
its filename would otherwise pick up whatever happens to be in the developer's
own `captures/faces/` - which makes a test pass or fail depending on who is
running it and what they last demonstrated.
"""

import os
import sys
import tempfile

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db", prefix="fms-test-")
os.close(_DB_FD)
os.environ["FMS_DATABASE_URI"] = f"sqlite:///{_DB_PATH}"
os.environ["FMS_SECRET_KEY"] = "test-secret-key"

import app as app_module  # noqa: E402
import face_engine  # noqa: E402
import paths  # noqa: E402
from database import db  # noqa: E402
from models import Setting, User, Worker  # noqa: E402

flask_app = app_module.app


# One temporary tree for the whole session, emptied between tests by the
# fixture below.
_CAPTURES_DIR = tempfile.mkdtemp(prefix="fms-test-captures-")
_FACES_DIR = os.path.join(_CAPTURES_DIR, "faces")
os.makedirs(_FACES_DIR, exist_ok=True)
face_engine.BASE_DIR = _CAPTURES_DIR
face_engine.FACES_DIR = _FACES_DIR

# Rebinding face_engine alone is not enough, and the gap had a real cost.
# `app.py` does `from paths import ... FACES_DIR ...`, so it holds its OWN
# reference to the project's real captures directory and hands that to
# face_engine.enroll_frame(). The enrolment route therefore wrote into
# captures/faces/ no matter what face_engine had been pointed at - which is
# how the real photograph used by test_real_face.py came to overwrite a demo
# worker's enrolment crops, and from there appeared on a printed identity
# card in a report figure.
#
# Every module that captured a copy of the path is redirected here. A test
# run must not be able to touch the project's own captures directory at all.
for _module in (app_module, face_engine, paths):
    for _name, _value in (("CAPTURES_DIR", _CAPTURES_DIR),
                          ("FACES_DIR", _FACES_DIR),
                          ("CLIPS_DIR", os.path.join(_CAPTURES_DIR, "clips"))):
        if hasattr(_module, _name):
            setattr(_module, _name, _value)
os.makedirs(os.path.join(_CAPTURES_DIR, "clips"), exist_ok=True)


def _reset_captures() -> None:
    for name in os.listdir(_FACES_DIR):
        try:
            os.remove(os.path.join(_FACES_DIR, name))
        except OSError:
            pass


def _reset_database() -> None:
    db.drop_all()
    db.create_all()
    app_module._seed_defaults()
    face_engine.invalidate()


@pytest.fixture()
def app_context():
    with flask_app.app_context():
        _reset_database()
        _reset_captures()
        yield flask_app


@pytest.fixture()
def client(app_context):
    flask_app.config.update(TESTING=True)
    return flask_app.test_client()


@pytest.fixture()
def setting(app_context):
    def _set(key: str, value: str) -> None:
        row = Setting.query.filter_by(key=key).first()
        if row:
            row.value = value
        else:
            db.session.add(Setting(key=key, value=value))
        db.session.commit()
    return _set


@pytest.fixture()
def flat_schedule(setting):
    """Eight hours a day, seven days, no lunch - the old implicit schedule.

    Several tests here are about overtime arithmetic or pay periods and were
    written before the farm had a working week, a half-day Saturday or an
    unpaid lunch. Rather than rewrite their figures around the new defaults
    and lose what they were actually pinning down, they ask for the flat
    schedule explicitly. The real defaults are covered in test_schedule.py.
    """
    setting("work_week", "all")
    setting("saturday_hours", "0")
    setting("lunch_minutes", "0")
    setting("standard_day_hours", "8")
    setting("shift_start_time", "07:00")
    setting("shift_end_time", "17:00")


@pytest.fixture()
def make_worker(app_context):
    def _make(name="Test Worker", pin="1234", rate=20.0, status="active"):
        worker = Worker(
            worker_id=app_module._generate_worker_id(),
            name=name,
            phone_number="+260970000000",
            hourly_rate=rate,
            status=status,
            pin_fingerprint=app_module._pin_fingerprint(pin),
        )
        worker.set_pin(pin)
        db.session.add(worker)
        db.session.commit()
        return worker
    return _make


@pytest.fixture()
def signed_in(client):
    """Sign in as a given role, bypassing the temporary-password gate."""
    def _sign_in(role="admin", username=None):
        username = username or f"{role}-user"
        user = User.query.filter_by(username=username).first()
        if not user:
            user = User(username=username, name=username.title(), role=role,
                        is_active=True, must_change_password=False)
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
        with client.session_transaction() as session:
            session["admin_logged_in"] = True
            session["admin_username"] = user.username
            session["admin_user_id"] = user.id
            session["admin_role"] = role
            session["must_change_password"] = False
        return user
    return _sign_in
