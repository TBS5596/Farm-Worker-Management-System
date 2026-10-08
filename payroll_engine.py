"""Attendance-driven daily summaries and payroll.

The first release read every payroll figure straight out of the submitted form,
so "eliminates manual errors" was not true - the errors just moved from paper to
a web page. Here hours come from the attendance sessions, and gross, NAPSA,
NHIMA and net pay are derived from a stored rate.

Deduction rates are settings, not constants, because statutory rates change and
a hard-coded 5% would quietly become wrong.
"""

from __future__ import annotations

import calendar
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
    "shift_end_time": "16:00",
    # The working week. The default is the one most Zambian farms actually
    # run: Monday to Saturday, full days to Friday and a half day on
    # Saturday, which is 5 x 8 + 4 = 44 hours.
    #
    # This matters far more than it looks. Before these settings existed the
    # standard day was a single number applied to all seven days, so a worker
    # who put in six hours on a Saturday earned no overtime (six is under
    # eight) and a worker who came in on a Sunday was treated as though it
    # were an ordinary working day. Both are wrong, and both were invisible.
    "work_week": "mon-sat",
    "saturday_hours": "4",
    # Lunch is unpaid. It is deducted only from time a worker was actually
    # clocked in across the break - see unpaid_break_hours() for why that
    # distinction keeps the farm honest in both directions.
    "lunch_start_time": "13:00",
    "lunch_minutes": "60",
}

# Which weekdays are worked, by Python's Monday=0 numbering.
WORK_WEEKS = {
    "mon-fri": {"label": "Monday to Friday", "days": {0, 1, 2, 3, 4}},
    "mon-sat": {"label": "Monday to Saturday", "days": {0, 1, 2, 3, 4, 5}},
    "all": {"label": "Every day", "days": {0, 1, 2, 3, 4, 5, 6}},
}
DEFAULT_WORK_WEEK = "mon-sat"
SATURDAY = 5


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
        "work_week": normalize_work_week(_setting("work_week")),
        "saturday_hours": _number("saturday_hours"),
        "lunch_start_time": _clock("lunch_start_time"),
        "lunch_minutes": _number("lunch_minutes"),
    }


def normalize_work_week(value: str | None) -> str:
    key = (value or "").strip().lower()
    return key if key in WORK_WEEKS else DEFAULT_WORK_WEEK


def working_days(config: dict | None = None) -> set[int]:
    config = config or rates()
    return WORK_WEEKS[normalize_work_week(config.get("work_week"))]["days"]


def standard_hours_for(day: date, config: dict | None = None) -> float:
    """How many hours are ordinary time on this particular date.

    Everything beyond this is overtime, so this one function decides the
    difference between a long Saturday and a cheap one.

        Monday to Friday   standard_day_hours            (8 by default)
        Saturday           saturday_hours                (4 by default)
        A non-working day  0 - every hour is overtime

    A Sunday returning 0 is the point, not an oversight. Somebody who comes
    in on their rest day is working entirely outside the schedule, and the
    multiplier is the only thing that says so.
    """
    config = config or rates()
    days = working_days(config)
    weekday = day.weekday()
    if weekday not in days:
        return 0.0
    if weekday == SATURDAY:
        saturday = float(config.get("saturday_hours") or 0.0)
        # A farm that works full Saturdays leaves the half-day setting blank
        # rather than having to retype the standard day in two places.
        return saturday if saturday > 0 else float(config["standard_day_hours"])
    return float(config["standard_day_hours"])


def scheduled_end(day: date, standard: float | None = None,
                  config: dict | None = None) -> datetime:
    """When this day is due to finish.

    A full day ends at shift_end_time. A half day ends earlier, and has to be
    worked out rather than looked up: shift start, plus the hours owed, plus
    lunch only if lunch falls inside that span. Measuring a Saturday against
    the full shift would read every half day as the whole workforce leaving
    early.
    """
    config = config or rates()
    if standard is None:
        standard = standard_hours_for(day, config)
    start = datetime.combine(day, config["shift_start_time"])
    if standard >= float(config["standard_day_hours"]):
        return datetime.combine(day, config["shift_end_time"])

    end = start + timedelta(hours=standard)
    minutes = float(config.get("lunch_minutes") or 0.0)
    if minutes > 0:
        lunch_from = datetime.combine(day, config["lunch_start_time"])
        if start <= lunch_from < end:
            end += timedelta(minutes=minutes)
    return end


