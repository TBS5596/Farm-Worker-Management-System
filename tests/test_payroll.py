"""Payroll is derived from attendance, not typed in."""

from datetime import date, datetime, time, timedelta

import payroll_engine
from database import db
from models import Attendance, Payroll


CONFIG = {
    "standard_day_hours": 8.0,
    "overtime_multiplier": 1.5,
    "napsa_rate": 0.05,
    "nhima_rate": 0.01,
    "default_hourly_rate": 15.0,
}


def test_compute_pay_applies_overtime_and_statutory_deductions():
    figures = payroll_engine.compute_pay(42.0, 2.0, 20.0, CONFIG)

    assert figures["regular_hours"] == 40.0
    assert figures["basic_pay"] == 800.0            # 40 h x 20
    assert figures["overtime_pay"] == 60.0          # 2 h x 20 x 1.5
    assert figures["gross_pay"] == 860.0
    assert figures["napsa_deduction"] == 43.0       # 5%
    assert figures["nhima_deduction"] == 8.6        # 1%
    assert figures["net_pay"] == 808.4


def test_compute_pay_never_lets_overtime_exceed_total_hours():
    figures = payroll_engine.compute_pay(5.0, 9.0, 10.0, CONFIG)

    assert figures["overtime_hours"] == 5.0
    assert figures["regular_hours"] == 0.0


def test_rebuild_day_measures_hours_overtime_and_lateness(app_context, make_worker, setting):
    setting("shift_start_time", "07:00")
    setting("shift_end_time", "17:00")
    setting("standard_day_hours", "8")

    worker = make_worker(name="Field Hand", pin="1234", rate=20.0)
    day = date(2026, 8, 24)
    db.session.add(Attendance(
        worker_id=worker.id,
        check_in_time=datetime.combine(day, time(7, 30)),
        check_out_time=datetime.combine(day, time(17, 30)),
        verified_by_face=True,
        verified_by_cctv=True,
    ))
    db.session.commit()

    summary = payroll_engine.rebuild_day(worker.id, day)

    assert summary.total_hours == 10.0
    assert summary.overtime_hours == 2.0
    assert summary.late_minutes == 30
    assert summary.early_departure_minutes == 0
    assert summary.verified_by_face is True


def test_rebuild_day_ignores_a_session_that_is_still_open(app_context, make_worker):
    worker = make_worker(name="Still Working", pin="1234")
    day = date(2026, 8, 25)
    db.session.add(Attendance(
        worker_id=worker.id,
        check_in_time=datetime.combine(day, time(8, 0)),
        check_out_time=None,
    ))
    db.session.commit()

    summary = payroll_engine.rebuild_day(worker.id, day)

    assert summary.total_hours == 0.0
    assert summary.sessions_count == 1


def test_generate_week_builds_payroll_from_recorded_sessions(app_context, make_worker, setting):
    setting("standard_day_hours", "8")
    setting("napsa_rate", "0.05")
    setting("nhima_rate", "0.01")

    worker = make_worker(name="Harvester", pin="1234", rate=10.0)
    week_ending = date(2026, 8, 23)  # Sunday
    for offset in range(5):          # Mon-Fri, 8 hours each
        day = week_ending - timedelta(days=6 - offset)
        db.session.add(Attendance(
            worker_id=worker.id,
            check_in_time=datetime.combine(day, time(8, 0)),
            check_out_time=datetime.combine(day, time(16, 0)),
            verified_by_face=True,
        ))
    db.session.commit()

    outcome = payroll_engine.generate_week(week_ending)

    assert outcome["created"] == 1
    row = Payroll.query.filter_by(worker_id=worker.id, week_ending=week_ending).one()
    assert row.total_hours == 40.0
    assert row.overtime_hours == 0.0
    assert row.gross_pay == 400.0
    assert row.napsa_deduction == 20.0
    assert row.nhima_deduction == 4.0
    assert row.net_pay == 376.0
    assert row.computed_from_attendance is True


def test_generate_week_never_rewrites_a_paid_week(app_context, make_worker):
    worker = make_worker(name="Paid Already", pin="1234", rate=10.0)
    week_ending = date(2026, 8, 23)
    db.session.add(Payroll(worker_id=worker.id, week_ending=week_ending,
                           total_hours=1.0, gross_pay=10.0, net_pay=10.0,
                           paid_status="paid"))
    db.session.add(Attendance(
        worker_id=worker.id,
        check_in_time=datetime.combine(week_ending, time(8, 0)),
        check_out_time=datetime.combine(week_ending, time(16, 0)),
    ))
    db.session.commit()

    payroll_engine.generate_week(week_ending)

    row = Payroll.query.filter_by(worker_id=worker.id, week_ending=week_ending).one()
    assert row.total_hours == 1.0
    assert row.paid_status == "paid"


def test_worker_rate_falls_back_to_the_default(app_context, make_worker, setting):
    setting("default_hourly_rate", "17.5")
    worker = make_worker(name="No Rate", pin="1234", rate=None)

    assert payroll_engine.worker_rate(worker) == 17.5
