"""Hourly, daily and monthly - the three ways a farm actually pays people.

Before these existed every worker had to be entered as an hourly rate, which
meant a salaried supervisor lost pay for a sick day and a day labourer's pay
moved with the clock rather than with the day. Both were wrong in ways the
system could not report, because by the time the figures reached a payslip
they looked like ordinary arithmetic.
"""

from datetime import date, datetime, time

import pytest

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


# --- the arithmetic, in isolation ------------------------------------------

def test_hourly_is_unchanged_by_the_other_bases_existing():
    figures = payroll_engine.compute_pay(42.0, 2.0, 20.0, CONFIG)

    assert figures["pay_basis"] == "hourly"
    assert figures["basic_pay"] == 800.0
    assert figures["overtime_pay"] == 60.0
    assert figures["net_pay"] == 808.4


def test_daily_pays_by_the_day_and_prices_overtime_from_it():
    """5.5 days at 160, plus 2 hours of overtime at 160/8 x 1.5."""
    figures = payroll_engine.compute_pay(
        46.0, 2.0, 160.0, CONFIG, pay_basis="daily", day_equivalents=5.5)

    assert figures["basic_pay"] == 880.0        # 5.5 x 160
    assert figures["overtime_pay"] == 60.0      # 2 x 20 x 1.5
    assert figures["gross_pay"] == 940.0


def test_daily_pay_does_not_move_with_the_hours_inside_a_day():
    """A short day and a long day are both a day's pay.

    That is what being paid by the day means, and it is the reason a day
    labourer's pay must not be derived from the clock.
    """
    short = payroll_engine.compute_pay(30.0, 0.0, 160.0, CONFIG,
                                       pay_basis="daily", day_equivalents=5.0)
    long = payroll_engine.compute_pay(40.0, 0.0, 160.0, CONFIG,
                                      pay_basis="daily", day_equivalents=5.0)
    assert short["basic_pay"] == long["basic_pay"] == 800.0


def test_a_monthly_salary_is_not_touched_by_hours():
    full = payroll_engine.compute_pay(176.0, 0.0, 6000.0, CONFIG,
                                      pay_basis="monthly", period_type="monthly")
    sick_day = payroll_engine.compute_pay(168.0, 0.0, 6000.0, CONFIG,
                                          pay_basis="monthly", period_type="monthly")

    assert full["basic_pay"] == sick_day["basic_pay"] == 6000.0


def test_a_salary_earns_no_overtime():
    figures = payroll_engine.compute_pay(200.0, 24.0, 6000.0, CONFIG,
                                         pay_basis="monthly", period_type="monthly")
    assert figures["overtime_pay"] == 0.0
    assert figures["gross_pay"] == 6000.0


@pytest.mark.parametrize("period_type, expected", [
    ("monthly", 6000.00),
    ("semi-monthly", 3000.00),
    ("fortnightly", 2769.23),      # 6000 x 12/26
    ("weekly", 1384.62),           # 6000 x 12/52
])
def test_a_salary_is_prorated_by_the_pay_cycle(period_type, expected):
    """Twelve payments a year, whatever the cycle.

    The fortnightly and weekly figures are the ones worth checking. Half and
    a quarter of a month look right and are not: there are 26 fortnights and
    52 weeks in a year, not 24 and 48, so the obvious arithmetic would pay
    thirteen months' salary a year.
    """
    figures = payroll_engine.compute_pay(40.0, 0.0, 6000.0, CONFIG,
                                         pay_basis="monthly",
                                         period_type=period_type)
    assert figures["basic_pay"] == pytest.approx(expected, abs=0.01)


def test_a_year_of_fortnightly_salary_is_still_twelve_months():
    fortnight = payroll_engine.compute_pay(80.0, 0.0, 6000.0, CONFIG,
                                           pay_basis="monthly",
                                           period_type="fortnightly")
    assert fortnight["basic_pay"] * 26 == pytest.approx(6000.0 * 12, abs=0.5)


def test_an_unknown_basis_falls_back_to_hourly():
    """Never to something expensive. A typo must not pay a month's salary."""
    figures = payroll_engine.compute_pay(10.0, 0.0, 20.0, CONFIG,
                                         pay_basis="per-fortnight-ish")
    assert figures["pay_basis"] == "hourly"
    assert figures["basic_pay"] == 200.0


