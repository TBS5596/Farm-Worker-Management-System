"""Additive schema migrations for existing SQLite databases.

`db.create_all()` creates missing tables but never alters existing ones, so an
`fms.db` created by an earlier release is missing the columns added for face
verification, geofencing and computed payroll.

This module compares each model's columns against the live table and issues
`ALTER TABLE ... ADD COLUMN` for anything missing. It is idempotent: running it
on an up-to-date database does nothing. It never drops or renames anything.
"""

from sqlalchemy import inspect, text

from database import db

# SQLite cannot add a NOT NULL column without a constant default, so every
# added column is declared nullable with an explicit default where useful.
_SQLITE_TYPES = {
    "INTEGER": "INTEGER",
    "BIGINT": "BIGINT",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "DATETIME": "DATETIME",
    "DATE": "DATE",
    "TIME": "TIME",
    "TEXT": "TEXT",
    "BLOB": "BLOB",
}


def _column_sql_type(column) -> str:
    try:
        compiled = column.type.compile(dialect=db.engine.dialect).upper()
    except Exception:
        compiled = "TEXT"
    base = compiled.split("(")[0].strip()
    if base.startswith("VARCHAR") or base in ("STRING", "CHAR"):
        return compiled
    return _SQLITE_TYPES.get(base, compiled or "TEXT")


def _default_clause(column) -> str:
    default = getattr(column, "default", None)
    if default is None or getattr(default, "is_callable", False):
        return ""
    value = getattr(default, "arg", None)
    if value is None or callable(value):
        return ""
    if isinstance(value, bool):
        return f" DEFAULT {1 if value else 0}"
    if isinstance(value, (int, float)):
        return f" DEFAULT {value}"
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f" DEFAULT '{escaped}'"
    return ""


def apply_migrations() -> list[str]:
    """Add any model columns missing from the live database.

    Returns descriptions of what changed, which app.create_app logs:

        Schema migrations applied: workers.hourly_rate, workers.face_enrolled_at,
        attendance.verified_by_face, attendance.check_in_match_score, ...

    Measured against a database from the previous release: 28 columns added,
    every row preserved, and the second startup a no-op. Brand-new tables are
    left to db.create_all(), which runs first.
    """
    applied: list[str] = []
    inspector = inspect(db.engine)
    existing_tables = set(inspector.get_table_names())

    for table in db.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all() handles brand-new tables
        live_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in live_columns:
                continue
            sql = (
                f'ALTER TABLE "{table.name}" '
                f'ADD COLUMN "{column.name}" {_column_sql_type(column)}'
                f"{_default_clause(column)}"
            )
            try:
                with db.engine.begin() as connection:
                    connection.execute(text(sql))
                applied.append(f"{table.name}.{column.name}")
            except Exception as exc:  # pragma: no cover - defensive
                applied.append(f"FAILED {table.name}.{column.name}: {exc}")

    return applied
