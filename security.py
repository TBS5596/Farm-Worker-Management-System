"""Role-based access control.

`users.role` existed from the first release but nothing enforced it, so a
supervisor account had exactly the same power as an administrator. Roles are now
mapped to named permissions, checked in the routes and used in the templates to
hide controls a user cannot operate.
"""

from __future__ import annotations

from functools import wraps

from flask import flash, redirect, request, session, url_for

VIEW = "view"
WORKER_MANAGE = "worker.manage"
ATTENDANCE_MANAGE = "attendance.manage"
PAYROLL_MANAGE = "payroll.manage"
CCTV_MANAGE = "cctv.manage"
BIOMETRIC_MANAGE = "biometric.manage"
SYNC_MANAGE = "sync.manage"
USER_MANAGE = "user.manage"
SETTINGS_MANAGE = "settings.manage"

# Roles as permission sets rather than a hierarchy of numbers, so a new
# permission is added in one place and every role's answer stays explicit.
# The sets nest in practice: viewer < supervisor < admin, which the tests
# assert - a supervisor can run the farm day to day but cannot create accounts
# or change statutory rates.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        VIEW, WORKER_MANAGE, ATTENDANCE_MANAGE, PAYROLL_MANAGE, CCTV_MANAGE,
        BIOMETRIC_MANAGE, SYNC_MANAGE, USER_MANAGE, SETTINGS_MANAGE,
    },
    "supervisor": {
        VIEW, WORKER_MANAGE, ATTENDANCE_MANAGE, PAYROLL_MANAGE, CCTV_MANAGE,
        BIOMETRIC_MANAGE, SYNC_MANAGE,
    },
    "viewer": {VIEW},
}

ROLE_LABELS = {
    "admin": "Administrator - full access",
    "supervisor": "Supervisor - operations, no users or settings",
    "viewer": "Viewer - read only",
}


def normalize_role(role: str | None) -> str:
    """Map stored text to a known role, defaulting to the least privileged.

        "Admin" -> "admin"     "manager" -> "viewer"     None -> "viewer"

    Failing closed matters: an unrecognised value in the database must not
    become an administrator by accident. app._seed_defaults handles the
    legitimate upgrade case separately, promoting an account when a database
    written before roles were enforced has no administrator at all.
    """
    value = (role or "").strip().lower()
    return value if value in ROLE_PERMISSIONS else "viewer"


def permissions_for(role: str | None) -> set[str]:
    return ROLE_PERMISSIONS[normalize_role(role)]


def current_role() -> str:
    return normalize_role(session.get("admin_role"))


def can(permission: str) -> bool:
    """Used by routes and exposed to templates as `can()`."""
    if not session.get("admin_logged_in"):
        return False
    return permission in permissions_for(session.get("admin_role"))


def admin_required(f):
    """Any signed-in dashboard user."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            flash("Please log in to access the dashboard.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def permission_required(permission: str):
    """Require a signed-in user whose role carries `permission`.

        @app.route("/workers/add", methods=["POST"])
        @permission_required(WORKER_MANAGE)
        def add_worker(): ...

    A viewer posting that form is redirected back with an explanation rather
    than silently failing. The template hides the button too, but this is the
    check that actually enforces it.
    """
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not session.get("admin_logged_in"):
                flash("Please log in to access the dashboard.", "warning")
                return redirect(url_for("login"))
            if not can(permission):
                flash(
                    f"Your role ({current_role()}) is not permitted to perform that action.",
                    "danger",
                )
                return redirect(request.referrer or url_for("dashboard"))
            return f(*args, **kwargs)
        return decorated
    return wrapper
