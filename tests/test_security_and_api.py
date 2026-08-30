"""Role enforcement, the JSON API and CSV exports."""

import json

import exports
import security
from models import Setting, Worker


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

def test_role_permission_map_is_a_hierarchy():
    admin = security.permissions_for("admin")
    supervisor = security.permissions_for("supervisor")
    viewer = security.permissions_for("viewer")

    assert supervisor < admin
    assert viewer < supervisor
    assert security.USER_MANAGE in admin
    assert security.USER_MANAGE not in supervisor
    assert security.PAYROLL_MANAGE in supervisor
    assert security.PAYROLL_MANAGE not in viewer


def test_unknown_roles_degrade_to_viewer():
    assert security.normalize_role("wizard") == "viewer"
    assert security.normalize_role(None) == "viewer"
    assert security.normalize_role("Admin") == "admin"


def test_viewer_cannot_add_a_worker(client, signed_in):
    signed_in("viewer")

    response = client.post("/workers/add", data={
        "name": "Sneaky Add", "phone_number": "+260970000000", "pin": "4321",
    }, follow_redirects=True)

    assert response.status_code == 200
    assert Worker.query.count() == 0


def test_supervisor_can_add_a_worker(client, signed_in):
    signed_in("supervisor")

    client.post("/workers/add", data={
        "name": "Legit Add", "phone_number": "+260970000000", "pin": "4321",
    }, follow_redirects=True)

    assert Worker.query.count() == 1


def test_supervisor_cannot_reach_user_management(client, signed_in):
    signed_in("supervisor")

    response = client.get("/users", follow_redirects=False)

    assert response.status_code == 302  # bounced back to the dashboard


def test_admin_can_reach_user_management(client, signed_in):
    signed_in("admin")

    assert client.get("/users").status_code == 200


def test_anonymous_visitors_are_sent_to_the_login_page(client):
    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert "/" in response.headers["Location"]


def test_temporary_password_blocks_the_rest_of_the_dashboard(client, signed_in):
    signed_in("admin")
    with client.session_transaction() as session:
        session["must_change_password"] = True

    response = client.get("/dashboard", follow_redirects=False)

    assert response.status_code == 302
    assert "password-change" in response.headers["Location"]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_health_endpoint_is_open_and_reports_the_engine(client):
    payload = client.get("/api/v1/health").get_json()

    assert payload["ok"] is True
    assert payload["service"] == "fms"
    assert "face_engine" in payload


def test_api_rejects_a_request_with_no_key(client):
    response = client.get("/api/v1/workers")

    assert response.status_code == 401
    assert response.get_json()["error"] == "unauthorised"


def test_api_accepts_the_configured_key(client, make_worker):
    make_worker(name="Api Worker", pin="1234")
    key = Setting.query.filter_by(key="api_key").one().value

    response = client.get("/api/v1/workers", headers={"X-API-Key": key})

    payload = response.get_json()
    assert response.status_code == 200
    assert payload["count"] == 1
    assert payload["data"][0]["name"] == "Api Worker"
    assert payload["data"][0]["face_enrolled"] is False


def test_api_rejects_a_wrong_key(client):
    response = client.get("/api/v1/workers", headers={"X-API-Key": "not-the-key"})

    assert response.status_code == 401


def test_api_clock_rejects_bad_credentials(client, make_worker):
    make_worker(name="Api Worker", pin="1234")
    key = Setting.query.filter_by(key="api_key").one().value

    response = client.post("/api/v1/attendance/clock",
                           data=json.dumps({"worker_id": "0001", "pin": "0000", "log_type": "IN"}),
                           content_type="application/json",
                           headers={"X-API-Key": key})

    assert response.status_code == 401
    assert response.get_json()["error"] == "invalid_credentials"


def test_api_payroll_generate_requires_a_week(client, signed_in):
    signed_in("admin")

    response = client.post("/api/v1/payroll/generate", json={})

    assert response.status_code == 400
    assert response.get_json()["error"] == "week_ending_required"


def test_api_sync_queue_reports_configuration(client, signed_in):
    signed_in("admin")

    payload = client.get("/api/v1/sync/queue").get_json()

    assert payload["ok"] is True
    assert payload["data"]["configured"] is False


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def test_every_export_produces_a_header_row(app_context):
    for key, (filename, builder) in exports.EXPORTS.items():
        content = builder()
        assert content.splitlines(), f"{key} produced nothing"
        assert filename.endswith(".csv")


def test_payroll_export_states_the_currency(app_context):
    header = exports.payroll_csv().splitlines()[0]

    assert "gross_pay_zmw" in header
    assert "net_pay_zmw" in header


def test_export_route_returns_a_csv_attachment(client, signed_in):
    signed_in("admin")

    response = client.get("/export/attendance.csv")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]


def test_unknown_export_key_is_a_404(client, signed_in):
    signed_in("admin")

    assert client.get("/export/salaries.csv").status_code == 404
