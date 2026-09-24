"""Pay cycles: weekly, fortnightly, semi-monthly and monthly.

Two things are being protected here.

The first is that the arithmetic does not change with the period. compute_pay()
takes hours and a rate, and overtime is decided per DAY in rebuild_day(), so a
monthly run is a weekly run over more days - and these tests pin that down.

The second is the overlap guard. A worker moved from weekly to monthly has days
that are already settled inside four weekly rows; generating the month must not
pay them again. That is a money bug, not a cosmetic one, so it gets the most
tests in the file.
"""

from datetime import date, datetime, timedelta

import pytest

import payroll_engine
from database import db
from models import Attendance, Payroll


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _shift(worker, day: date, hours: float = 8.0):
    """One closed session on a given day."""
    start = datetime.combine(day, datetime.min.time()).replace(hour=7)
    db.session.add(Attendance(worker_id=worker.id, check_in_time=start,
                              check_out_time=start + timedelta(hours=hours),
                              verified_by_face=True))
    db.session.commit()


def _worked(worker, first: date, days: int, hours: float = 8.0):
    for offset in range(days):
        _shift(worker, first + timedelta(days=offset), hours)


# ---------------------------------------------------------------------------
# period_bounds
# ---------------------------------------------------------------------------

def test_weekly_ends_on_the_date_you_choose(app_context):
    assert payroll_engine.period_bounds(date(2026, 8, 23), "weekly") == \
        (date(2026, 8, 17), date(2026, 8, 23))


def test_fortnightly_ends_on_the_date_you_choose(app_context):
    assert payroll_engine.period_bounds(date(2026, 8, 23), "fortnightly") == \
        (date(2026, 8, 10), date(2026, 8, 23))


def test_monthly_snaps_to_the_calendar_month(app_context):
    # Any day inside the month gives the whole month, so a clerk typing the
    # 23rd is not told they are wrong.
    for day in (1, 9, 23, 30):
        assert payroll_engine.period_bounds(date(2026, 9, day), "monthly") == \
            (date(2026, 9, 1), date(2026, 9, 30))


def test_monthly_handles_month_lengths_and_leap_years(app_context):
    assert payroll_engine.period_bounds(date(2026, 2, 5), "monthly")[1] == date(2026, 2, 28)
    assert payroll_engine.period_bounds(date(2028, 2, 5), "monthly")[1] == date(2028, 2, 29)
    assert payroll_engine.period_bounds(date(2026, 1, 5), "monthly")[1] == date(2026, 1, 31)


def test_semi_monthly_splits_the_month_in_two(app_context):
    assert payroll_engine.period_bounds(date(2026, 9, 3), "semi-monthly") == \
        (date(2026, 9, 1), date(2026, 9, 15))
    assert payroll_engine.period_bounds(date(2026, 9, 16), "semi-monthly") == \
        (date(2026, 9, 16), date(2026, 9, 30))
    assert payroll_engine.period_bounds(date(2026, 9, 30), "semi-monthly") == \
        (date(2026, 9, 16), date(2026, 9, 30))


def test_an_unknown_cycle_falls_back_to_weekly(app_context):
    assert payroll_engine.normalize_period("fortnightlyish") == "weekly"
    assert payroll_engine.normalize_period(None) == "weekly"
    assert payroll_engine.normalize_period("") == "weekly"


def test_week_bounds_still_behaves_as_it_always_did(app_context):
    assert payroll_engine.week_bounds(date(2026, 8, 23)) == \
        payroll_engine.period_bounds(date(2026, 8, 23), "weekly")


def test_period_labels_read_correctly(app_context):
    label = payroll_engine.period_label
    assert label(date(2026, 8, 17), date(2026, 8, 23), "weekly") == "Week ending 23 Aug 2026"
    assert label(date(2026, 9, 1), date(2026, 9, 30), "monthly") == "September 2026"
    assert label(date(2026, 9, 1), date(2026, 9, 15), "semi-monthly") == "1-15 Sep 2026"


# ---------------------------------------------------------------------------
# Whose cycle is it?
# ---------------------------------------------------------------------------

