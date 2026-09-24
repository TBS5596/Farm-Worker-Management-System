"""Analytics: the questions a farm manager actually asks, answered.

The dashboard shows what is happening right now. This module answers the
questions that only appear once you look across weeks: who has stopped turning
up, where the wage bill is going, whether the verification that the whole system
rests on is still working, and where overtime is accumulating.

Three principles run through it.

**Every figure is derived, never estimated.** Each report reads the same daily
summaries and payroll rows the rest of the system writes. If a number here
disagrees with the attendance register, the register is right and this is a bug.

**Every finding carries its own explanation.** A report that says
"Chipo Mwale: 0.42" tells a supervisor nothing. Each row that matters comes with
a plain sentence saying what was observed and what to do about it, because the
person reading this manages a farm rather than a spreadsheet.

**Nothing is ranked that should not be.** There is no productivity score and no
league table of workers. The workplace-monitoring literature records that
attendance systems get quietly extended into performance systems, so the only
thing ranked here is what the system was installed to measure: hours actually
worked, and whether the record of them is trustworthy.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

import payroll_engine
from models import (Attendance, BiometricTransaction, DailyAttendanceSummary,
                    Payroll, Worker)

# How far back the reports look by default. Four weeks is long enough for a
# pattern to separate itself from a bad week, and short enough that a farm
# recognises the period it is being told about.
DEFAULT_WINDOW_DAYS = 28


def _window(days: int) -> tuple[date, date]:
    today = date.today()
    return today - timedelta(days=max(1, days) - 1), today


def _pct(part: float, whole: float) -> float:
    return round((part / whole) * 100, 1) if whole else 0.0


# --------------------------------------------------------------------------
# 1. Attendance risk - "who is not coming for work"
# --------------------------------------------------------------------------

def attendance_risk(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Workers whose attendance has slipped, and what kind of slip it is.

    Two different problems hide under "not coming to work", and they need
    different responses, so they are separated rather than merged into one
    score:

      Absence  - the worker is not turning up at all. Measured against the
                 farm's own working rhythm, not a fixed five-day week, because
                 a farm works Saturdays and its quiet days move with the season.
      Lateness - the worker turns up, but after the shift has started.

    The comparison is against what the rest of the workforce did on the same
    days. A worker who missed the week everyone missed, because the rains closed
    the road, should not appear here at all.
    """
    start, end = _window(days)

    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.summary_date >= start)
            .filter(DailyAttendanceSummary.summary_date <= end)
            .all())
    workers = {w.id: w for w in Worker.query.filter(Worker.status == "active").all()}

    # Days on which the farm actually operated: a day nobody worked is a farm
    # holiday, not absence, and counting it would indict everyone equally.
    operating_days = sorted({r.summary_date for r in rows if r.worker_id in workers})
    if not operating_days:
        return {"window_days": days, "start": start, "end": end, "operating_days": 0,
                "rows": [], "systemic": None,
                "summary": "No attendance recorded in this period."}

    attended: dict[int, set] = defaultdict(set)
    late_days: dict[int, int] = defaultdict(int)
    late_minutes: dict[int, int] = defaultdict(int)
    last_seen: dict[int, date] = {}

    for row in rows:
        if row.worker_id not in workers:
            continue
        attended[row.worker_id].add(row.summary_date)
        if (row.late_minutes or 0) > 0:
            late_days[row.worker_id] += 1
            late_minutes[row.worker_id] += row.late_minutes or 0
        if row.worker_id not in last_seen or row.summary_date > last_seen[row.worker_id]:
            last_seen[row.worker_id] = row.summary_date

    total_days = len(operating_days)
    findings = []

    for worker_id, worker in workers.items():
        present = len(attended.get(worker_id, ()))
        missed = total_days - present
        attendance_rate = _pct(present, total_days)
        late_count = late_days.get(worker_id, 0)
        late_rate = _pct(late_count, present) if present else 0.0
        seen = last_seen.get(worker_id)
        days_since = (end - seen).days if seen else None

        notes = []
        severity = 0

        # Gone entirely. The most urgent case, and the one a paper register
        # hides longest, because nobody notices an absence of a signature.
        if present == 0:
            severity = 3
            notes.append(f"No attendance at all in the last {total_days} working days.")
        elif days_since is not None and days_since >= 7:
            severity = max(severity, 3)
            notes.append(f"Last seen {days_since} days ago, on {seen.strftime('%d %b')}.")

        # The bands are deliberately wide. A report that flags most of the
        # workforce is one a manager stops opening, so the thresholds are set
        # where a supervisor would agree there is something to discuss rather
        # than where a statistician would find a deviation.
        if present and attendance_rate < 60:
            severity = max(severity, 2)
            notes.append(f"Present on only {present} of {total_days} working days "
                         f"({attendance_rate:.0f}%).")
        elif present and attendance_rate < 75:
            severity = max(severity, 1)
            notes.append(f"Present on {present} of {total_days} working days "
                         f"({attendance_rate:.0f}%).")

        # Lateness is only judged once there are enough days to judge it on.
        # Two late mornings in a worker's first week is not a pattern.
        if present >= 5:
            average_late = round(late_minutes[worker_id] / late_count) if late_count else 0
            if late_rate >= 60 and late_count >= 5:
                severity = max(severity, 2)
                notes.append(f"Late on {late_count} of {present} days worked, "
                             f"averaging {average_late} minutes.")
            elif late_rate >= 40 and late_count >= 4:
                severity = max(severity, 1)
                notes.append(f"Late on {late_count} of {present} days worked, "
                             f"averaging {average_late} minutes.")

        if not severity:
            continue

        findings.append({
            "worker": worker,
            "severity": severity,
            "present_days": present,
            "missed_days": missed,
            "attendance_rate": attendance_rate,
            "late_days": late_count,
            "days_since_seen": days_since,
            "notes": notes,
            "action": _risk_action(severity, present, days_since),
        })

    findings.sort(key=lambda f: (-f["severity"], f["attendance_rate"]))

    # A farm-level check before the individual ones are believed.
    #
    # When most of the workforce is flagged for lateness by a similar, small
    # margin, the likeliest explanation is not that most of the workforce
    # started misbehaving at once - it is that the configured shift start does
    # not match the hour the farm actually begins. Saying so here stops a
    # supervisor having six identical and pointless conversations, and points
    # at the setting that would fix all of them.
    systemic = None
    late_flagged = [f for f in findings if any("Late on" in n for n in f["notes"])]
    if len(workers) >= 4 and len(late_flagged) >= 0.6 * len(workers):
        margins = [late_minutes[f["worker"].id] / max(1, late_days[f["worker"].id])
                   for f in late_flagged]
        typical = round(sum(margins) / len(margins)) if margins else 0
        if typical <= 30:
            shift_start = payroll_engine._clock("shift_start_time")
            systemic = (
                f"{len(late_flagged)} of {len(workers)} workers are marked late, "
                f"typically by about {typical} minutes. When nearly everyone is late "
                f"by a similar small margin, the shift start time is usually the "
                f"problem rather than the workers. The farm currently starts at "
                f"{shift_start.strftime('%H:%M')}; if work really begins later than "
                f"that, change it in Settings and these flags will clear."
            )

    urgent = sum(1 for f in findings if f["severity"] == 3)
    watch = sum(1 for f in findings if f["severity"] == 1)

    if not findings:
        summary = f"No attendance concerns across {len(workers)} active workers."
    elif urgent:
        summary = (f"{urgent} worker{'s need' if urgent != 1 else ' needs'} attention now"
                   + (f", and {len(findings) - urgent} more worth watching." if len(findings) > urgent else "."))
    else:
        summary = (f"Nobody urgent. {len(findings)} of {len(workers)} workers show a "
                   f"pattern worth a look"
                   + (f", {watch} of them mild." if watch else "."))

    return {"window_days": days, "start": start, "end": end,
            "operating_days": total_days, "rows": findings, "summary": summary,
            "systemic": systemic}


