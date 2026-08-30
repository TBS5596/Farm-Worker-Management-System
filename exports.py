"""CSV exports for payroll, attendance, summaries and verification logs.

Listed as an optional feature in the proposal; it is what turns the dashboard
into something a payroll clerk can actually hand over.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from models import (
    Attendance,
    AuditLog,
    BiometricTransaction,
    DailyAttendanceSummary,
    Payroll,
    Worker,
)


def _csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def _stamp(value) -> str:
    """Format any date, time or datetime for a spreadsheet, or "" for None.

    "2026-08-28 07:12:05" rather than an ISO T-separator, because Excel and
    LibreOffice both parse the space form as a date without prompting.
    """
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.isoformat() if hasattr(value, "isoformat") else ("" if value is None else str(value))


def _worker_lookup() -> dict:
    """{worker.id: Worker} in one query.

    Exports join by hand rather than through the ORM's relationships: a payroll
    export of a year's rows would otherwise issue a query per row for the
    worker's name.
    """
    return {w.id: w for w in Worker.query.all()}


def attendance_csv() -> str:
    workers = _worker_lookup()
    rows = []
    for row in Attendance.query.order_by(Attendance.check_in_time.desc()).all():
        worker = workers.get(row.worker_id)
        hours = ""
        if row.check_in_time and row.check_out_time:
            hours = round((row.check_out_time - row.check_in_time).total_seconds() / 3600.0, 2)
        rows.append([
            row.attendance_id,
            worker.worker_id if worker else row.worker_id,
            worker.name if worker else "",
            _stamp(row.check_in_time),
            _stamp(row.check_out_time),
            hours,
            "yes" if row.verified_by_face else "no",
            row.check_in_match_score or "",
            "yes" if row.verified_by_cctv else "no",
            row.latitude or "",
            row.longitude or "",
            "" if row.within_geofence is None else ("yes" if row.within_geofence else "no"),
            row.distance_from_farm_m or "",
        ])
    return _csv([
        "attendance_id", "worker_id", "worker_name", "check_in", "check_out", "hours",
        "face_verified", "match_score", "snapshot_captured", "latitude", "longitude",
        "within_geofence", "distance_from_farm_m",
    ], rows)


def payroll_csv() -> str:
    workers = _worker_lookup()
    rows = []
    for row in Payroll.query.order_by(Payroll.week_ending.desc(), Payroll.payroll_id.desc()).all():
        worker = workers.get(row.worker_id)
        rows.append([
            row.payroll_id,
            worker.worker_id if worker else row.worker_id,
            worker.name if worker else "",
            _stamp(row.week_ending),
            row.total_hours or 0,
            row.overtime_hours or 0,
            row.hourly_rate or 0,
            row.overtime_pay or 0,
            row.gross_pay or 0,
            row.napsa_deduction or 0,
            row.nhima_deduction or 0,
            row.net_pay or 0,
            "computed" if row.computed_from_attendance else "manual",
            row.paid_status or "",
            _stamp(row.payment_date),
        ])
    return _csv([
        "payroll_id", "worker_id", "worker_name", "week_ending", "total_hours",
        "overtime_hours", "hourly_rate", "overtime_pay", "gross_pay_zmw",
        "napsa_deduction_zmw", "nhima_deduction_zmw", "net_pay_zmw", "source",
        "paid_status", "payment_date",
    ], rows)


def daily_summary_csv() -> str:
    workers = _worker_lookup()
    rows = []
    query = DailyAttendanceSummary.query.order_by(DailyAttendanceSummary.summary_date.desc())
    for row in query.all():
        worker = workers.get(row.worker_id)
        rows.append([
            _stamp(row.summary_date),
            worker.worker_id if worker else row.worker_id,
            worker.name if worker else "",
            _stamp(row.check_in_time),
            _stamp(row.check_out_time),
            row.total_hours or 0,
            row.overtime_hours or 0,
            row.sessions_count or 0,
            row.late_minutes or 0,
            row.early_departure_minutes or 0,
            "yes" if row.verified_by_face else "no",
        ])
    return _csv([
        "date", "worker_id", "worker_name", "first_in", "last_out", "total_hours",
        "overtime_hours", "sessions", "late_minutes", "early_departure_minutes",
        "face_verified",
    ], rows)


def biometric_csv() -> str:
    workers = _worker_lookup()
    rows = []
    query = BiometricTransaction.query.order_by(BiometricTransaction.timestamp.desc())
    for row in query.all():
        worker = workers.get(row.worker_id)
        rows.append([
            row.transaction_id,
            _stamp(row.timestamp),
            worker.worker_id if worker else (row.worker_id or ""),
            worker.name if worker else "",
            row.transaction_type,
            row.modality,
            "accepted" if row.success else "rejected",
            row.match_score if row.match_score is not None else "",
            row.threshold_used if row.threshold_used is not None else "",
            row.error_message or "",
        ])
    return _csv([
        "transaction_id", "timestamp", "worker_id", "worker_name", "type", "modality",
        "outcome", "match_score", "threshold", "reason",
    ], rows)


def audit_csv() -> str:
    rows = [[
        row.id, _stamp(row.timestamp), row.username, row.action,
        row.details or "", row.ip_address or "",
    ] for row in AuditLog.query.order_by(AuditLog.timestamp.desc()).all()]
    return _csv(["id", "timestamp", "username", "action", "details", "ip_address"], rows)


EXPORTS = {
    "attendance": ("attendance.csv", attendance_csv),
    "payroll": ("payroll.csv", payroll_csv),
    "daily-summary": ("daily_attendance_summary.csv", daily_summary_csv),
    "biometric": ("biometric_transactions.csv", biometric_csv),
    "audit-log": ("audit_log.csv", audit_csv),
}
