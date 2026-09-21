# `payroll_engine.py`

← [Module index](README.md) · [Wiki index](../README.md)

**~330 lines. Turns attendance rows into hours, and hours into money.**

---

## What it owns

| | |
| --- | --- |
| **Owns** | Daily summaries, the pay calculation, weekly generation, the trend series |
| **Does not own** | Recording attendance, displaying payslips |
| **Called by** | `attendance_service` (after each punch), `app.py`, `api.py` |

## The two-stage pipeline

```mermaid
flowchart LR
    A["attendance<br/>raw sessions"] --> B["rebuild_day()"]
    B --> C["daily_attendance_summary<br/>hours per worker per day"]
    C --> D["generate_week()"]
    D --> E["payroll<br/>money per worker per week"]
```

**Reading this diagram:** raw clock-in and clock-out times go in on the left and
money comes out on the right, through two stages. The first turns times into
**hours per person per day**. The second turns those daily hours into **money per
person per week**.

> **Analogy: a shop's takings.** You do not add up every till receipt for the
> year in one go. You total each day, then add the days into a week. If one
> receipt turns out to be wrong, you re-total that one day — not the whole year.

Attendance rows are never read directly by payroll generation. Everything goes
through the summary table, which is what keeps weekly generation fast for two
hundred workers.

## Pay cycles

Four of them: **weekly**, **fortnightly**, **semi-monthly** and **monthly**. A
farm sets a default in Settings, and any individual worker can override it on
their own record — casual labour weekly and permanent staff monthly, on the same
farm, at the same time.

```mermaid
flowchart TD
    A["Which cycle is this worker on?"] --> B{"worker.payroll_period set?"}
    B -- yes --> C["Use it"]
    B -- "no (blank)" --> D["Use the farm default<br/>from Settings"]
    C --> E["period_bounds(anchor, cycle)"]
    D --> E
    E --> F["A start and an end date"]
```

**Reading this diagram:** exactly the same shape as `worker_rate()` — one
worker-level value with a farm-level fallback. One idiom to learn, not two.

### How the date you pick is read

This differs by cycle, and the difference is not arbitrary:

| Cycle | The date you pick means |
| --- | --- |
| weekly | the **last day** — a farm can end its week on any day it likes |
| fortnightly | the **last day** |
| semi-monthly | **any day inside** the half-month; bounds snap to 1–15 or 16–end |
| monthly | **any day inside** the month; bounds snap to the calendar month |

A month ends when the calendar says so, not when somebody picks a date. Snapping
also means a clerk typing the 23rd gets September, rather than an error.

### Why this was cheap to add

**The arithmetic did not change at all.** `compute_pay()` takes hours and a rate
and has no idea what period they came from, and overtime is decided **per day**
in `rebuild_day()` against the standard *day*, never against the period. A
monthly run just sums thirty days of already-correct daily overtime instead of
seven.

> **Analogy: a till roll.** The daily totals are already printed down the strip.
> Choosing a pay period is only a decision about where to tear it.

### The period is recorded on the row, not just in Settings

`Payroll` carries `period_start` and `period_type` alongside `week_ending`
(which now means *period* ending — the additive-only migration cannot rename a
column). This is not bookkeeping for its own sake: a farm that switches from
weekly to monthly still has to be able to read last year's payslips, and a list
showing `875` next to `3,400` with no labels is one a worker will read as being
short-paid.

Rows written before cycles existed are backfilled as weekly on first start-up by
`app._backfill_payroll_periods()`.

## The overlap guard

`paid_overlap()` is the money-safety check, and it is the reason this feature is
more than a dropdown.

```mermaid
flowchart TD
    A["About to write a period<br/>for this worker"] --> B{"Is this exact period<br/>already PAID?"}
    B -- yes --> S1["Skip: already_paid"]
    B -- no --> C{"Does a DIFFERENT paid period<br/>cover any of these days?"}
    C -- yes --> S2["Skip: overlap<br/>+ report the clash loudly"]
    C -- no --> W["Write the row"]
```

**Reading this diagram:** two separate questions. The first stops a settled
period being rewritten. The second stops a *different* settled period being paid
over the top of.

The case it exists for: a worker paid weekly has four settled weeks, then the
farm moves them to monthly. Generating the month would re-pay every one of those
days. Nothing else in the system would have noticed.

Only **paid** periods block — a pending row is provisional by definition. Legacy
rows with no `period_start` are treated as the weeks they were, their start
inferred as six days before their end.

## `rates()` — configuration, not constants

```python
DEFAULTS = {"standard_day_hours": 8.0, "overtime_multiplier": 1.5,
            "napsa_rate": 0.05, "nhima_rate": 0.01, ...}

def rates() -> dict:
    # reads the settings table, falling back to DEFAULTS
```

Every rate is a settings row. Statutory rates change by legislation and farms
differ; a farm should not need a developer when the pension rate is revised.

The statutory basis, so you know what the numbers mean:

| Setting | Default | Basis |
| --- | --- | --- |
| `napsa_rate` | 0.05 | NAPSA is 10% of earnings split equally, so **5% from the employee** |
| `nhima_rate` | 0.01 | NHIMA Act No. 2 of 2018: **1% employee**, matched by 1% employer |
| `standard_day_hours` | 8 | Operating convention |
| `overtime_multiplier` | 1.5 | Operating convention |

> **Not implemented:** pay-as-you-earn income tax, the NAPSA contribution
> ceiling, terminal benefits. The ceiling in particular means a high earner would
> currently be **over-deducted**. This is the most consequential outstanding item
> in the module and it should be fixed before the system pays anyone real money.

## `rebuild_day(worker_pk, day)`

Recomputes one worker's summary for one day, **from scratch**.

