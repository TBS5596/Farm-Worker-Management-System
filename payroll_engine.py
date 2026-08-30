"""Attendance-driven daily summaries and payroll.

The first release read every payroll figure straight out of the submitted form,
so "eliminates manual errors" was not true - the errors just moved from paper to
a web page. Here hours come from the attendance sessions, and gross, NAPSA,
NHIMA and net pay are derived from a stored rate.

Deduction rates are settings, not constants, because statutory rates change and
a hard-coded 5% would quietly become wrong.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from database import db
from models import Attendance, DailyAttendanceSummary, Payroll, Setting, Worker

DEFAULTS = {
    "standard_day_hours": "8",
    "overtime_multiplier": "1.5",
    "napsa_rate": "0.05",
    "nhima_rate": "0.01",
    "default_hourly_rate": "15",
    "shift_start_time": "07:00",
    "shift_end_time": "17:00",
}


def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    if row and row.value not in (None, ""):
        return row.value
    return default or DEFAULTS.get(key, "")


def _number(key: str) -> float:
    try:
        return float(_setting(key))
    except (TypeError, ValueError):
        return float(DEFAULTS.get(key, 0) or 0)


def _clock(key: str) -> time:
    raw = (_setting(key) or "").strip()
    try:
        hour, minute = raw.split(":")[:2]
        return time(int(hour), int(minute))
    except Exception:
        fallback = DEFAULTS.get(key, "07:00")
        hour, minute = fallback.split(":")
        return time(int(hour), int(minute))


def rates() -> dict:
    """Everything payroll depends on, in one readable place."""
    return {
        "standard_day_hours": _number("standard_day_hours"),
        "overtime_multiplier": _number("overtime_multiplier"),
        "napsa_rate": _number("napsa_rate"),
        "nhima_rate": _number("nhima_rate"),
        "default_hourly_rate": _number("default_hourly_rate"),
        "shift_start_time": _clock("shift_start_time"),
        "shift_end_time": _clock("shift_end_time"),
    }


def worker_rate(worker: Worker) -> float:
    if worker.hourly_rate and worker.hourly_rate > 0:
        return float(worker.hourly_rate)
    return _number("default_hourly_rate")


# ---------------------------------------------------------------------------
# Daily summaries
# ---------------------------------------------------------------------------

def rebuild_day(worker_pk: int, day: date) -> DailyAttendanceSummary | None:
    """Recompute one worker's summary for one day from their attendance rows.

    Only CLOSED sessions contribute hours, so somebody still clocked in shows
    total_hours 0 with sessions_count 1 - their hours appear when they clock
    out. A day with no sessions deletes any stale summary and returns None.

    Example - in at 07:30, out at 17:30, 8 hour standard day, 07:00 shift start:
        total_hours 10.0, overtime_hours 2.0, late_minutes 30,
        early_departure_minutes 0
    """
    config = rates()
    start = datetime.combine(day, time.min)
    end = start + timedelta(days=1)

    sessions = (Attendance.query
                .filter(Attendance.worker_id == worker_pk)
                .filter(Attendance.check_in_time >= start)
                .filter(Attendance.check_in_time < end)
                .order_by(Attendance.check_in_time.asc())
                .all())

    summary = DailyAttendanceSummary.query.filter_by(worker_id=worker_pk, summary_date=day).first()

    if not sessions:
        if summary:
            db.session.delete(summary)
            db.session.commit()
        return None

    first_in = sessions[0].check_in_time
    closed = [s for s in sessions if s.check_out_time]
    last_out = max((s.check_out_time for s in closed), default=None)

    total_hours = 0.0
    for item in closed:
        total_hours += max(0.0, (item.check_out_time - item.check_in_time).total_seconds() / 3600.0)
    total_hours = round(total_hours, 2)

    overtime = round(max(0.0, total_hours - config["standard_day_hours"]), 2)

    shift_start = datetime.combine(day, config["shift_start_time"])
    late_minutes = max(0, int((first_in - shift_start).total_seconds() // 60)) if first_in else 0

    early_minutes = 0
    if last_out:
        shift_end = datetime.combine(day, config["shift_end_time"])
        early_minutes = max(0, int((shift_end - last_out).total_seconds() // 60))

    if not summary:
        summary = DailyAttendanceSummary(worker_id=worker_pk, summary_date=day)
        db.session.add(summary)

    summary.check_in_time = first_in.time() if first_in else None
    summary.check_out_time = last_out.time() if last_out else None
    summary.total_hours = total_hours
    summary.overtime_hours = overtime
    summary.sessions_count = len(sessions)
    summary.late_minutes = late_minutes
    summary.early_departure_minutes = early_minutes
    summary.verified_by_cctv = any(bool(s.verified_by_cctv) for s in sessions)
    summary.verified_by_face = any(bool(s.verified_by_face) for s in sessions)
    summary.updated_at = datetime.utcnow()
    db.session.commit()
    return summary


def refresh_range(day_from: date, day_to: date, worker_pk: int | None = None) -> int:
    """Rebuild summaries across a date range. Returns rows touched."""
    query = db.session.query(Attendance.worker_id, Attendance.check_in_time) \
        .filter(Attendance.check_in_time >= datetime.combine(day_from, time.min)) \
        .filter(Attendance.check_in_time < datetime.combine(day_to + timedelta(days=1), time.min))
    if worker_pk:
        query = query.filter(Attendance.worker_id == worker_pk)

    pairs = {(int(w), c.date()) for w, c in query.all() if c}
    for pk, day in sorted(pairs):
        rebuild_day(pk, day)
    return len(pairs)


# ---------------------------------------------------------------------------
# Payroll
# ---------------------------------------------------------------------------

def week_bounds(week_ending: date) -> tuple[date, date]:
    """The seven days ending on, and including, week_ending.

        week_bounds(date(2026, 8, 23))  ->  (2026-08-17, 2026-08-23)
    """
    return week_ending - timedelta(days=6), week_ending


def compute_pay(total_hours: float, overtime_hours: float, hourly_rate: float,
                config: dict | None = None) -> dict:
    """The pay calculation itself, kept pure so the tests can pin it down.

    Worked example - 42 hours of which 2 overtime, at ZMW 20.00/hour, with an
    8 hour standard day, 1.5x overtime, NAPSA 5% and NHIMA 1%:

        regular 40 h x 20.00            = 800.00
        overtime 2 h x 20.00 x 1.5      =  60.00
        gross                           = 860.00
        NAPSA 5%                        =  43.00
        NHIMA 1%                        =   8.60
        net                             = 808.40

    Overtime is clamped to total hours, so a mistyped correction (5 hours
    worked, 9 of them overtime) cannot inflate the gross.
    """
    config = config or rates()
    total_hours = round(max(0.0, float(total_hours or 0.0)), 2)
    overtime_hours = round(min(max(0.0, float(overtime_hours or 0.0)), total_hours), 2)
    regular_hours = round(total_hours - overtime_hours, 2)
    rate = max(0.0, float(hourly_rate or 0.0))

    basic_pay = round(regular_hours * rate, 2)
    overtime_pay = round(overtime_hours * rate * config["overtime_multiplier"], 2)
    gross_pay = round(basic_pay + overtime_pay, 2)
    napsa = round(gross_pay * config["napsa_rate"], 2)
    nhima = round(gross_pay * config["nhima_rate"], 2)
    net_pay = round(gross_pay - napsa - nhima, 2)

    return {
        "total_hours": total_hours,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "hourly_rate": rate,
        "basic_pay": basic_pay,
        "overtime_pay": overtime_pay,
        "gross_pay": gross_pay,
        "napsa_rate": config["napsa_rate"],
        "nhima_rate": config["nhima_rate"],
        "napsa_deduction": napsa,
        "nhima_deduction": nhima,
        "net_pay": net_pay,
    }


def week_totals(worker_pk: int, week_ending: date) -> dict:
    day_from, day_to = week_bounds(week_ending)
    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.worker_id == worker_pk)
            .filter(DailyAttendanceSummary.summary_date >= day_from)
            .filter(DailyAttendanceSummary.summary_date <= day_to)
            .all())
    return {
        "total_hours": round(sum(r.total_hours or 0.0 for r in rows), 2),
        "overtime_hours": round(sum(r.overtime_hours or 0.0 for r in rows), 2),
        "days_worked": len(rows),
    }


def generate_week(week_ending: date, worker_pk: int | None = None) -> dict:
    """Create or refresh payroll rows for a week from recorded attendance.

    Rebuilds the seven daily summaries first, so the totals reflect the
    attendance table as it stands rather than whatever was last cached.

    A week already marked `paid` is skipped, never rewritten - so re-running
    generation after a correction elsewhere is always safe.

    Returns counts plus a row-by-row breakdown, which the flash message
    summarises: "3 created, 2 updated from recorded attendance. 2 workers had
    no hours."
    """
    day_from, day_to = week_bounds(week_ending)
    refresh_range(day_from, day_to, worker_pk=worker_pk)

    config = rates()
    workers = Worker.query.filter(Worker.status == "active")
    if worker_pk:
        workers = workers.filter(Worker.id == worker_pk)

    outcome = {"week_ending": week_ending.isoformat(), "created": 0, "updated": 0,
               "skipped_no_hours": 0, "rows": []}

    for worker in workers.order_by(Worker.worker_id.asc()).all():
        totals = week_totals(worker.id, week_ending)
        if totals["total_hours"] <= 0:
            outcome["skipped_no_hours"] += 1
            continue

        figures = compute_pay(totals["total_hours"], totals["overtime_hours"],
                             worker_rate(worker), config)

        row = Payroll.query.filter_by(worker_id=worker.id, week_ending=week_ending).first()
        if row and (row.paid_status or "").lower() == "paid":
            continue  # never rewrite a paid week

        created = row is None
        if created:
            row = Payroll(worker_id=worker.id, week_ending=week_ending)
            db.session.add(row)

        row.total_hours = figures["total_hours"]
        row.overtime_hours = figures["overtime_hours"]
        row.hourly_rate = figures["hourly_rate"]
        row.overtime_pay = figures["overtime_pay"]
        row.gross_pay = figures["gross_pay"]
        row.napsa_rate = figures["napsa_rate"]
        row.nhima_rate = figures["nhima_rate"]
        row.napsa_deduction = figures["napsa_deduction"]
        row.nhima_deduction = figures["nhima_deduction"]
        row.net_pay = figures["net_pay"]
        row.computed_from_attendance = True
        row.generated_at = datetime.utcnow()
        if not row.paid_status:
            row.paid_status = "pending"

        outcome["created" if created else "updated"] += 1
        outcome["rows"].append({
            "worker_id": worker.worker_id,
            "name": worker.name,
            "days_worked": totals["days_worked"],
            **figures,
        })

    db.session.commit()
    return outcome


def attendance_trend(days: int = 14) -> dict:
    """Daily clock-in counts and verification rate for the dashboard chart."""
    today = date.today()
    start = today - timedelta(days=max(1, days) - 1)
    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.summary_date >= start)
            .filter(DailyAttendanceSummary.summary_date <= today)
            .all())

    buckets: dict[date, dict] = {}
    for offset in range((today - start).days + 1):
        day = start + timedelta(days=offset)
        buckets[day] = {"workers": 0, "hours": 0.0, "verified": 0}

    for row in rows:
        bucket = buckets.get(row.summary_date)
        if bucket is None:
            continue
        bucket["workers"] += 1
        bucket["hours"] += row.total_hours or 0.0
        if row.verified_by_face:
            bucket["verified"] += 1

    labels = [day.strftime("%d %b") for day in buckets]
    return {
        "labels": labels,
        "workers": [b["workers"] for b in buckets.values()],
        "hours": [round(b["hours"], 2) for b in buckets.values()],
        "verified": [b["verified"] for b in buckets.values()],
    }
