"""Analytics.

A report is only worth having if its numbers are right and its findings are
discriminating. Both are tested here.

Right: each report is driven with data whose correct answer is known by
construction, so a wrong figure fails rather than merely looking plausible.

Discriminating: a report that flags everybody is one a manager stops opening.
Several tests assert that a normal workforce produces *no* findings, which is
the property most easily lost when thresholds are tuned.
"""

from datetime import date, datetime, time, timedelta

import pytest

import reports_engine
from database import db
from models import (Attendance, BiometricTransaction, DailyAttendanceSummary,
                    Payroll, Worker)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summary(worker, day, hours=8.0, overtime=0.0, late=0, verified=True):
    row = DailyAttendanceSummary(
        worker_id=worker.id,
        summary_date=day,
        check_in_time=time(7, 0),
        check_out_time=time(15, 0),
        total_hours=hours,
        overtime_hours=overtime,
        sessions_count=1,
        late_minutes=late,
        early_departure_minutes=0,
        verified_by_face=verified,
        verified_by_cctv=False,
    )
    db.session.add(row)
    return row


def _working_days(count, end=None):
    """`count` consecutive days ending today, most recent last."""
    end = end or date.today()
    return [end - timedelta(days=offset) for offset in range(count - 1, -1, -1)]


def _payroll(worker, week_ending, gross=800.0, net=750.0, hours=40.0,
             overtime_hours=0.0, overtime_pay=0.0, status="paid"):
    row = Payroll(
        worker_id=worker.id,
        week_ending=week_ending,
        period_start=week_ending - timedelta(days=6),
        period_type="weekly",
        total_hours=hours,
        overtime_hours=overtime_hours,
        hourly_rate=20.0,
        overtime_pay=overtime_pay,
        gross_pay=gross,
        napsa_rate=0.05,
        nhima_rate=0.01,
        napsa_deduction=gross * 0.05,
        nhima_deduction=gross * 0.01,
        net_pay=net,
        computed_from_attendance=True,
        paid_status=status,
    )
    db.session.add(row)
    return row


# ---------------------------------------------------------------------------
# Attendance risk
# ---------------------------------------------------------------------------

def test_a_normal_workforce_raises_nothing(app_context, make_worker):
    """The property most easily lost when thresholds are tuned."""
    days = _working_days(10)
    for index in range(4):
        worker = make_worker(name=f"Regular {index}")
        for day in days:
            _summary(worker, day)
    db.session.commit()

    result = reports_engine.attendance_risk(28)

    assert result["rows"] == [], f"flagged a healthy workforce: {result['summary']}"
    assert "No attendance concerns" in result["summary"]


def test_a_worker_who_stopped_coming_is_urgent(app_context, make_worker):
    days = _working_days(12)
    present = make_worker(name="Still Here")
    vanished = make_worker(name="Stopped Coming")
    for day in days:
        _summary(present, day)
    # Last seen well over a week ago.
    for day in days[:3]:
        _summary(vanished, day)
    db.session.commit()

    result = reports_engine.attendance_risk(28)
    flagged = {row["worker"].name: row for row in result["rows"]}

    assert "Stopped Coming" in flagged
    assert flagged["Stopped Coming"]["severity"] == 3
    assert "Still Here" not in flagged
    assert "stopped coming" in flagged["Stopped Coming"]["action"]


def test_a_worker_with_no_attendance_at_all_is_urgent(app_context, make_worker):
    days = _working_days(10)
    active = make_worker(name="Works")
    never = make_worker(name="Never Seen")
    for day in days:
        _summary(active, day)
    db.session.commit()

    result = reports_engine.attendance_risk(28)
    flagged = {row["worker"].name: row for row in result["rows"]}

    assert flagged["Never Seen"]["severity"] == 3
    assert flagged["Never Seen"]["present_days"] == 0
    assert "ghost worker" in flagged["Never Seen"]["action"]