def test_a_worker_follows_the_farm_default(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    worker = make_worker(name="Default Cycle")
    assert worker.payroll_period is None
    assert payroll_engine.worker_period(worker) == "monthly"


def test_a_worker_can_override_the_farm_default(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    worker = make_worker(name="Casual Labourer")
    worker.payroll_period = "weekly"
    db.session.commit()
    assert payroll_engine.worker_period(worker) == "weekly"


def test_a_nonsense_override_falls_back_to_the_farm_default(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    worker = make_worker(name="Typo")
    worker.payroll_period = "wekly"
    db.session.commit()
    assert payroll_engine.worker_period(worker) == "monthly"


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def test_a_monthly_run_pays_the_whole_month(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    worker = make_worker(name="Monthly Staff", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=20, hours=8.0)

    outcome = payroll_engine.generate_period(date(2026, 9, 23), "monthly")
    assert outcome["created"] == 1
    assert outcome["period_start"] == "2026-09-01"
    assert outcome["period_end"] == "2026-09-30"

    row = Payroll.query.filter_by(worker_id=worker.id).one()
    assert row.period_type == "monthly"
    assert row.period_start == date(2026, 9, 1)
    assert row.week_ending == date(2026, 9, 30)
    assert row.total_hours == pytest.approx(160.0)
    assert row.gross_pay == pytest.approx(160.0 * 20.0)


def test_overtime_is_daily_so_the_period_does_not_change_it(app_context, make_worker, setting):
    """Nine-hour days give one hour of overtime each, weekly or monthly.

    This is the property that made the whole feature cheap: overtime is decided
    against the standard DAY in rebuild_day(), never against the period.
    """
    setting("payroll_period", "monthly")
    worker = make_worker(name="Long Days", rate=10.0)
    _worked(worker, date(2026, 9, 1), days=10, hours=9.0)

    payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    row = Payroll.query.filter_by(worker_id=worker.id).one()
    assert row.total_hours == pytest.approx(90.0)
    assert row.overtime_hours == pytest.approx(10.0)      # one per nine-hour day


def test_generation_only_touches_workers_on_that_cycle(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    permanent = make_worker(name="Permanent Staff", pin="1111")
    casual = make_worker(name="Casual Labourer", pin="2222")
    casual.payroll_period = "weekly"
    db.session.commit()

    _worked(permanent, date(2026, 9, 1), days=5)
    _worked(casual, date(2026, 9, 1), days=5)

    outcome = payroll_engine.generate_period(date(2026, 9, 20), "monthly")
    assert outcome["created"] == 1
    assert outcome["skipped_other_cycle"] == 1
    assert Payroll.query.filter_by(worker_id=casual.id).count() == 0
    assert Payroll.query.filter_by(worker_id=permanent.id).count() == 1


def test_the_weekly_run_then_picks_up_the_casual_worker(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    casual = make_worker(name="Casual Labourer")
    casual.payroll_period = "weekly"
    db.session.commit()
    _worked(casual, date(2026, 9, 7), days=5)

    outcome = payroll_engine.generate_period(date(2026, 9, 13), "weekly")
    assert outcome["created"] == 1
    row = Payroll.query.filter_by(worker_id=casual.id).one()
    assert row.period_type == "weekly"


# ---------------------------------------------------------------------------
# The overlap guard - the money bug
# ---------------------------------------------------------------------------

def test_a_paid_week_blocks_a_monthly_run_covering_the_same_days(app_context, make_worker, setting):
    """The case this guard exists for.

    A worker is paid weekly, four weeks are settled, then the farm moves them to
    monthly. Generating the month must NOT pay those days a second time.
    """
    setting("payroll_period", "weekly")
    worker = make_worker(name="Switched Cycle", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=25)

    payroll_engine.generate_period(date(2026, 9, 7), "weekly")
    week = Payroll.query.filter_by(worker_id=worker.id).one()
    week.paid_status = "paid"
    db.session.commit()

    worker.payroll_period = "monthly"
    db.session.commit()

    outcome = payroll_engine.generate_period(date(2026, 9, 20), "monthly")
    assert outcome["created"] == 0
    assert outcome["skipped_overlap"] == 1
    assert outcome["conflicts"][0]["worker_id"] == worker.worker_id
    # Still exactly one payroll row: the paid week. Nothing was added.
    assert Payroll.query.filter_by(worker_id=worker.id).count() == 1


def test_a_pending_week_does_not_block_anything(app_context, make_worker, setting):
    """Only PAID periods block. A pending row is provisional by definition."""
    setting("payroll_period", "weekly")
    worker = make_worker(name="Nothing Settled", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=25)

    payroll_engine.generate_period(date(2026, 9, 7), "weekly")
    assert Payroll.query.filter_by(worker_id=worker.id).one().paid_status == "pending"

    worker.payroll_period = "monthly"
    db.session.commit()
    outcome = payroll_engine.generate_period(date(2026, 9, 20), "monthly")
    assert outcome["skipped_overlap"] == 0
    assert outcome["created"] == 1


def test_regenerating_the_same_period_updates_rather_than_blocking(app_context, make_worker, setting):
    """A period must not be treated as overlapping itself."""
    setting("payroll_period", "monthly")
    worker = make_worker(name="Regenerated", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=10)

    payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    outcome = payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    assert outcome["updated"] == 1
    assert outcome["skipped_overlap"] == 0


def test_a_paid_period_is_never_rewritten(app_context, make_worker, setting):
    setting("payroll_period", "monthly")
    worker = make_worker(name="Settled", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=10)

    payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    row = Payroll.query.filter_by(worker_id=worker.id).one()
    row.paid_status = "paid"
    settled = row.net_pay
    db.session.commit()

    _worked(worker, date(2026, 9, 20), days=5)          # more hours appear
    outcome = payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    assert outcome["skipped_already_paid"] == 1
    assert Payroll.query.filter_by(worker_id=worker.id).one().net_pay == settled


def test_adjacent_periods_do_not_overlap(app_context, make_worker, setting):
    """September paid, October generated. They touch but never share a day."""
    setting("payroll_period", "monthly")
    worker = make_worker(name="Two Months", rate=20.0)
    _worked(worker, date(2026, 9, 20), days=25)         # spans into October

    payroll_engine.generate_period(date(2026, 9, 15), "monthly")
    sept = Payroll.query.filter_by(worker_id=worker.id).one()
    sept.paid_status = "paid"
    db.session.commit()

    outcome = payroll_engine.generate_period(date(2026, 10, 15), "monthly")
    assert outcome["skipped_overlap"] == 0
    assert outcome["created"] == 1


def test_legacy_rows_without_a_period_start_are_treated_as_weeks(app_context, make_worker, setting):
    """Rows written before period_start existed are all weeks.

    paid_overlap infers their start as six days before their end, which is what
    they always were - so an old paid row still blocks correctly.
    """
    setting("payroll_period", "monthly")
    worker = make_worker(name="Old Record", rate=20.0)
    _worked(worker, date(2026, 9, 1), days=25)

    legacy = Payroll(worker_id=worker.id, week_ending=date(2026, 9, 7),
                     total_hours=40.0, net_pay=700.0, paid_status="paid")
    db.session.add(legacy)
    db.session.commit()
    assert legacy.period_start is None and legacy.period_type is None

    outcome = payroll_engine.generate_period(date(2026, 9, 20), "monthly")
    assert outcome["skipped_overlap"] == 1