def weekly_standard_hours(config: dict | None = None) -> float:
    """The scheduled week, added up. 44 under the defaults.

    Used to describe the schedule on the Settings page and to prorate a
    monthly salary down to a shorter pay period.
    """
    config = config or rates()
    days = working_days(config)
    total = 0.0
    for weekday in sorted(days):
        if weekday == SATURDAY:
            saturday = float(config.get("saturday_hours") or 0.0)
            total += saturday if saturday > 0 else float(config["standard_day_hours"])
        else:
            total += float(config["standard_day_hours"])
    return round(total, 2)


def schedule_summary(config: dict | None = None) -> str:
    """The schedule in one sentence, for the Settings page and the manuals."""
    config = config or rates()
    week = WORK_WEEKS[normalize_work_week(config.get("work_week"))]
    start = config["shift_start_time"].strftime("%H:%M")
    end = config["shift_end_time"].strftime("%H:%M")
    parts = [f"{week['label']}, {start} to {end}"]
    lunch = float(config.get("lunch_minutes") or 0.0)
    if lunch > 0:
        parts.append(f"{int(lunch)} minutes unpaid lunch from "
                     f"{config['lunch_start_time'].strftime('%H:%M')}")
    if SATURDAY in week["days"]:
        saturday = float(config.get("saturday_hours") or 0.0)
        if saturday > 0 and saturday != float(config["standard_day_hours"]):
            parts.append(f"Saturday {saturday:g} hours")
    return "; ".join(parts) + f" - {weekly_standard_hours(config):g} hours a week"


def unpaid_break_hours(sessions, day: date, config: dict | None = None) -> float:
    """Lunch, deducted only where it was actually taken on the clock.

    The rule is the overlap between each clocked-in session and the lunch
    window, and it has to be the overlap rather than a flat hour, because the
    two honest ways of taking a break would otherwise be punished unequally:

      * A worker who clocks out at 13:00 and back in at 14:00 has no session
        overlapping the window, so nothing is deducted. Their break is
        already missing from their hours; deducting an hour again would
        charge them for it twice.
      * A worker who stays clocked in through the break has one continuous
        session covering the window, so the hour comes off - which is the
        case a flat rule was written for in the first place.
      * A worker who genuinely works through lunch on a day the farm asked
        them to is in the second case, so the hour still comes off. That is
        the limit of what attendance data can tell us: it records presence,
        not whether a meal was eaten. A farm that pays worked lunches
        records the extra time as overtime, or sets lunch_minutes to 0.
    """
    config = config or rates()
    minutes = float(config.get("lunch_minutes") or 0.0)
    if minutes <= 0:
        return 0.0

    lunch_from = datetime.combine(day, config["lunch_start_time"])
    lunch_to = lunch_from + timedelta(minutes=minutes)

    overlap = timedelta(0)
    for item in sessions:
        if not item.check_out_time:
            continue
        begin = max(item.check_in_time, lunch_from)
        finish = min(item.check_out_time, lunch_to)
        if finish > begin:
            overlap += finish - begin
    return round(overlap.total_seconds() / 3600.0, 2)


def worker_rate(worker: Worker) -> float:
    if worker.hourly_rate and worker.hourly_rate > 0:
        return float(worker.hourly_rate)
    return _number("default_hourly_rate")


# ---------------------------------------------------------------------------
# Pay bases
# ---------------------------------------------------------------------------
#
# A farm does not pay everybody the same way. Casual labour is hired by the
# day, a tractor driver by the hour, a farm manager on a salary - and until
# these existed all three had to be entered as an hourly rate, which meant a
# salaried supervisor lost pay for a sick day. That is not a rounding error;
# it is the wrong answer.
#
# The rate column is shared. `hourly_rate` holds "the rate in whatever unit
# the basis names" - kwacha per hour, per day, or per month. Renaming a column
# is not possible under this project's additive-only migration rule (see
# migrations.py), and a second and third rate column would let a worker hold
# three rates at once with nothing saying which one counts. One rate, one
# basis, no ambiguity - at the cost of a column whose name is now too narrow.

PAY_BASES = {
    "hourly": {
        "label": "Hourly",
        "unit": "per hour",
        "noun": "Hourly rate",
        "summary": "Paid for the hours actually worked, overtime above the "
                   "standard day at the overtime multiplier.",
    },
    "daily": {
        "label": "Daily",
        "unit": "per day",
        "noun": "Daily rate",
        "summary": "Paid a fixed amount for each day worked. A scheduled half "
                   "day pays half. Hours beyond the day's schedule are "
                   "overtime, priced from the daily rate.",
    },
    "monthly": {
        "label": "Monthly salary",
        "unit": "per month",
        "noun": "Monthly salary",
        "summary": "A fixed salary, prorated if the pay cycle is shorter than "
                   "a month. Hours do not change it, and there is no overtime.",
    },
}
DEFAULT_PAY_BASIS = "hourly"


