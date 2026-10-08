"""The working week, the half-day Saturday and the unpaid lunch.

The farm's schedule is what decides which hours are ordinary and which are
overtime, so getting it wrong is not a cosmetic problem - it is the wage bill
being wrong in a way nobody can see on the page.

The default these tests pin down is 44 hours: Monday to Saturday, 07:00 to
16:00 with an unpaid hour for lunch, and four hours on Saturday.
"""

from datetime import date, datetime, time

import payroll_engine
from database import db
from models import Attendance


MONDAY = date(2026, 8, 24)
SATURDAY = date(2026, 8, 29)
SUNDAY = date(2026, 8, 30)


def _session(worker, day, start, end):
    db.session.add(Attendance(
        worker_id=worker.id,
        check_in_time=datetime.combine(day, start),
        check_out_time=datetime.combine(day, end),
        verified_by_face=True,
    ))
    db.session.commit()


# --- the shape of the week -------------------------------------------------

def test_the_default_week_is_forty_four_hours(app_context):
    config = payroll_engine.rates()
    assert payroll_engine.weekly_standard_hours(config) == 44.0
    assert payroll_engine.standard_hours_for(MONDAY, config) == 8.0
    assert payroll_engine.standard_hours_for(SATURDAY, config) == 4.0
    assert payroll_engine.standard_hours_for(SUNDAY, config) == 0.0


def test_a_five_day_farm_drops_saturday_entirely(app_context, setting):
    setting("work_week", "mon-fri")
    config = payroll_engine.rates()
    assert payroll_engine.weekly_standard_hours(config) == 40.0
    assert payroll_engine.standard_hours_for(SATURDAY, config) == 0.0


def test_a_blank_saturday_setting_means_a_full_saturday(app_context, setting):
    """Rather than meaning "no Saturday hours at all", which would be a trap.

    A farm that works full Saturdays should not have to retype the standard
    day in a second box, and should certainly not be able to zero its
    Saturdays by clearing a field that reads like a half-day option.
    """
    setting("saturday_hours", "0")
    config = payroll_engine.rates()
    assert payroll_engine.standard_hours_for(SATURDAY, config) == 8.0


# --- lunch -----------------------------------------------------------------

def test_lunch_comes_off_a_worker_who_stayed_clocked_in(app_context, make_worker):
    worker = make_worker(name="Through Lunch", pin="1234")
    _session(worker, MONDAY, time(7, 0), time(16, 0))

    summary = payroll_engine.rebuild_day(worker.id, MONDAY)

    assert summary.break_hours == 1.0
    assert summary.total_hours == 8.0        # nine on the clock, one unpaid
    assert summary.overtime_hours == 0.0


def test_lunch_is_not_deducted_twice_from_a_worker_who_clocked_out_for_it(
        app_context, make_worker):
    """The deduction has to be an overlap, not a flat hour.

    Somebody who punches out at 13:00 and back in at 14:00 has already left
    the break out of their hours. Taking another hour off would charge them
    for the same lunch twice, and - worse - would quietly punish the worker
    who used the clock honestly.
    """
    worker = make_worker(name="Clocked Out", pin="1234")
    _session(worker, MONDAY, time(7, 0), time(13, 0))
    _session(worker, MONDAY, time(14, 0), time(16, 0))

    summary = payroll_engine.rebuild_day(worker.id, MONDAY)

    assert summary.break_hours == 0.0
    assert summary.total_hours == 8.0
    assert summary.sessions_count == 2


def test_a_short_day_that_ends_before_lunch_loses_nothing(app_context, make_worker):
    worker = make_worker(name="Morning Only", pin="1234")
    _session(worker, MONDAY, time(7, 0), time(11, 0))

    summary = payroll_engine.rebuild_day(worker.id, MONDAY)

    assert summary.break_hours == 0.0
    assert summary.total_hours == 4.0


def test_lunch_is_taken_off_before_overtime_is_worked_out(app_context, make_worker):
    """Otherwise an hour at the table becomes an hour at time-and-a-half.

    07:00 to 18:00 is eleven hours on the clock. Ten are worked, eight are
    ordinary, so two are overtime - not three.
    """
    worker = make_worker(name="Long Day", pin="1234")
    _session(worker, MONDAY, time(7, 0), time(18, 0))

    summary = payroll_engine.rebuild_day(worker.id, MONDAY)

    assert summary.total_hours == 10.0
    assert summary.overtime_hours == 2.0


def test_paid_lunch_can_be_switched_off(app_context, make_worker, setting):
    setting("lunch_minutes", "0")
    worker = make_worker(name="Paid Lunch", pin="1234")
    _session(worker, MONDAY, time(7, 0), time(16, 0))

    summary = payroll_engine.rebuild_day(worker.id, MONDAY)

    assert summary.break_hours == 0.0
    assert summary.total_hours == 9.0
    assert summary.overtime_hours == 1.0


# --- Saturday and Sunday ---------------------------------------------------

def test_a_full_saturday_earns_overtime_after_the_half_day(app_context, make_worker):
    """Four hours ordinary, the rest overtime.

    Under the old flat eight-hour day this worker earned no overtime at all
    for a full Saturday, because seven is less than eight. Nothing on the
    page said so.
    """
    worker = make_worker(name="Saturday Shift", pin="1234")
    _session(worker, SATURDAY, time(7, 0), time(15, 0))   # 8 on the clock

    summary = payroll_engine.rebuild_day(worker.id, SATURDAY)

    assert summary.total_hours == 7.0        # an hour of it was lunch
    assert summary.overtime_hours == 3.0     # four ordinary, three over


def test_a_saturday_half_day_is_not_an_early_departure(app_context, make_worker):
    """Leaving at noon on a Saturday is leaving on time.

    Measured against the full shift it would read as four hours early, and
    every Saturday would look like a mass walk-out.
    """
    worker = make_worker(name="Half Day", pin="1234")
    _session(worker, SATURDAY, time(7, 0), time(12, 0))   # 4 h + lunch window

    summary = payroll_engine.rebuild_day(worker.id, SATURDAY)

    assert summary.early_departure_minutes == 0


def test_every_hour_on_a_rest_day_is_overtime(app_context, make_worker):
    worker = make_worker(name="Sunday Call-out", pin="1234")
    _session(worker, SUNDAY, time(8, 0), time(12, 0))

    summary = payroll_engine.rebuild_day(worker.id, SUNDAY)

    assert summary.total_hours == 4.0
    assert summary.overtime_hours == 4.0


def test_nobody_is_late_on_a_day_the_farm_is_closed(app_context, make_worker):
    """There is no shift to be late for, so the accusation would be invented."""
    worker = make_worker(name="Sunday Call-out", pin="1234")
    _session(worker, SUNDAY, time(10, 0), time(12, 0))    # three hours "late"

    summary = payroll_engine.rebuild_day(worker.id, SUNDAY)

    assert summary.late_minutes == 0
    assert summary.early_departure_minutes == 0


def test_the_schedule_describes_itself_in_one_line(app_context):
    text = payroll_engine.schedule_summary()
    assert "Monday to Saturday" in text
    assert "44 hours a week" in text