def _risk_action(severity: int, present: int, days_since: int | None) -> str:
    if present == 0:
        return ("Check whether this worker has left. A name on the register with no "
                "attendance behind it is how a ghost worker starts.")
    if days_since is not None and days_since >= 7:
        return "Find out why they stopped coming before the next payroll run."
    if severity >= 2:
        return "Worth asking about directly — this is a pattern, not a bad week."
    return "Keep an eye on it; not yet a problem."


# --------------------------------------------------------------------------
# 2. Labour cost - "who gets paid the most"
# --------------------------------------------------------------------------

def labour_cost(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Where the wage bill went, by department and by worker.

    Reads paid and pending payroll rows both, because a manager asking what
    labour is costing wants the period they are in, not only the one already
    settled. Pending rows are counted and flagged so the figure is not mistaken
    for a final one.
    """
    start, end = _window(days)

    rows = (Payroll.query
            .filter(Payroll.week_ending >= start)
            .filter(Payroll.week_ending <= end)
            .all())
    if not rows:
        return {"window_days": days, "start": start, "end": end, "rows": [],
                "departments": [], "totals": {}, "pending_count": 0,
                "summary": "No payroll has been generated for this period yet."}

    workers = {w.id: w for w in Worker.query.all()}

    by_worker: dict[int, dict] = defaultdict(
        lambda: {"gross": 0.0, "net": 0.0, "hours": 0.0, "overtime_hours": 0.0,
                 "overtime_pay": 0.0, "periods": 0})
    pending = 0

    for row in rows:
        bucket = by_worker[row.worker_id]
        bucket["gross"] += row.gross_pay or 0.0
        bucket["net"] += row.net_pay or 0.0
        bucket["hours"] += row.total_hours or 0.0
        bucket["overtime_hours"] += row.overtime_hours or 0.0
        bucket["overtime_pay"] += row.overtime_pay or 0.0
        bucket["periods"] += 1
        if (row.paid_status or "pending").lower() != "paid":
            pending += 1

    total_gross = sum(b["gross"] for b in by_worker.values())
    total_ot_pay = sum(b["overtime_pay"] for b in by_worker.values())
    total_hours = sum(b["hours"] for b in by_worker.values())

    worker_rows = []
    for worker_id, bucket in by_worker.items():
        worker = workers.get(worker_id)
        if worker is None:
            continue
        worker_rows.append({
            "worker": worker,
            "department": worker.department or "Unassigned",
            "gross": round(bucket["gross"], 2),
            "net": round(bucket["net"], 2),
            "hours": round(bucket["hours"], 2),
            "overtime_hours": round(bucket["overtime_hours"], 2),
            "overtime_pay": round(bucket["overtime_pay"], 2),
            "share": _pct(bucket["gross"], total_gross),
            # The hourly figure is what makes two workers comparable when one
            # worked twice the days of the other.
            "effective_rate": round(bucket["gross"] / bucket["hours"], 2) if bucket["hours"] else 0.0,
        })
    worker_rows.sort(key=lambda r: -r["gross"])

    by_department: dict[str, dict] = defaultdict(
        lambda: {"gross": 0.0, "hours": 0.0, "overtime_pay": 0.0, "headcount": 0})
    for row in worker_rows:
        bucket = by_department[row["department"]]
        bucket["gross"] += row["gross"]
        bucket["hours"] += row["hours"]
        bucket["overtime_pay"] += row["overtime_pay"]
        bucket["headcount"] += 1

    department_rows = [{
        "name": name,
        "gross": round(bucket["gross"], 2),
        "hours": round(bucket["hours"], 2),
        "overtime_pay": round(bucket["overtime_pay"], 2),
        "headcount": bucket["headcount"],
        "share": _pct(bucket["gross"], total_gross),
        "cost_per_worker": round(bucket["gross"] / bucket["headcount"], 2) if bucket["headcount"] else 0.0,
    } for name, bucket in by_department.items()]
    department_rows.sort(key=lambda r: -r["gross"])

    ot_share = _pct(total_ot_pay, total_gross)
    notes = []
    if ot_share >= 20:
        notes.append(f"Overtime is {ot_share:.0f}% of the wage bill. Above about a fifth, "
                     f"it is usually cheaper to add a worker than to keep paying the premium.")
    elif ot_share >= 10:
        notes.append(f"Overtime is {ot_share:.0f}% of the wage bill — worth watching.")
    if department_rows and department_rows[0]["share"] >= 50:
        notes.append(f"{department_rows[0]['name']} alone accounts for "
                     f"{department_rows[0]['share']:.0f}% of the wage bill.")
    if pending:
        notes.append(f"{pending} payroll row{'s are' if pending != 1 else ' is'} still pending, "
                     f"so these figures can still change.")

    return {
        "window_days": days, "start": start, "end": end,
        "rows": worker_rows, "departments": department_rows,
        "pending_count": pending,
        "totals": {
            "gross": round(total_gross, 2),
            "net": round(sum(b["net"] for b in by_worker.values()), 2),
            "hours": round(total_hours, 2),
            "overtime_pay": round(total_ot_pay, 2),
            "overtime_share": ot_share,
            "headcount": len(worker_rows),
            "average_gross": round(total_gross / len(worker_rows), 2) if worker_rows else 0.0,
        },
        "notes": notes,
        "summary": (f"ZMW {total_gross:,.2f} across {len(worker_rows)} workers and "
                    f"{round(total_hours):,} hours."),
    }


# --------------------------------------------------------------------------
# 3. Verification health - is the control still working?
# --------------------------------------------------------------------------

def verification_health(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Whether attendance is still being verified, or quietly going manual.

    This is the report that matters most and looks least interesting. The whole
    argument for the system is that a record is bound to a verified identity.
    If the share of face-verified attendance falls, the farm has drifted back to
    a paper register kept on a computer, and nothing else in these reports would
    reveal it.
    """
    start, end = _window(days)

    summaries = (DailyAttendanceSummary.query
                 .filter(DailyAttendanceSummary.summary_date >= start)
                 .filter(DailyAttendanceSummary.summary_date <= end)
                 .all())
    total = len(summaries)
    verified = sum(1 for s in summaries if s.verified_by_face)
    rate = _pct(verified, total)

    attempts = (BiometricTransaction.query
                .filter(BiometricTransaction.timestamp >= datetime.combine(start, datetime.min.time()))
                .all())
    refused = [a for a in attempts if not a.success]

    by_reason: dict[str, int] = defaultdict(int)
    for attempt in refused:
        by_reason[attempt.error_message or "unspecified"] += 1

    # Workers refused repeatedly. Usually an enrolment that has gone stale or a
    # camera aimed badly, not a person trying to cheat - and the difference
    # matters, because one is fixed by re-enrolling and the other by a
    # conversation.
    workers = {w.id: w for w in Worker.query.all()}
    refusals_by_worker: dict[int, int] = defaultdict(int)
    attempts_by_worker: dict[int, int] = defaultdict(int)
    for attempt in attempts:
        if attempt.worker_id:
            attempts_by_worker[attempt.worker_id] += 1
            if not attempt.success:
                refusals_by_worker[attempt.worker_id] += 1

    struggling = []
    for worker_id, refusal_count in refusals_by_worker.items():
        tries = attempts_by_worker[worker_id]
        if refusal_count < 2:
            continue
        failure_rate = _pct(refusal_count, tries)
        if failure_rate < 30:
            continue
        worker = workers.get(worker_id)
        if worker is None:
            continue
        struggling.append({
            "worker": worker,
            "refusals": refusal_count,
            "attempts": tries,
            "failure_rate": failure_rate,
            "action": ("Re-enrol this worker's face. Repeated refusals are almost always a "
                       "stale enrolment or a badly positioned camera, not someone cheating."),
        })
    struggling.sort(key=lambda r: -r["failure_rate"])

    if total == 0:
        verdict, tone = "No attendance recorded in this period.", "muted"
    elif rate >= 90:
        verdict, tone = (f"{rate:.0f}% of attendance was face-verified. The control is working.",
                         "good")
    elif rate >= 70:
        verdict, tone = (f"Only {rate:.0f}% of attendance was face-verified. Find out why the rest "
                         f"was entered manually before it becomes the habit.", "warn")
    else:
        verdict, tone = (f"Just {rate:.0f}% of attendance was face-verified. The farm has largely "
                         f"returned to unverified record-keeping, which is the problem this system "
                         f"was installed to solve.", "bad")

    return {
        "window_days": days, "start": start, "end": end,
        "total_days_recorded": total, "verified_days": verified,
        "manual_days": total - verified, "verified_rate": rate,
        "attempts": len(attempts), "refusals": len(refused),
        "refusal_reasons": sorted(by_reason.items(), key=lambda kv: -kv[1]),
        "struggling": struggling,
        "verdict": verdict, "tone": tone,
    }


# --------------------------------------------------------------------------
# 4. Hours and overtime patterns
# --------------------------------------------------------------------------

def hours_patterns(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Where the hours fall: by weekday, by department, and who sits outside.

    The weekday breakdown is the one farms find most useful, because it shows
    the shape of the week rather than a total. A Saturday that costs as much as
    a Wednesday is a scheduling decision somebody should be making on purpose.
    """
    start, end = _window(days)

    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.summary_date >= start)
            .filter(DailyAttendanceSummary.summary_date <= end)
            .all())
    if not rows:
        return {"window_days": days, "start": start, "end": end,
                "weekdays": [], "departments": [], "outliers": [],
                "summary": "No attendance recorded in this period."}

    workers = {w.id: w for w in Worker.query.all()}
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    weekday_hours: dict[int, float] = defaultdict(float)
    weekday_shifts: dict[int, int] = defaultdict(int)
    weekday_overtime: dict[int, float] = defaultdict(float)

    per_worker_hours: dict[int, float] = defaultdict(float)
    per_worker_days: dict[int, int] = defaultdict(int)
    per_worker_overtime: dict[int, float] = defaultdict(float)
    department_hours: dict[str, float] = defaultdict(float)
    department_overtime: dict[str, float] = defaultdict(float)
    department_shifts: dict[str, int] = defaultdict(int)

    for row in rows:
        index = row.summary_date.weekday()
        hours = row.total_hours or 0.0
        overtime = row.overtime_hours or 0.0
        weekday_hours[index] += hours
        weekday_shifts[index] += 1
        weekday_overtime[index] += overtime

        per_worker_hours[row.worker_id] += hours
        per_worker_days[row.worker_id] += 1
        per_worker_overtime[row.worker_id] += overtime

        worker = workers.get(row.worker_id)
        department = (worker.department if worker and worker.department else "Unassigned")
        department_hours[department] += hours
        department_overtime[department] += overtime
        department_shifts[department] += 1

    weekdays = [{
        "name": names[i],
        "shifts": weekday_shifts.get(i, 0),
        "hours": round(weekday_hours.get(i, 0.0), 2),
        "overtime": round(weekday_overtime.get(i, 0.0), 2),
        "average": round(weekday_hours.get(i, 0.0) / weekday_shifts[i], 2) if weekday_shifts.get(i) else 0.0,
    } for i in range(7)]

    departments = [{
        "name": name,
        "hours": round(hours, 2),
        "overtime": round(department_overtime[name], 2),
        "shifts": department_shifts[name],
        "average": round(hours / department_shifts[name], 2) if department_shifts[name] else 0.0,
        "overtime_share": _pct(department_overtime[name], hours),
    } for name, hours in department_hours.items()]
    departments.sort(key=lambda d: -d["hours"])

    # Workers whose average day sits well outside the rest. Reported as a
    # scheduling observation, not a judgement: a long average day may mean the
    # person is covering for an absence nobody recorded.
    averages = {wid: per_worker_hours[wid] / per_worker_days[wid]
                for wid in per_worker_days if per_worker_days[wid] >= 3}
    outliers = []
    if len(averages) >= 4:
        values = list(averages.values())
        mean = statistics.mean(values)
        spread = statistics.pstdev(values) or 0.0
        for worker_id, average in averages.items():
            if spread == 0:
                break
            distance = (average - mean) / spread
            if abs(distance) < 1.5:
                continue
            worker = workers.get(worker_id)
            if worker is None:
                continue
            outliers.append({
                "worker": worker,
                "average_day": round(average, 2),
                "farm_average": round(mean, 2),
                "days": per_worker_days[worker_id],
                "overtime": round(per_worker_overtime[worker_id], 2),
                "direction": "longer" if distance > 0 else "shorter",
                "note": (f"Averages {average:.1f} hours a day against a farm average of "
                         f"{mean:.1f}."),
            })
        outliers.sort(key=lambda o: -abs(o["average_day"] - o["farm_average"]))

    busiest = max(weekdays, key=lambda d: d["hours"]) if weekdays else None
    total_hours = round(sum(weekday_hours.values()), 2)
    total_overtime = round(sum(weekday_overtime.values()), 2)

    return {
        "window_days": days, "start": start, "end": end,
        "weekdays": weekdays, "departments": departments, "outliers": outliers,
        "total_hours": total_hours, "total_overtime": total_overtime,
        "overtime_share": _pct(total_overtime, total_hours),
        "summary": (f"{total_hours:,.0f} hours worked, {total_overtime:,.0f} of them overtime"
                    + (f". Busiest day: {busiest['name']}." if busiest and busiest["hours"] else ".")),
    }


# --------------------------------------------------------------------------
# 5. Workforce shape - the headline tiles
# --------------------------------------------------------------------------

def headline(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """The four numbers that go above everything else."""
    start, end = _window(days)
    active = Worker.query.filter(Worker.status == "active").count()

    summaries = (DailyAttendanceSummary.query
                 .filter(DailyAttendanceSummary.summary_date >= start)
                 .filter(DailyAttendanceSummary.summary_date <= end)
                 .all())
    hours = sum(s.total_hours or 0.0 for s in summaries)
    verified = sum(1 for s in summaries if s.verified_by_face)

    payroll_rows = (Payroll.query
                    .filter(Payroll.week_ending >= start)
                    .filter(Payroll.week_ending <= end).all())
    gross = sum(p.gross_pay or 0.0 for p in payroll_rows)

    return {
        "window_days": days, "start": start, "end": end,
        "active_workers": active,
        "hours": round(hours, 1),
        "gross": round(gross, 2),
        "verified_rate": _pct(verified, len(summaries)),
        "cost_per_hour": round(gross / hours, 2) if hours else 0.0,
    }


def full_report(days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Everything, for the reports page and the JSON endpoint."""
    return {
        "generated_at": datetime.utcnow(),
        "window_days": days,
        "headline": headline(days),
        "attendance_risk": attendance_risk(days),
        "labour_cost": labour_cost(days),
        "verification": verification_health(days),
        "hours": hours_patterns(days),
    }


# --------------------------------------------------------------------------
# 6. A single worker's own view, for the portal
# --------------------------------------------------------------------------

def worker_dashboard_extras(worker: Worker, days: int = 28) -> dict:
    """A few extra figures for the worker's home page.

    Deliberately modest. A worker opening their phone at the end of a shift
    wants four or five things they can read in a glance, not a management
    console: how this period compares with the last, what they are on course to
    earn, which day they usually work longest, and whether their record is
    fully verified. Anything more and the page stops being read at all.

    Nothing here compares them with another worker.
    """
    today = date.today()
    start = today - timedelta(days=max(1, days) - 1)
    previous_start = start - timedelta(days=days)

    def totals(day_from: date, day_to: date) -> dict:
        rows = (DailyAttendanceSummary.query
                .filter(DailyAttendanceSummary.worker_id == worker.id)
                .filter(DailyAttendanceSummary.summary_date >= day_from)
                .filter(DailyAttendanceSummary.summary_date <= day_to)
                .all())
        return {
            "days": len(rows),
            "hours": round(sum(r.total_hours or 0.0 for r in rows), 2),
            "overtime": round(sum(r.overtime_hours or 0.0 for r in rows), 2),
            "verified": sum(1 for r in rows if r.verified_by_face),
            "rows": rows,
        }

    current = totals(start, today)
    previous = totals(previous_start, start - timedelta(days=1))

    # How this period compares with the one before it. Stated as a direction and
    # a number, with no judgement attached - more hours is not automatically
    # good, and fewer is not automatically bad.
    change = None
    if previous["hours"] > 0:
        change = round(((current["hours"] - previous["hours"]) / previous["hours"]) * 100)

    # The day of the week this worker usually works longest. Farms rotate
    # people through tasks, and a worker often does not realise their own
    # pattern until it is named.
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    by_weekday: dict[int, list] = defaultdict(list)
    for row in current["rows"]:
        by_weekday[row.summary_date.weekday()].append(row.total_hours or 0.0)
    longest_day = None
    if by_weekday:
        index, values = max(by_weekday.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        if len(values) >= 2:
            longest_day = {"name": names[index],
                           "average": round(sum(values) / len(values), 1)}

    # Earnings so far in the period the worker is currently being paid for, and
    # what that is on course to come to. An estimate, and labelled as one: the
    # figure that counts is the payslip.
    period_type = payroll_engine.worker_period(worker)
    period_start, period_end = payroll_engine.period_bounds(today, period_type)
    so_far = totals(period_start, min(today, period_end))
    rate = payroll_engine.worker_rate(worker)
    earned_so_far = round(so_far["hours"] * rate, 2)

    elapsed = (min(today, period_end) - period_start).days + 1
    total_span = (period_end - period_start).days + 1
    on_course = None
    if elapsed and so_far["hours"] and elapsed < total_span:
        on_course = round((earned_so_far / elapsed) * total_span, 2)

    return {
        "window_days": days,
        "hours": current["hours"],
        "days_worked": current["days"],
        "overtime": current["overtime"],
        "change_pct": change,
        "longest_day": longest_day,
        "verified_rate": _pct(current["verified"], current["days"]),
        "unverified_days": current["days"] - current["verified"],
        # Two forms, because they read differently in a sentence. "label" is
        # the adjective the payroll page already uses ("Weekly"); "noun" is what
        # a heading needs ("This week so far"), and "This weekly so far" is not
        # English.
        "period_label": payroll_engine.PERIODS[period_type]["label"],
        "period_noun": payroll_engine.PERIODS[period_type]["noun"],
        "period_start": period_start,
        "period_end": period_end,
        "period_hours": so_far["hours"],
        "earned_so_far": earned_so_far,
        "on_course": on_course,
        "rate": rate,
    }


def worker_report(worker: Worker, days: int = 56) -> dict:
    """One worker's own trends, for the portal.

    Deliberately narrower than the farm-wide reports: a worker sees their own
    hours, their own punctuality and their own earnings, and is never shown
    where they stand against a colleague. The comparison offered is against
    their own recent average, which is the only one that is theirs to know.

    The window is longer than the farm default because a worker checking their
    own record wants to see the shape of a couple of months, not four weeks.
    """
    start, end = _window(days)

    rows = (DailyAttendanceSummary.query
            .filter(DailyAttendanceSummary.worker_id == worker.id)
            .filter(DailyAttendanceSummary.summary_date >= start)
            .filter(DailyAttendanceSummary.summary_date <= end)
            .order_by(DailyAttendanceSummary.summary_date.asc())
            .all())

    payslips = (Payroll.query
                .filter(Payroll.worker_id == worker.id)
                .filter(Payroll.paid_status == "paid")
                .filter(Payroll.week_ending >= start)
                .order_by(Payroll.week_ending.asc())
                .all())

    # Weekly buckets, labelled by the Monday of each week.
    weekly: dict[date, dict] = {}
    for row in rows:
        monday = row.summary_date - timedelta(days=row.summary_date.weekday())
        bucket = weekly.setdefault(monday, {"hours": 0.0, "overtime": 0.0, "days": 0, "late": 0})
        bucket["hours"] += row.total_hours or 0.0
        bucket["overtime"] += row.overtime_hours or 0.0
        bucket["days"] += 1
        if (row.late_minutes or 0) > 0:
            bucket["late"] += 1

    weeks = [{
        "week_of": monday,
        "label": monday.strftime("%d %b"),
        "hours": round(bucket["hours"], 2),
        "overtime": round(bucket["overtime"], 2),
        "days": bucket["days"],
        "late": bucket["late"],
    } for monday, bucket in sorted(weekly.items())]

    total_hours = round(sum(w["hours"] for w in weeks), 2)
    total_days = sum(w["days"] for w in weeks)
    late_days = sum(w["late"] for w in weeks)
    average_week = round(total_hours / len(weeks), 2) if weeks else 0.0

    # How the most recent complete week compares with this worker's own
    # average. Phrased as information, never as praise or reproach.
    trend_note = ""
    if len(weeks) >= 3:
        latest = weeks[-1]["hours"]
        earlier = [w["hours"] for w in weeks[:-1]]
        baseline = round(sum(earlier) / len(earlier), 2)
        if baseline:
            change = round(((latest - baseline) / baseline) * 100)
            if change >= 15:
                trend_note = (f"Your most recent week was {change}% above your usual "
                              f"{baseline:.0f} hours.")
            elif change <= -15:
                trend_note = (f"Your most recent week was {abs(change)}% below your usual "
                              f"{baseline:.0f} hours.")
            else:
                trend_note = f"Your hours are steady at about {baseline:.0f} a week."

    earnings = [{
        "label": row.week_ending.strftime("%d %b"),
        "net": round(row.net_pay or 0.0, 2),
        "hours": round(row.total_hours or 0.0, 2),
    } for row in payslips]

    # If this worker is late most days but only by a few minutes, the likelier
    # explanation is the farm's configured shift start, not the worker - the
    # same conclusion attendance_risk() reaches farm-wide. Saying so here keeps
    # the two views honest with each other, and stops the portal accusing
    # somebody of lateness that a setting invented.
    lateness_note = ""
    if total_days >= 5 and late_days:
        late_share = (late_days / total_days) * 100
        late_rows = [r for r in rows if (r.late_minutes or 0) > 0]
        typical = round(sum(r.late_minutes for r in late_rows) / len(late_rows)) if late_rows else 0
        if late_share >= 60 and typical <= 30:
            lateness_note = (
                f"You are marked late on most days, typically by about {typical} minutes. "
                f"When that happens to many workers at once it usually means the shift "
                f"start time on the system is set earlier than work actually begins. "
                f"Worth raising with your supervisor rather than assuming it counts "
                f"against you."
            )
        else:
            lateness_note = (
                f"You arrived after the shift start on {late_days} of {total_days} days "
                f"worked. If you think a day is recorded wrongly, show your supervisor "
                f"the date — every shift has a photo and a time attached to it."
            )

    return {
        "window_days": days, "start": start, "end": end,
        "weeks": weeks,
        "earnings": earnings,
        "lateness_note": lateness_note,
        "total_hours": total_hours,
        "total_days": total_days,
        "total_overtime": round(sum(w["overtime"] for w in weeks), 2),
        "late_days": late_days,
        "punctuality": _pct(total_days - late_days, total_days),
        "average_week": average_week,
        "total_earned": round(sum(e["net"] for e in earnings), 2),
        "trend_note": trend_note,
    }
