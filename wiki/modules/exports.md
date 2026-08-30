# `exports.py`

← [Module index](README.md) · [Wiki index](../README.md)

**~175 lines. The simplest module in the project — read it first if you want an easy start.**

---

## Why it exists

A farm's data should not be trapped inside the application. An accountant who
wants attendance in a spreadsheet, or a manager migrating to another system,
should be able to take it without assistance.

## The shape

Five functions, each returning a CSV **string**, and one dictionary that
registers them:

```python
EXPORTS = {
    "attendance":    ("attendance.csv",                attendance_csv),
    "payroll":       ("payroll.csv",                   payroll_csv),
    "daily-summary": ("daily_attendance_summary.csv",  daily_summary_csv),
    "biometric":     ("biometric_transactions.csv",    biometric_csv),
    "audit-log":     ("audit_log.csv",                 audit_csv),
}
```

One route serves all five:

```python
@app.route("/export/<string:export_key>.csv")
```

It looks the key up in `EXPORTS`, calls the function, and returns the string as
an attachment. **Adding an export needs no new route** — write the function,
register it, done. The Data Hub picks it up automatically.

```mermaid
flowchart LR
    A["GET /export/payroll.csv"] --> B["look up 'payroll' in EXPORTS"]
    B --> C["call payroll_csv()"]
    C --> D["query the models"]
    D --> E["_csv(header, rows)"]
    E --> F["download as payroll.csv"]
```

**Reading this diagram:** one route serves every export. The bit of the URL
before `.csv` is looked up in a dictionary, which hands back the function that
builds that file. Add an entry to the dictionary and a new download appears — no
new route, no new page.

## The helpers

### `_csv(header, rows)`

Builds the CSV with Python's `csv` module writing into a `StringIO`. Using the
standard library rather than joining strings with commas is what makes a worker
name containing a comma, or a note containing a newline, come out correctly.

### `_stamp(value)`

Formats a datetime consistently across every export. One function, so the date
format cannot drift between files.

### `_worker_lookup()`

Loads every worker into a dictionary once, so a hundred attendance rows do not
issue a hundred separate worker queries. This is the classic N+1 query problem,
solved in the simplest possible way.

## What each export contains

| Key | Contents |
| --- | --- |
| `attendance` | Sessions with worker, times, hours, match scores, geofence distance |
| `payroll` | Payroll rows with hours, gross, each deduction, net. **States the currency** |
| `daily-summary` | Per worker per day: hours, overtime, lateness |
| `biometric` | Every verification attempt with score, threshold and reason |
| `audit-log` | Every administrative action |

The `biometric` export is the interesting one: it includes refusals, so it is the
file to hand somebody who asks how accurate the system actually is.

## A note on privacy

These files contain personal data — names, and in the attendance export
positions and match scores. `@admin_required` on the route is the control.

**Do not add columns to an export without asking whether they belong outside the
system.** A face template must never appear in one. A PIN hash must never appear
in one.

## Gotchas

- **Exports are generated in memory.** Fine for a farm-sized dataset; a
  multi-year export on a Raspberry Pi would want streaming.
- **`tests/test_security_and_api.py` iterates `EXPORTS`** and asserts every entry
  produces a header row. Register a new export and it is covered automatically.
- **Return a string, not a `Response`.** The route handles the HTTP.

## Where to look next

- [08 — Making Your First Change](../08-making-your-first-change.md#recipe-6--add-a-csv-export)
