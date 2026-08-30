"""Test fixtures.

The database URI is set before `app` is imported, so the suite never touches the
real `fms.db`.
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
from database import db  # noqa: E402
from models import Setting, User, Worker  # noqa: E402

flask_app = app_module.app


def _reset_database() -> None:
    db.drop_all()
    db.create_all()
    app_module._seed_defaults()
    face_engine.invalidate()


@pytest.fixture()
def app_context():
    with flask_app.app_context():
        _reset_database()
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
