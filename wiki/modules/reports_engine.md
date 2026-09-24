# `reports_engine.py`

← [Module index](README.md) · [Wiki index](../README.md)

**~800 lines. Turns rows of attendance into four answers a farm manager can act on.**

---

## What it does

Everything else in this project records facts. This module is the only one that
*interprets* them.

The Attendance page says what happened. The Analytics page, which this module
feeds, says what it means — and, next to each finding, what to do about it. Four
questions, in the order a manager would ask them:

1. **Is attendance still being verified?** — because if the camera has quietly
   stopped working, every other number on the page is built on sand.
2. **Who is not coming to work?** — absence and lateness, ranked, with an action.
3. **Where is the wage bill going?** — cost by department and by worker.
4. **When is the work happening?** — hours by weekday, ordinary against overtime.

| | |
| --- | --- |
| **Owns** | Every computed figure on `/analytics` and on the worker's own `/me/reports` |
| **Depends on** | `DailyAttendanceSummary`, `Attendance`, `Payroll`, `BiometricTransaction`, `Worker`, and `payroll_engine` for the shift clock |
| **Called by** | `app.py` (`/analytics`), `portal.py` (`/me`, `/me/reports`) |
| **Never does** | Write anything. Every function is a read |

## The functions

| Function | Answers |
| --- | --- |
| `verification_health(days)` | How many sessions were face-verified, how many entered by hand, how many attempts refused and why |
| `attendance_risk(days)` | Which workers need attention, ranked, with a suggested action each |
| `labour_cost(days)` | The wage bill, split by department and by worker, with each worker's share |
| `hours_patterns(days)` | Hours by day of the week, ordinary against overtime, and average day length per department |
| `headline(days)` | The four tiles at the top of the page |
| `full_report(days)` | All of the above in one call, which is what the route uses |
| `worker_dashboard_extras(worker, days=28)` | The figures on a worker's portal home page |
| `worker_report(worker, days=56)` | A worker's own eight-week record |

## Three decisions worth understanding

### 1. Absence is measured against the farm's own rhythm, not a calendar

`attendance_risk()` does not assume a five-day week. It builds `operating_days`
from the days on which *anybody* worked, and measures each worker against that.

A farm works Saturdays, and its quiet days move with the season. More
importantly: if the rains closed the road and nobody came in on Tuesday, a fixed
calendar would indict the entire workforce for it. Measuring against what the
rest of the workforce actually did makes that Tuesday disappear from everyone's
record, which is the correct answer.

### 2. Absence and lateness are kept apart

Two different problems hide under "not coming to work", and they need different
responses, so they are never merged into a single score:

- **Absence** — the worker is not turning up at all. Severity 3 (*urgent*) when
  they have not appeared once in the window, because a name on the register with
  no attendance behind it is how a ghost worker starts, and a paper register
  hides exactly that for longest.
- **Lateness** — the worker turns up, after the shift started. Judged only once
  they have at least five days present, so a new starter's first week is not a
  pattern.

### 3. The farm-level check that runs *before* the individual ones are believed

This is the part of the module most worth reading.

```python
late_flagged = [f for f in findings if any("Late on" in n for n in f["notes"])]
if len(workers) >= 4 and len(late_flagged) >= 0.6 * len(workers):
    ...
    if typical <= 30:
        systemic = "... the shift start time is usually the problem rather than the workers."
```

When most of the workforce is flagged late by a similar small margin, the
likeliest explanation is not that most of the workforce started misbehaving at
once. It is that `shift_start_time` in Settings does not match the hour the farm
actually begins.

Saying so on the page stops a supervisor having six identical and pointless
conversations, and points at the one setting that would clear all six flags.
`worker_report()` carries the matching note on the worker's own page, so the
portal never accuses somebody of lateness that a setting invented.

**The thresholds are calibrated, not guessed.** The first version flagged seven
workers out of seven on ordinary demonstration data, which is the same as
flagging nobody. The current bands — absence below 60% for severity 2, below 75%
for severity 1; lateness on at least 60% of days across at least five days —
were set by running them against real seeded data until the output was a list
somebody would actually read.

## What the worker sees, and what they deliberately do not

`worker_report()` is narrower than the farm-wide functions on purpose.

A worker sees their own hours, their own punctuality and their own earnings, and
is never shown where they stand against a colleague. The only comparison offered
is against their **own** recent average, because that is the only comparison that
is theirs to know. Ranking workers against each other in the portal would turn a
record-keeping system into a performance-management one, which is exactly the
drift the design set out to avoid.

`worker_dashboard_extras()` adds the estimate a worker actually asks for: pay
earned so far this period, and what that is on course to become if the rest of
the period looks like the part already worked. It is labelled an estimate on the
page, and the payslip remains the figure that counts — but an honest estimate
answers the question better than silence does.

## Reading the charts

The charts are drawn by `static/js/analytics-page.js` and
`static/js/portal-reports.js` with Chart.js, served from `static/vendor/`.

Two colours carry meaning and they were checked rather than chosen by eye:
`#35946a` for ordinary hours and `#b4690e` for overtime pass a colour-blindness
separation check against each other and against both light and dark page
surfaces. A single-series chart gets no legend, because the heading above it
already names the series.

## Related pages

- [app.md](app.md) — the `/analytics` route
- [portal.md](portal.md) — `/me/reports` and the extras on `/me`
- [payroll_engine.md](payroll_engine.md) — where the summaries and pay rows come from
- [frontend.md](frontend.md) — the page templates and chart scripts
