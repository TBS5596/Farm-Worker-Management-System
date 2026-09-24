"""Which database am I using, and what is in it?

    python tools/db_info.py

Answers the question without starting the server, because the moment you need
the answer is usually the moment the server is showing you an empty system and
you want to know whether a fortnight of attendance is gone or simply somewhere
else.

It also lists every FMS database it can find in the project, so the common
confusion - data entered while running `python app.py` does not appear when
running under Docker, and vice versa, because those are two different files -
resolves itself in one command.

Nothing here writes. It is safe to run at any time.
"""

import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from paths import BASE_DIR  # noqa: E402

CANDIDATES = [
    ("Running directly (python app.py)", os.path.join(BASE_DIR, "fms.db")),
    ("Running under Docker", os.path.join(BASE_DIR, "data", "fms.db")),
]

COUNTS = [
    ("workers", "workers"),
    ("attendance records", "attendance"),
    ("enrolled face samples", "face_templates"),
    ("payroll rows", "payroll"),
    ("user accounts", "users"),
]


def _summarise(path: str) -> list[str]:
    """Row counts for one database file, without going through SQLAlchemy.

    Read-only and defensive on purpose: this script has to work on a file that
    is half-written, locked by a running server, or not a database at all, and
    say something useful rather than raise.
    """
    lines = []
    try:
        size = os.path.getsize(path)
    except OSError as err:
        return [f"    cannot read it: {err}"]

    modified = datetime.fromtimestamp(os.path.getmtime(path))
    lines.append(f"    {size / 1024:,.0f} KB, last changed {modified:%d %b %Y at %H:%M}")

    try:
        # Read-only, so a server holding the file open is not disturbed.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except sqlite3.Error as err:
        return lines + [f"    could not open it: {err}"]

    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if not tables:
            return lines + ["    no tables - this file is not an FMS database"]

        parts = []
        for label, table in COUNTS:
            if table not in tables:
                continue
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                continue
            parts.append(f"{count} {label}")
        lines.append("    " + (", ".join(parts) if parts else "empty"))

        if "workers" in tables:
            try:
                names = [r[0] for r in conn.execute(
                    "SELECT name FROM workers ORDER BY worker_id LIMIT 3")]
                if names:
                    lines.append("    first workers: " + ", ".join(names))
            except sqlite3.Error:
                pass
    finally:
        conn.close()

    return lines


def main() -> None:
    override = os.environ.get("FMS_DATABASE_URI")

    print()
    print("FMS databases in this project")
    print("=" * 60)

    found = 0
    for how, path in CANDIDATES:
        print()
        print(f"  {how}")
        print(f"    {path}")
        if os.path.exists(path) and os.path.getsize(path) > 0:
            found += 1
            for line in _summarise(path):
                print(line)
        else:
            print("    does not exist yet")

    print()
    print("=" * 60)

    if override:
        print(f"\nFMS_DATABASE_URI is set, so the application will ignore both of the")
        print(f"above and use this instead:\n    {override}")
    elif found == 0:
        print("\nNo database yet. One is created the first time you start the app.")
    elif found == 2:
        print("\nBoth exist. They are SEPARATE databases - data entered in one does")
        print("not appear in the other. Whichever way you start the app is the one")
        print("you will see. To carry data from one to the other, stop the app and")
        print("copy the file over the other; see 'Keeping your data between runs'")
        print("in INSTALL.md.")
    else:
        print("\nOne database. The app will keep using it every time you start,")
        print("as long as you start it the same way.")
    print()


if __name__ == "__main__":
    main()