```python
sessions = Attendance.query.filter(...).order_by(Attendance.check_in_time.asc()).all()

if not sessions:
    if summary:
        db.session.delete(summary)     # stale summary removed
    return None
```

What it computes: total hours from **closed** sessions only, overtime as hours
beyond the standard day, first in and last out, late minutes against the shift
start, early departure minutes, session count, and whether the day was face and
CCTV verified.

**Only closed sessions contribute hours.** Somebody currently clocked in shows
`total_hours = 0` with `sessions_count = 1`; their hours appear when they clock
out. That is correct — you cannot pay for a shift that has not ended.

**Rebuild, not increment.** Deleting and recomputing is slower (about 269 ms for
a fortnight, measured) and is the right trade: if a session is corrected later,
the summary corrects itself. An incrementing counter would stay wrong forever.

## `refresh_range(day_from, day_to, worker_pk=None)`

Rebuilds every day in a range, for one worker or all. Behind the *Rebuild Daily
Summaries* button on the Attendance page — the recovery path when sessions were
imported or edited directly.

## `week_bounds(week_ending)`

A payroll week is the **seven days ending on** `week_ending`, inclusive. One
place defines it so no caller can get the arithmetic subtly wrong.

## `compute_pay(total_hours, overtime_hours, hourly_rate, config=None)`

**The most important function in the module, and it is pure.** No database, no
request context, no Flask. Give it numbers, get numbers back.

```python
overtime_hours = round(min(max(0.0, float(overtime_hours or 0.0)), total_hours), 2)
regular_hours  = round(total_hours - overtime_hours, 2)

basic_pay    = round(regular_hours * rate, 2)
overtime_pay = round(overtime_hours * rate * config["overtime_multiplier"], 2)
gross_pay    = round(basic_pay + overtime_pay, 2)
napsa        = round(gross_pay * config["napsa_rate"], 2)
nhima        = round(gross_pay * config["nhima_rate"], 2)
net_pay      = round(gross_pay - napsa - nhima, 2)
```

The worked example from the docstring — 42 hours of which 2 overtime, at ZMW
20.00/hour:

```
regular   40 h x 20.00           = 800.00
overtime   2 h x 20.00 x 1.5     =  60.00
gross                            = 860.00
NAPSA 5%                         =  43.00
NHIMA 1%                         =   8.60
net                              = 808.40
```

**Note the clamp on line 1.** `min(overtime_hours, total_hours)` — this is the
line that fixed a real defect the test suite found, where a mistyped correction
(5 hours worked, 9 of them overtime) produced an arithmetically impossible
payslip. Purity is what made that findable: the test could drive the function
directly with absurd inputs, which no amount of clicking would have produced.

**Every step rounds to 2 decimal places** as it goes, rather than once at the
end, so the components a payslip displays always add up to the total shown.

Returns all twelve components — hours, rate, basic, overtime, gross, each rate,
each deduction, net — not just `net_pay`, so a worker who queries a payment can
be shown how it was derived.

## `generate_period(anchor, period_type=None, worker_pk=None)`

```mermaid
flowchart TD
    A["generate_week(week_ending)"] --> B["for each ACTIVE worker"]
    B --> C["week_totals: sum the daily summaries"]
    C --> D["worker_rate: their rate, or the farm default"]
    D --> E["compute_pay(...)"]
    E --> F{"payroll row already<br/>exists for this week?"}
    F -- "no" --> G["INSERT"]
    F -- "yes, pending" --> H["UPDATE in place"]
    F -- "yes, PAID" --> I["SKIP - never rewrite a paid week"]
    G --> B
    H --> B
    I --> B
```

**Reading this diagram:** for each active worker, add up their daily summaries
for the week, work out the pay, then decide what to do with the result. The
three-way branch at the bottom is the important part — a brand new row is
inserted, an unpaid row is updated, and **a row already marked paid is left
completely alone**.

**Only workers on the cycle being generated are touched.** Running a monthly
period must not quietly generate for the casual labourers paid weekly, so each
worker's effective cycle is checked first. The outcome counts four separate skip
reasons — `other_cycle`, `no_hours`, `already_paid`, `overlap` — so the operator
is told what happened rather than left wondering.

`generate_week()` still exists as a thin wrapper that calls this with `"weekly"`,
so callers written before cycles existed keep working.

**A paid period is never rewritten.** Once `paid_status` is `paid`, regenerating
skips that row. Payroll is a financial record; silently changing a figure
somebody has already been paid against would destroy the audit trail.
`tests/test_payroll.py` asserts this.

Only **active** workers are included.

## `worker_rate(worker)`

The worker's own `hourly_rate`, falling back to the `default_hourly_rate`
setting. So a farm can set one rate for everyone and override per person.

## `attendance_trend(days=14)`

Daily counts for the dashboard chart. Returns labels and series ready for
Chart.js — the shaping is here rather than in the template so the API can serve
the same data.

## What it produces

Each row here is one worker for one week. Note that the hours, the rate, the
gross, both deductions and the net are all stored — not just the final figure —
so a worker who queries a payment can be shown how it was reached:

![Generated payroll showing hours, overtime, gross, NAPSA, NHIMA and net pay](../images/payroll.png)

## Gotchas

- **Summaries are derived.** Editing `daily_attendance_summary` by hand is
  pointless: the next `rebuild_day()` overwrites it. Correct the attendance row
  instead.
- **Correct a session, then rebuild.** The summary does not update itself when
  you edit attendance directly in the database.
- **`compute_pay` takes `config` explicitly.** Do not make it read settings
  itself — that would destroy its purity and the tests that depend on it.
- **The NAPSA ceiling is not implemented.** See the warning above.

## Where to look next

- [models.md](models.md) — `daily_attendance_summary` and `payroll`
- `tests/test_payroll.py` — seven tests, several of them boundary cases