def test_a_day_nobody_worked_is_not_counted_against_anyone(app_context, make_worker):
    """A farm holiday must not read as absence for the whole workforce."""
    days = _working_days(10)
    workers = [make_worker(name=f"Worker {i}") for i in range(3)]
    # Nobody works the middle three days - rain, a holiday, whatever.
    worked = days[:4] + days[7:]
    for worker in workers:
        for day in worked:
            _summary(worker, day)
    db.session.commit()

    result = reports_engine.attendance_risk(28)

    # Those three days are simply not operating days, so attendance is 100%.
    assert result["operating_days"] == len(worked)
    assert result["rows"] == []


def test_widespread_small_lateness_is_reported_as_a_setting_problem(app_context, make_worker):
    """When nearly everyone is late by a little, blame the clock, not the people."""
    days = _working_days(10)
    for index in range(5):
        worker = make_worker(name=f"Late {index}")
        for day in days:
            _summary(worker, day, late=15)
    db.session.commit()

    result = reports_engine.attendance_risk(28)

    assert result["systemic"], "should have spotted the pattern"
    assert "shift start time" in result["systemic"]


def test_one_persistently_late_worker_is_not_a_setting_problem(app_context, make_worker):
    """One person late among many on time is about the person."""
    days = _working_days(10)
    for index in range(5):
        worker = make_worker(name=f"Punctual {index}")
        for day in days:
            _summary(worker, day, late=0)
    latecomer = make_worker(name="Always Late")
    for day in days:
        _summary(latecomer, day, late=45)
    db.session.commit()

    result = reports_engine.attendance_risk(28)
    flagged = {row["worker"].name for row in result["rows"]}

    assert "Always Late" in flagged
    assert not result["systemic"], "one worker is not a farm-wide pattern"
    assert len(flagged) == 1


def test_empty_period_does_not_crash(app_context, make_worker):
    make_worker(name="Nobody Worked")
    result = reports_engine.attendance_risk(28)

    assert result["rows"] == []
    assert result["operating_days"] == 0
    assert result["systemic"] is None


# ---------------------------------------------------------------------------
# Labour cost
# ---------------------------------------------------------------------------

def test_labour_cost_totals_the_payroll(app_context, make_worker):
    week = date.today() - timedelta(days=3)
    first = make_worker(name="Earner One")
    second = make_worker(name="Earner Two")
    _payroll(first, week, gross=1000.0, net=940.0, hours=50.0)
    _payroll(second, week, gross=600.0, net=564.0, hours=30.0)
    db.session.commit()

    result = reports_engine.labour_cost(28)

    assert result["totals"]["gross"] == 1600.0
    assert result["totals"]["hours"] == 80.0
    assert result["totals"]["headcount"] == 2
    # Sorted by cost, highest first: the question was "who gets paid the most".
    assert result["rows"][0]["worker"].name == "Earner One"
    assert result["rows"][0]["share"] == 62.5


def test_labour_cost_groups_by_department(app_context, make_worker):
    week = date.today() - timedelta(days=3)
    for name, department, gross in [("A", "Harvesting", 500.0),
                                    ("B", "Harvesting", 700.0),
                                    ("C", "Packhouse", 300.0)]:
        worker = make_worker(name=name)
        worker.department = department
        db.session.commit()
        _payroll(worker, week, gross=gross, net=gross * 0.94)
    db.session.commit()

    result = reports_engine.labour_cost(28)
    departments = {d["name"]: d for d in result["departments"]}

    assert departments["Harvesting"]["gross"] == 1200.0
    assert departments["Harvesting"]["headcount"] == 2
    assert departments["Packhouse"]["gross"] == 300.0
    assert result["departments"][0]["name"] == "Harvesting"


def test_heavy_overtime_is_called_out(app_context, make_worker):
    week = date.today() - timedelta(days=3)
    worker = make_worker(name="Overtime Heavy")
    _payroll(worker, week, gross=1000.0, net=940.0, overtime_hours=20.0,
             overtime_pay=300.0)
    db.session.commit()

    result = reports_engine.labour_cost(28)

    assert result["totals"]["overtime_share"] == 30.0
    assert any("cheaper to add a worker" in note for note in result["notes"])


