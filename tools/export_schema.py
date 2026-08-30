"""Generate Workers.sql from models.py.

`models.py` is the single source of truth for the schema. This script writes the
equivalent SQL so the report, an ER diagram tool or an external database can read
the schema without running the application.

    python tools/export_schema.py

Deliberately imports only the models and SQLAlchemy - not the Flask app - so it
runs without OpenCV or a camera present.
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.dialects import sqlite  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

import models  # noqa: E402,F401  (importing registers every table)
from database import db  # noqa: E402

HEADER = """-- ---------------------------------------------------------------------------
-- Farm Worker Management System - database schema
--
-- GENERATED FILE. Do not edit by hand.
-- Source of truth: models.py
-- Regenerate with: python tools/export_schema.py
-- Generated: {stamp} UTC
-- Dialect: SQLite (the deployment target; Postgres or MySQL need type tweaks)
-- ---------------------------------------------------------------------------

"""


def main() -> None:
    dialect = sqlite.dialect()
    parts = [HEADER.format(stamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"))]

    for table in db.metadata.sorted_tables:
        parts.append(f"-- Table: {table.name}\n")
        parts.append(str(CreateTable(table).compile(dialect=dialect)).strip() + ";\n\n")
        for index in table.indexes:
            parts.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";\n")
        if table.indexes:
            parts.append("\n")

    target = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Workers.sql"))
    with open(target, "w", encoding="utf-8") as handle:
        handle.write("".join(parts))
    print(f"Wrote {target} ({len(db.metadata.sorted_tables)} tables)")


if __name__ == "__main__":
    main()
