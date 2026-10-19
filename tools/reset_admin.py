"""Get back into the system when the administrator password is lost.

    python tools/reset_admin.py                 # reset the 'admin' account
    python tools/reset_admin.py --user mary     # reset somebody else
    python tools/reset_admin.py --list          # just show the accounts

Until this existed the only way back in was to delete the database, which on
a farm means deleting the attendance and payroll records the system was
bought to keep. That is not an acceptable answer to a forgotten password.

The new password is generated here and printed once. It is written with
`must_change_password` set, so whoever uses it is made to choose their own
before they can reach any page - the same gate the shipped account passes
through on a new installation.

This writes to the database, so it asks before doing it.
"""

import argparse
import os
import secrets
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import app as app_module  # noqa: E402
from database import db  # noqa: E402
from models import User  # noqa: E402
from security import ROLE_LABELS, normalize_role  # noqa: E402

# Ambiguous characters are left out: this gets read off a screen and typed
# on a terminal at a farm office, often by somebody else over the phone.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def _generate(length: int = 12) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reset a lost administrator password without losing the records.")
    parser.add_argument("--user", default="admin",
                        help="the account to reset (default: admin)")
    parser.add_argument("--list", action="store_true",
                        help="list the accounts and change nothing")
    parser.add_argument("--yes", action="store_true",
                        help="do not ask for confirmation")
    args = parser.parse_args()

    flask_app = app_module.create_app()
    with flask_app.app_context():
        for line in app_module.describe_database():
            print(line)
        print()

        users = User.query.order_by(User.id.asc()).all()
        if not users:
            print("There are no accounts in this database at all.")
            print("Start the system once with `python app.py` and it will create")
            print("the default administrator.")
            return 1

        if args.list:
            # The role labels are sentences ("Administrator - full access"),
            # so the column is the first word of one, which is the part that
            # distinguishes them.
            print(f"{'Username':<18}{'Role':<16}{'Active':<8}Must change password")
            for u in users:
                role = ROLE_LABELS.get(normalize_role(u.role), u.role).split(" -")[0]
                print(f"{u.username:<18}{role:<16}"
                      f"{'yes' if u.is_active else 'no':<8}"
                      f"{'yes' if u.must_change_password else 'no'}")
            return 0

        user = User.query.filter_by(username=args.user).first()
        if user is None:
            print(f"No account named '{args.user}'. The accounts in this database are:")
            for u in users:
                print(f"  {u.username}")
            return 1

        role = normalize_role(user.role)
        print(f"About to reset the password for '{user.username}' "
              f"({ROLE_LABELS.get(role, role)}).")
        if role != "admin":
            # Resetting a viewer's password does not get anybody back into the
            # settings, and saying so is cheaper than letting them find out.
            admins = [u.username for u in users if normalize_role(u.role) == "admin"]
            print("  Note: this account is not an administrator. The administrator "
                  f"account{'s are' if len(admins) != 1 else ' is'}: "
                  f"{', '.join(admins) if admins else 'none - no account can reach Settings'}")
        print("Nothing else in the database is touched: no worker, no attendance")
        print("record and no payroll row is changed.")
        print()

        if not args.yes:
            answer = input("Type 'reset' to go ahead, or anything else to stop: ")
            if answer.strip().lower() != "reset":
                print("Stopped. Nothing was changed.")
                return 1

        password = _generate()
        user.set_password(password)
        user.must_change_password = True
        user.is_active = True
        db.session.commit()

        try:
            app_module._log_audit("user.password_reset",
                                  f"Password reset for '{user.username}' from the command line")
        except Exception:
            pass        # an audit failure must not undo a recovery

        print()
        print("=" * 60)
        print(f"  Username:  {user.username}")
        print(f"  Password:  {password}")
        print("=" * 60)
        print()
        print("This password is shown once and is not stored anywhere in readable")
        print("form. Sign in with it now; the system will make you choose your own")
        print("before it lets you reach any page.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