def test_pending_payroll_is_flagged_as_provisional(app_context, make_worker):
    week = date.today() - timedelta(days=3)
    worker = make_worker(name="Not Paid Yet")
    _payroll(worker, week, status="pending")
    db.session.commit()

    result = reports_engine.labour_cost(28)

    assert result["pending_count"] == 1
    assert any("still pending" in note for note in result["notes"])


def test_labour_cost_with_no_payroll_says_so(app_context, make_worker):
    make_worker(name="Unpaid")
    result = reports_engine.labour_cost(28)

    assert result["rows"] == []
    assert "No payroll" in result["summary"]


# ---------------------------------------------------------------------------
# Verification health
# ---------------------------------------------------------------------------

def test_full_verification_reads_as_healthy(app_context, make_worker):
    worker = make_worker(name="Always Verified")
    for day in _working_days(10):
        _summary(worker, day, verified=True)
    db.session.commit()

    result = reports_engine.verification_health(28)

    assert result["verified_rate"] == 100.0
    assert result["tone"] == "good"


def test_drifting_back_to_manual_is_called_out(app_context, make_worker):
    """The report the whole system depends on: has the control stopped operating?"""
    worker = make_worker(name="Mostly Manual")
    days = _working_days(10)
    for day in days[:3]:
        _summary(worker, day, verified=True)
    for day in days[3:]:
        _summary(worker, day, verified=False)
    db.session.commit()

    result = reports_engine.verification_health(28)

    assert result["verified_rate"] == 30.0
    assert result["tone"] == "bad"
    assert "returned to unverified" in result["verdict"]


def test_a_worker_refused_repeatedly_is_surfaced(app_context, make_worker):
    worker = make_worker(name="Cannot Match")
    now = datetime.utcnow()
    for index in range(6):
        db.session.add(BiometricTransaction(
            worker_id=worker.id, transaction_type="face_verify_in",
            modality="face", success=index == 0, match_score=12.0,
            threshold_used=35.0, timestamp=now - timedelta(hours=index),
            error_message=None if index == 0 else "face_did_not_match",
        ))
    db.session.commit()

    result = reports_engine.verification_health(28)
    names = {row["worker"].name for row in result["struggling"]}

    assert "Cannot Match" in names
    assert any("Re-enrol" in row["action"] for row in result["struggling"])


def test_an_occasional_refusal_is_not_surfaced(app_context, make_worker):
    """One bad frame in ten is normal and must not generate a task."""
    worker = make_worker(name="Mostly Fine")
    now = datetime.utcnow()
    for index in range(10):
        db.session.add(BiometricTransaction(
            worker_id=worker.id, transaction_type="face_verify_in",
            modality="face", success=index != 0, match_score=70.0,
            threshold_used=35.0, timestamp=now - timedelta(hours=index),
            error_message=None if index != 0 else "no_face_detected",
        ))
    db.session.commit()

    result = reports_engine.verification_health(28)

    assert result["struggling"] == []


# ---------------------------------------------------------------------------
# Hours and overtime
# ---------------------------------------------------------------------------

def test_hours_are_bucketed_by_weekday(app_context, make_worker):
    worker = make_worker(name="Weekday Worker")
    # Three consecutive Mondays.
    monday = date.today() - timedelta(days=date.today().weekday())
    for offset in (0, 7, 14):
        _summary(worker, monday - timedelta(days=offset), hours=9.0, overtime=1.0)
    db.session.commit()

    result = reports_engine.hours_patterns(28)
    mondays = next(d for d in result["weekdays"] if d["name"] == "Monday")

    assert mondays["shifts"] == 3
    assert mondays["hours"] == 27.0
    assert mondays["overtime"] == 3.0
    assert mondays["average"] == 9.0