def normalize_basis(value: str | None) -> str:
    key = (value or "").strip().lower()
    return key if key in PAY_BASES else DEFAULT_PAY_BASIS


def worker_basis(worker: Worker) -> str:
    """A worker's pay basis, defaulting to hourly.

    NULL means hourly for the same reason a NULL hourly_rate means "use the
    farm default": every worker on a database written before this column
    existed was being paid by the hour, so that is what NULL has to mean if
    their pay is not to change the day they upgrade.
    """
    return normalize_basis(getattr(worker, "pay_basis", None))


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

    clocked_hours = 0.0
    for item in closed:
        clocked_hours += max(0.0, (item.check_out_time - item.check_in_time).total_seconds() / 3600.0)

    # Lunch is unpaid, and comes off the time they were on the clock through
    # it. Taken off BEFORE overtime is worked out, so an hour at the table
    # cannot quietly become an hour at time-and-a-half.
    break_hours = unpaid_break_hours(closed, day, config)
    total_hours = round(max(0.0, clocked_hours - break_hours), 2)

    # Overtime is measured against THIS day's schedule, not a flat eight
    # hours: four on a Saturday, nothing at all on a rest day.
    standard = standard_hours_for(day, config)
    overtime = round(max(0.0, total_hours - standard), 2)

    scheduled_day = standard > 0
    shift_start = datetime.combine(day, config["shift_start_time"])
    # Lateness is only meaningful against a shift the farm actually runs. On
    # a rest day the worker was not due at all, so there is nothing to be
    # late for, and flagging them would be an accusation the schedule invented.
    late_minutes = (max(0, int((first_in - shift_start).total_seconds() // 60))
                    if first_in and scheduled_day else 0)

    early_minutes = 0
    if last_out and scheduled_day:
        early_minutes = max(0, int(
            (scheduled_end(day, standard, config) - last_out).total_seconds() // 60))

    if not summary:
        summary = DailyAttendanceSummary(worker_id=worker_pk, summary_date=day)
        db.session.add(summary)

    summary.check_in_time = first_in.time() if first_in else None
    summary.check_out_time = last_out.time() if last_out else None
    summary.total_hours = total_hours
    summary.break_hours = break_hours
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

# ---------------------------------------------------------------------------
# Pay periods
# ---------------------------------------------------------------------------
#
# Four cycles. A farm sets a default in Settings, and any individual worker can
# override it on their record - casual labour weekly, permanent staff monthly,
# on the same farm at the same time.
#
# Nothing below touches the arithmetic. compute_pay() takes hours and a rate
# and has no idea what period they came from, and overtime is decided per DAY
# in rebuild_day() against the standard day, never per period. So a monthly run
# simply sums thirty days of already-correct daily overtime instead of seven.

PERIODS = {
    "weekly":       {"label": "Weekly",       "noun": "Week"},
    "fortnightly":  {"label": "Fortnightly",  "noun": "Fortnight"},
    "semi-monthly": {"label": "Semi-monthly", "noun": "Half-month"},
    "monthly":      {"label": "Monthly",      "noun": "Month"},
}
DEFAULT_PERIOD = "weekly"


def normalize_period(value: str | None) -> str:
    """Map stored text to a known cycle, defaulting to weekly.

    Fails safe the same way security.normalize_role does: an unrecognised value
    becomes the conservative default rather than raising in the middle of a
    payroll run.
    """
    v = (value or "").strip().lower()
    return v if v in PERIODS else DEFAULT_PERIOD


def farm_period() -> str:
    """The farm-wide default cycle from Settings."""
    return normalize_period(_setting("payroll_period", DEFAULT_PERIOD))


def worker_period(worker: Worker) -> str:
    """This worker's cycle: their own if set, otherwise the farm default.

    Deliberately the same shape as worker_rate() - one worker-level value with
    a farm-level fallback - so there is one idiom to learn, not two.
    """
    own = (getattr(worker, "payroll_period", None) or "").strip().lower()
    return own if own in PERIODS else farm_period()


def period_bounds(anchor: date, period_type: str | None = None) -> tuple[date, date]:
    """The first and last day of the pay period containing `anchor`.

    How `anchor` is read depends on the cycle, and the difference is not
    arbitrary:

      weekly / fortnightly  the period ENDS on the anchor date. A farm can end
                            its week on whatever day it likes, so the operator
                            picks the date and gets the 7 or 14 days up to it.
                            This is exactly the old week_bounds behaviour.

          period_bounds(date(2026, 8, 23), "weekly")
              -> (2026-08-17, 2026-08-23)

      semi-monthly/monthly  a month ends when the calendar says it does, not
                            when somebody picks a date. So the anchor is read
                            as any day INSIDE the period and the bounds snap to
                            the calendar - which also means a clerk typing the
                            23rd gets the right month rather than an error.

          period_bounds(date(2026, 9, 23), "monthly")
              -> (2026-09-01, 2026-09-30)
          period_bounds(date(2026, 9, 23), "semi-monthly")
              -> (2026-09-16, 2026-09-30)
    """
    period_type = normalize_period(period_type)

    if period_type == "weekly":
        return anchor - timedelta(days=6), anchor
    if period_type == "fortnightly":
        return anchor - timedelta(days=13), anchor

    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    if period_type == "semi-monthly":
        if anchor.day <= 15:
            return anchor.replace(day=1), anchor.replace(day=15)
        return anchor.replace(day=16), anchor.replace(day=last_day)

    return anchor.replace(day=1), anchor.replace(day=last_day)


def period_label(start: date | None, end: date, period_type: str | None = None) -> str:
    """How a period is written on a payslip.

        weekly        "Week ending 23 Aug 2026"
        fortnightly   "Fortnight ending 23 Aug 2026"
        semi-monthly  "1-15 Sep 2026"
        monthly       "September 2026"
    """
    period_type = normalize_period(period_type)
    if period_type == "monthly":
        return end.strftime("%B %Y")
    if period_type == "semi-monthly" and start:
        return f"{start.day}-{end.day} {end.strftime('%b %Y')}"
    return f"{PERIODS[period_type]['noun']} ending {end.strftime('%d %b %Y')}"


def week_bounds(week_ending: date) -> tuple[date, date]:
    """The seven days ending on, and including, week_ending.

    Kept as the weekly case of period_bounds so existing callers and tests
    written before other cycles existed keep working unchanged.
    """
    return period_bounds(week_ending, "weekly")


def monthly_fraction(period_type: str | None, config: dict | None = None) -> float:
    """What share of a month's salary one pay period is worth.

        monthly        1
        semi-monthly   1/2
        fortnightly    12/26   (26 fortnights in a year, not 24)
        weekly         12/52   (52 weeks in a year, not 48)

    The two awkward ones are awkward on purpose. A fortnight is not half a
    month and a week is not a quarter of one; using 1/2 and 1/4 would pay a
    salaried worker thirteen months' salary a year on a fortnightly cycle.
    """
    period_type = normalize_period(period_type)
    return {
        "monthly": 1.0,
        "semi-monthly": 0.5,
        "fortnightly": 12.0 / 26.0,
        "weekly": 12.0 / 52.0,
    }[period_type]


def compute_pay(total_hours: float, overtime_hours: float, hourly_rate: float,
                config: dict | None = None, pay_basis: str = "hourly",
                day_equivalents: float = 0.0,
                period_type: str | None = None) -> dict:
    """The pay calculation itself, kept pure so the tests can pin it down.

    `hourly_rate` is the worker's rate in the unit their basis names - per
    hour, per day or per month. The name is historical; see PAY_BASES above.

    HOURLY - 42 hours of which 2 overtime, at ZMW 20.00/hour, 1.5x overtime,
    NAPSA 5%, NHIMA 1%:

        regular 40 h x 20.00            = 800.00
        overtime 2 h x 20.00 x 1.5      =  60.00
        gross                           = 860.00
        NAPSA 5%  43.00, NHIMA 1%  8.60 -> net 808.40

    DAILY - 5 full days and a Saturday half day (5.5 day-equivalents) at
    ZMW 160.00/day, with 2 hours of overtime, an 8 hour standard day:

        basic 5.5 x 160.00              = 880.00
        hourly equivalent 160/8         =  20.00
        overtime 2 h x 20.00 x 1.5      =  60.00
        gross                           = 940.00

    MONTHLY - ZMW 6,000.00/month on a weekly cycle:

        basic 6000 x 12/52              = 1384.62
        overtime                        =    0.00

    Overtime is clamped to total hours, so a mistyped correction (5 hours
    worked, 9 of them overtime) cannot inflate the gross.
    """
    config = config or rates()
    pay_basis = normalize_basis(pay_basis)
    total_hours = round(max(0.0, float(total_hours or 0.0)), 2)
    overtime_hours = round(min(max(0.0, float(overtime_hours or 0.0)), total_hours), 2)
    regular_hours = round(total_hours - overtime_hours, 2)
    rate = max(0.0, float(hourly_rate or 0.0))
    day_equivalents = round(max(0.0, float(day_equivalents or 0.0)), 2)
    standard_day = float(config["standard_day_hours"]) or 8.0

    if pay_basis == "daily":
        # One day's pay per day worked, a half day paying half - the weights
        # are decided in period_totals() against the farm's schedule.
        basic_pay = round(day_equivalents * rate, 2)
        # Overtime still has to be priced by the hour, so the daily rate is
        # divided by the standard day. A worker on 160/day with an 8 hour day
        # is on 20/hour for anything beyond it.
        hourly_equivalent = round(rate / standard_day, 4)
        overtime_pay = round(overtime_hours * hourly_equivalent * config["overtime_multiplier"], 2)
    elif pay_basis == "monthly":
        # A salary does not move with hours. That is the whole point of one,
        # and it is why a salaried worker's sick day no longer costs them.
        basic_pay = round(rate * monthly_fraction(period_type, config), 2)
        # No overtime on a salary. A farm that pays salaried staff for extra
        # hours pays it as an allowance, not through this engine - silently
        # inventing overtime on a salary is how a wage bill runs away.
        overtime_pay = 0.0
    else:
        basic_pay = round(regular_hours * rate, 2)
        overtime_pay = round(overtime_hours * rate * config["overtime_multiplier"], 2)

    gross_pay = round(basic_pay + overtime_pay, 2)
    napsa = round(gross_pay * config["napsa_rate"], 2)
    nhima = round(gross_pay * config["nhima_rate"], 2)
    net_pay = round(gross_pay - napsa - nhima, 2)

    return {
        "pay_basis": pay_basis,
        "total_hours": total_hours,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "day_equivalents": day_equivalents,
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


def period_totals(worker_pk: int, day_from: date, day_to: date) -> dict:
    """Hours, overtime and days worked between two dates, inclusive.

    The only thing that changes between a weekly and a monthly run: the two
    dates. Overtime is already decided per day, so summing thirty days is as
    correct as summing seven.
    """
    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.worker_id == worker_pk)
            .filter(DailyAttendanceSummary.summary_date >= day_from)
            .filter(DailyAttendanceSummary.summary_date <= day_to)
            .all())
    config = rates()
    standard_day = float(config["standard_day_hours"]) or 8.0

    # Day-equivalents, for the daily pay basis. A day counts as one, except a
    # day the farm schedules short - a Saturday under the default - which
    # counts as the fraction it is. A day worked when the farm is closed
    # counts as a whole day: they turned up and did a day's work, and the
    # schedule saying otherwise is what the overtime multiplier is for.
    equivalents = 0.0
    for row in rows:
        standard = standard_hours_for(row.summary_date, config)
        equivalents += 1.0 if standard <= 0 else min(1.0, standard / standard_day)

    return {
        "total_hours": round(sum(r.total_hours or 0.0 for r in rows), 2),
        "overtime_hours": round(sum(r.overtime_hours or 0.0 for r in rows), 2),
        "break_hours": round(sum(getattr(r, "break_hours", 0.0) or 0.0 for r in rows), 2),
        "days_worked": len(rows),
        "day_equivalents": round(equivalents, 2),
    }


def paid_overlap(worker_pk: int, day_from: date, day_to: date, ignore_id: int | None = None):
    """Any PAID payroll row for this worker covering days in [day_from, day_to].

    This is the guard that stops the same day being paid twice. Without it, a
    farm that switches a worker from weekly to monthly and regenerates would
    produce a monthly row covering days already settled inside four weekly
    rows, and nothing would complain.

    Legacy rows written before period_start existed are all weeks, so their
    start is inferred as six days before their end.

    Two ranges overlap when each starts on or before the other ends.
    """
    rows = (Payroll.query
            .filter(Payroll.worker_id == worker_pk)
            .filter(db.func.lower(Payroll.paid_status) == "paid")
            .all())
    for row in rows:
        if ignore_id is not None and row.payroll_id == ignore_id:
            continue
        row_end = row.week_ending
        row_start = row.period_start or (row_end - timedelta(days=6))
        if row_start <= day_to and day_from <= row_end:
            return row
    return None


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


def generate_period(anchor: date, period_type: str | None = None,
                    worker_pk: int | None = None) -> dict:
    """Create or refresh payroll rows for one pay period.

    `anchor` picks the period; how it is read depends on the cycle - see
    period_bounds(). `period_type` defaults to the farm-wide setting.

    Only workers ON THAT CYCLE are touched. Running a monthly period must not
    quietly generate for the casual labourers who are paid weekly, so each
    worker's effective cycle is checked against the one being generated.

    Four reasons a worker is skipped, each counted separately so the operator
    is told what happened rather than left wondering:

      other_cycle    they are on a different pay cycle
      no_hours       no recorded attendance in the period
      already_paid   this exact period is settled - never rewritten
      overlap        a DIFFERENT paid period already covers some of these days

    That last one is the guard against paying a day twice. It matters most
    when a worker moves from weekly to monthly: without it, the first monthly
    run would re-pay days already settled inside four weekly rows.

    Returns counts plus a row-by-row breakdown for the flash message.
    """
    period_type = normalize_period(period_type or farm_period())
    day_from, day_to = period_bounds(anchor, period_type)

    # Rebuild the daily summaries first, so the totals reflect the attendance
    # table as it stands rather than whatever was last cached.
    refresh_range(day_from, day_to, worker_pk=worker_pk)

    config = rates()
    workers = Worker.query.filter(Worker.status == "active")
    if worker_pk:
        workers = workers.filter(Worker.id == worker_pk)

    outcome = {
        "period_type": period_type,
        "period_start": day_from.isoformat(),
        "period_end": day_to.isoformat(),
        "week_ending": day_to.isoformat(),      # kept for existing callers
        "label": period_label(day_from, day_to, period_type),
        "created": 0, "updated": 0,
        "skipped_no_hours": 0, "skipped_other_cycle": 0,
        "skipped_already_paid": 0, "skipped_overlap": 0,
        "rows": [], "conflicts": [],
    }

    for worker in workers.order_by(Worker.worker_id.asc()).all():
        if worker_period(worker) != period_type:
            outcome["skipped_other_cycle"] += 1
            continue

        basis = worker_basis(worker)
        totals = period_totals(worker.id, day_from, day_to)
        # No attendance, no row - including for salaried staff. A salary is
        # not conditional on hours, but it IS conditional on the person still
        # being there, and a register with no attendance behind it is exactly
        # how a ghost worker gets paid. Mark them present for one day, or pay
        # them outside the run.
        if totals["total_hours"] <= 0:
            outcome["skipped_no_hours"] += 1
            continue

        row = Payroll.query.filter_by(worker_id=worker.id, week_ending=day_to).first()
        if row and (row.paid_status or "").lower() == "paid":
            outcome["skipped_already_paid"] += 1
            continue

        # Any OTHER paid period covering these days? If the exact-period row
        # existed and was paid we already skipped above, so anything found here
        # is a genuinely different settled period.
        clash = paid_overlap(worker.id, day_from, day_to,
                             ignore_id=row.payroll_id if row else None)
        if clash:
            outcome["skipped_overlap"] += 1
            outcome["conflicts"].append({
                "worker_id": worker.worker_id,
                "name": worker.name,
                "paid_period": period_label(
                    clash.period_start, clash.week_ending, clash.period_type),
            })
            continue

        figures = compute_pay(totals["total_hours"], totals["overtime_hours"],
                              worker_rate(worker), config, pay_basis=basis,
                              day_equivalents=totals["day_equivalents"],
                              period_type=period_type)

        created = row is None
        if created:
            row = Payroll(worker_id=worker.id, week_ending=day_to)
            db.session.add(row)

        row.period_start = day_from
        row.period_type = period_type
        # Stored on the row, not looked up from the worker at print time, for
        # the same reason napsa_rate is: a payslip has to stay reproducible
        # after the worker moves from daily to salaried.
        row.pay_basis = figures["pay_basis"]
        row.day_equivalents = figures["day_equivalents"]
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


def generate_week(week_ending: date, worker_pk: int | None = None) -> dict:
    """Generate one weekly period.

    The original entry point, kept so callers and tests written before other
    cycles existed keep working. New code should call generate_period().
    """
    return generate_period(week_ending, "weekly", worker_pk=worker_pk)


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