def test_deductions_apply_to_every_basis():
    for basis, rate, days in [("hourly", 20.0, 0), ("daily", 160.0, 5),
                              ("monthly", 6000.0, 0)]:
        figures = payroll_engine.compute_pay(40.0, 0.0, rate, CONFIG,
                                             pay_basis=basis, day_equivalents=days,
                                             period_type="monthly")
        assert figures["napsa_deduction"] == round(figures["gross_pay"] * 0.05, 2)
        assert figures["nhima_deduction"] == round(figures["gross_pay"] * 0.01, 2)
        assert figures["net_pay"] == round(
            figures["gross_pay"] - figures["napsa_deduction"]
            - figures["nhima_deduction"], 2)


# --- through the database --------------------------------------------------

def _worked(worker, first_day, days, start=time(7, 0), end=time(16, 0)):
    for offset in range(days):
        day = date.fromordinal(first_day.toordinal() + offset)
        db.session.add(Attendance(
            worker_id=worker.id,
            check_in_time=datetime.combine(day, start),
            check_out_time=datetime.combine(day, end),
            verified_by_face=True,
        ))
    db.session.commit()


def test_a_worker_with_no_basis_set_is_still_paid_by_the_hour(app_context, make_worker):
    """The upgrade must not change anybody's pay.

    Every worker on a database written before this column existed was being
    paid hourly, so NULL has to mean hourly.
    """
    worker = make_worker(name="Existing Worker", pin="1234", rate=10.0)
    assert worker.pay_basis is None
    assert payroll_engine.worker_basis(worker) == "hourly"

    _worked(worker, date(2026, 8, 24), days=5)        # Mon-Fri, 8 h each
    payroll_engine.generate_period(date(2026, 8, 30), "weekly")

    row = Payroll.query.filter_by(worker_id=worker.id).one()
    assert row.pay_basis == "hourly"
    assert row.total_hours == pytest.approx(40.0)
    assert row.gross_pay == pytest.approx(400.0)


def test_a_saturday_pays_half_a_day_to_a_daily_worker(app_context, make_worker):
    """Mon-Fri plus a Saturday morning is 5.5 days, not 6."""
    worker = make_worker(name="Day Labourer", pin="1234", rate=160.0)
    worker.pay_basis = "daily"
    db.session.commit()

    _worked(worker, date(2026, 8, 24), days=5)                      # Mon-Fri
    _worked(worker, date(2026, 8, 29), days=1, end=time(11, 0))     # Sat morning

    payroll_engine.generate_period(date(2026, 8, 30), "weekly")
    row = Payroll.query.filter_by(worker_id=worker.id).one()

    assert row.pay_basis == "daily"
    assert row.day_equivalents == pytest.approx(5.5)
    assert row.gross_pay == pytest.approx(5.5 * 160.0)


def test_a_salaried_worker_keeps_their_salary_after_a_short_week(
        app_context, make_worker):
    """The whole reason the monthly basis exists."""
    worker = make_worker(name="Farm Manager", pin="1234", rate=6000.0)
    worker.pay_basis = "monthly"
    worker.payroll_period = "monthly"
    db.session.commit()

    _worked(worker, date(2026, 9, 1), days=3)         # three days only
    payroll_engine.generate_period(date(2026, 9, 15), "monthly")

    row = Payroll.query.filter_by(worker_id=worker.id).one()
    assert row.pay_basis == "monthly"
    assert row.gross_pay == pytest.approx(6000.0)


def test_a_salaried_worker_who_never_appears_is_still_not_paid(
        app_context, make_worker):
    """A salary is not conditional on hours. It IS conditional on existing.

    A name on the register with no attendance behind it for a whole month is
    how a ghost worker gets paid, and a salary would pay one in full.
    """
    worker = make_worker(name="Absent Manager", pin="1234", rate=6000.0)
    worker.pay_basis = "monthly"
    worker.payroll_period = "monthly"
    db.session.commit()

    outcome = payroll_engine.generate_period(date(2026, 9, 15), "monthly")

    assert outcome["created"] == 0
    assert outcome["skipped_no_hours"] == 1
    assert Payroll.query.filter_by(worker_id=worker.id).count() == 0


def test_the_payslip_remembers_the_basis_it_was_paid_on(app_context, make_worker):
    """Changing a worker's basis must not rewrite history.

    The same reasoning as storing napsa_rate on the row: a payslip has to
    stay reproducible months later, when the worker has moved on to a salary.
    """
    worker = make_worker(name="Promoted", pin="1234", rate=160.0)
    worker.pay_basis = "daily"
    db.session.commit()

    _worked(worker, date(2026, 8, 24), days=5)
    payroll_engine.generate_period(date(2026, 8, 30), "weekly")
    row = Payroll.query.filter_by(worker_id=worker.id).one()
    assert row.pay_basis == "daily"

    worker.pay_basis = "monthly"
    worker.hourly_rate = 6000.0
    db.session.commit()

    assert Payroll.query.get(row.payroll_id).pay_basis == "daily"