def test_an_unusual_day_length_is_reported_as_an_observation(app_context, make_worker):
    days = _working_days(8)
    for index in range(5):
        worker = make_worker(name=f"Normal {index}")
        for day in days:
            _summary(worker, day, hours=8.0)
    long_days = make_worker(name="Very Long Days")
    for day in days:
        _summary(long_days, day, hours=13.0, overtime=5.0)
    db.session.commit()

    result = reports_engine.hours_patterns(28)
    names = {row["worker"].name for row in result["outliers"]}

    assert "Very Long Days" in names
    outlier = next(r for r in result["outliers"] if r["worker"].name == "Very Long Days")
    assert outlier["direction"] == "longer"


def test_a_uniform_workforce_has_no_outliers(app_context, make_worker):
    days = _working_days(8)
    for index in range(5):
        worker = make_worker(name=f"Same {index}")
        for day in days:
            _summary(worker, day, hours=8.0)
    db.session.commit()

    assert reports_engine.hours_patterns(28)["outliers"] == []


# ---------------------------------------------------------------------------
# A worker's own view
# ---------------------------------------------------------------------------

def test_worker_report_covers_only_that_worker(app_context, make_worker):
    """The isolation that matters: one worker's report holds nobody else's hours."""
    mine = make_worker(name="Mine")
    theirs = make_worker(name="Theirs")
    for day in _working_days(10):
        _summary(mine, day, hours=8.0)
        _summary(theirs, day, hours=12.0)
    db.session.commit()

    result = reports_engine.worker_report(mine)

    assert result["total_hours"] == 80.0      # not 200
    assert result["total_days"] == 10


def test_worker_report_compares_only_against_their_own_average(app_context, make_worker):
    worker = make_worker(name="Steady")
    this_monday = date.today() - timedelta(days=date.today().weekday())
    # Four complete weeks, each Monday to Friday. The current week is excluded
    # because it is part-worked and would read as a drop rather than a pattern.
    for week in range(1, 5):
        monday = this_monday - timedelta(days=7 * week)
        for offset in range(5):
            _summary(worker, monday + timedelta(days=offset), hours=8.0)
    db.session.commit()

    result = reports_engine.worker_report(worker)

    assert "steady" in result["trend_note"].lower()
    # No other worker is named or implied anywhere in what a worker is shown.
    assert "than" not in result["trend_note"] or "below" in result["trend_note"] \
        or "above" in result["trend_note"]


def test_worker_report_blames_the_setting_when_it_should(app_context, make_worker):
    """Consistent with what the farm-wide report concludes from the same data."""
    worker = make_worker(name="Marked Late")
    for day in _working_days(10):
        _summary(worker, day, late=15)
    db.session.commit()

    result = reports_engine.worker_report(worker)

    assert "shift start time" in result["lateness_note"]
    assert "against you" in result["lateness_note"]


def test_worker_report_with_no_history_is_empty_not_broken(app_context, make_worker):
    worker = make_worker(name="Brand New")
    result = reports_engine.worker_report(worker)

    assert result["weeks"] == []
    assert result["total_hours"] == 0
    assert result["trend_note"] == ""


# ---------------------------------------------------------------------------
# The pages
# ---------------------------------------------------------------------------

def test_analytics_page_requires_an_admin(client):
    response = client.get("/analytics")
    assert response.status_code in (302, 401, 403)


def test_analytics_page_renders(client, signed_in, make_worker):
    signed_in("admin")
    worker = make_worker(name="Someone")
    for day in _working_days(5):
        _summary(worker, day)
    db.session.commit()

    page = client.get("/analytics").get_data(as_text=True)

    assert "Analytics" in page
    assert "Is attendance still being verified?" in page


def test_report_window_is_clamped(client, signed_in):
    """A hand-edited query string must not ask for a decade of history."""
    signed_in("admin")
    assert client.get("/analytics?days=99999").status_code == 200
    assert client.get("/analytics?days=-5").status_code == 200
    assert client.get("/analytics?days=banana").status_code == 200


def test_full_report_has_every_section(app_context, make_worker):
    make_worker(name="Anyone")
    report = reports_engine.full_report(28)

    for section in ("headline", "attendance_risk", "labour_cost", "verification", "hours"):
        assert section in report, f"missing section: {section}"
