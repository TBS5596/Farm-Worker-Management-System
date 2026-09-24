# Farm Worker Management System - Operator Manual

This manual is for the people who use the system day to day: the farm manager, the
supervisor at the clock-in terminal, and whoever runs payroll on Friday.

---

## 1. What the system does

A worker walks up to the terminal, types their Worker ID and PIN, and looks at the
camera. The system compares the face at the camera with the face samples enrolled
for that Worker ID. If they match, the clock-in is recorded together with a photo,
a short video clip, and the worker's distance from the farm. If they do not match,
nothing is recorded and the attempt is logged.

That single check is what makes the record trustworthy. A PIN can be shared or
guessed; a face at the camera cannot be handed to a friend. This is why enrolment
matters more than any other setup step.

At the end of each pay period, payroll reads those recorded hours and works out
the pay. Nobody types hours or amounts into a form. The farm chooses whether that
period is a week, a fortnight, half a month or a month, and individual workers can
be on different cycles.

Workers can also sign in on their own phones to see the hours recorded for them
and their payslips, which means the office is not the only place the record can
be checked.

---

## 2. Starting the system

### On a normal computer

```bash
source .venv/bin/activate
python app.py
```

### With Docker (the usual choice for the farm office machine)

```bash
docker compose up -d
```

Either way, open:

```
http://localhost:8010
```

If you are opening it from another computer on the farm network, replace
`localhost` with the office machine's address, for example
`http://192.168.1.20:8010`.

> The port must not be 6000. Chrome and Firefox refuse to open any address on
> port 6000, so the page would simply never appear.

---

## 3. First login

Username `admin`, password `admin`. The system immediately asks you to set a real
password and nothing else opens until you do. The same applies to any user account
created or reset later.

---

## 4. Setting up, in order

### 4.1 Settings

| Setting | Why it matters |
| --- | --- |
| Organisation name | Appears on the sidebar and the clock-in screen |
| Farm latitude and longitude | Needed before any distance can be measured |
| Clock-in radius | How far from the farm centre a punch is still "on site" |
| Refuse clock-ins outside the radius | Leave **off** at first, so you can see real readings before enforcing them |
| Match threshold | How strict face matching is. Start at 35 |
| Standard day, overtime multiplier | Where overtime begins and what it pays |
| Default hourly rate | Used for any worker without their own rate |
| NAPSA and NHIMA rates | Deduction percentages. Confirm the current statutory rates before a real payroll run |
| Shift start and end | Used to measure lateness and early departure |
| **Pay cycle** | How often payroll runs for the whole farm: weekly, fortnightly, twice a month or monthly. Individual workers can differ - see section 8 |
| Clip recording | Whether a short video is recorded at each punch, and how long |
| **Worker portal** | Whether workers can sign in to see their own hours and payslips, and whether that sign-in needs a face match. Leave the face check **on** - see section 15 |

### 4.2 The clock-in camera (CCTV page)

1. **Add CCTV Feed** with the camera source:
   - `builtin://0` for this machine's own camera
   - `1` for a second USB camera
   - `rtsp://user:password@192.168.1.50:554/stream1` for an IP camera
2. Press the **broadcast** button to test it. A working camera reports its
   response time; a failing one tells you so and the reason is recorded under
   Hardware Health.
3. Press the **star** button on the camera at the clock-in point. That marks it as
   the attendance camera - the one used for verification, snapshots and clips.
   Everything else is surveillance.

### 4.3 Workers

**Workers -> Add Worker.** Name, phone and a PIN are required. The Worker ID is
generated automatically (0001, 0002, ...). Set the hourly rate here; leave it
blank to use the default.

**Pay cycle** works the same way: leave it on *Farm default* for almost
everybody, and change it only for a worker paid on a different cycle from the
rest of the farm. Casual labour weekly and permanent staff monthly is a common
arrangement and is fully supported - see section 8.

### 4.4 Enrolment (the step that makes it work)

**Biometric** page:

1. Ask the worker to stand square to the camera, in even light, no hat or
   sunglasses.
2. Press the green camera button on their row. One sample is captured.
3. Repeat three to five times, with small changes of angle and expression.

The badge on their row turns green at three samples. Below three it stays amber -
matching will be unreliable.

No camera to hand? Press the upload button instead and choose clear, front-facing
photographs. Each usable photo becomes one sample.

To start over, press the red bin: all samples for that worker are deleted and they
cannot clock in until re-enrolled.

**Flow:**

```
[Add worker]
     |
     v
[Biometric page] --> [Green camera button] --> sample stored
     |                        |
     |                   repeat 3-5 times
     v
[Badge turns green]  --> worker can now clock in
```

---

## 5. Daily use: clocking in and out

The worker uses the home page - no login to the dashboard needed.

1. Enter Worker ID and PIN.
2. Choose **Clock In** or **Clock Out**.
3. Look at the camera and submit.

What the worker sees:

| Message | Meaning | What to do |
| --- | --- | --- |
| Welcome ... recorded at 07:12 (face match 74%) | Success | Nothing |
| Your face did not match the enrolled record | The face and the Worker ID disagree | Check they typed their own ID; re-enrol if a genuine worker keeps failing |
| The face at the camera belongs to a different worker | Somebody is punching for somebody else | Each worker must clock in personally |
| Your face is not enrolled yet | No samples stored | Enrol them on the Biometric page |
| No face was detected | Too far, too dark, or the camera is blocked | Move closer, improve the light |
| Your eyes were not clearly visible | Hat, sunglasses, bad angle | Remove and retry |
| You are already clocked in | An open session exists | Clock out first |
| No open check-in found | Clock-out with no clock-in | Clock in first |
| You are ... m from the farm | Outside the radius, with enforcement on | Punch on site |

**Flow:**

```
[Worker ID + PIN]
       |
       v
[Credentials checked] -- fail --> [Error shown, nothing recorded]
       |
       v
[Face matched against enrolled samples] -- fail --> [Refused and logged]
       |
       v
[Location checked] -- outside, if enforced --> [Refused]
       |
       v
[Snapshot saved] -> [Attendance recorded] -> [Clip recorded] -> [Summary updated]
```

**Workers can check their own record.** Anyone enrolled can sign in at `/me` on
their phone to see their hours and payslips, without asking the office. Section
15 covers it.

---

## 6. Checking attendance

**Attendance** page. Each row is one session:

- **Identity** - a green badge with the match score means the face matched. Grey
  "Unverified" means it was recorded without a match, which only happens if face
  verification was switched off in Settings.
- **Location** - "On site", or the distance if the worker was outside the radius.
- **Clip** - opens the short video recorded at that punch.
- **Photo** - click a thumbnail to enlarge it.

**Rebuild Daily Summaries** recalculates hours, overtime and lateness for the last
30 days. Use it if sessions were edited or imported directly.

**Export CSV** gives the whole table for a spreadsheet or a report.

---

## 7. Running payroll

**Payroll** page:

1. Choose the **pay cycle**. It already shows your farm default, so if the farm
   runs one cycle you can leave it alone.
2. Choose a **date in the period**. On weekly and fortnightly this is the last
   day of the period; on monthly and twice-a-month it can be any day inside it.
   Section 8 explains why the two behave differently.
3. Press **Generate Payroll**.

For every active worker **on that cycle**, the system totals the recorded hours
for the period, splits regular from overtime hours, applies the worker's rate,
and computes gross pay, NAPSA, NHIMA and net pay. Workers with no hours are
skipped and reported, and so are workers on a different cycle.

Periods already marked **paid** are never overwritten, so re-running is safe.

A worker whose days are already covered by a *different* paid period is skipped
with a red message naming the clash. That is the system stopping a double
payment, not an error - section 8 explains what to do about it.

To mark a week paid, press edit on the row, set status to *paid* and add the
payment date.

The rates used are shown on the page, and the source column says whether a row
came from attendance or was entered by hand. Even a hand-entered row has its pay
calculated: you enter hours and a rate, never an amount.

**Export CSV** produces the payment list. It now names the period type and both
of its dates, so a spreadsheet covering a change of cycle still reads correctly.

Once a period is marked paid, the workers on it can see their own payslip on
their phone - see section 15.

---

---

## 8. Choosing how often payroll runs

The farm can be paid weekly, fortnightly, twice a month, or monthly — and
individual workers can be on a different cycle from everybody else. Casual
labour weekly and permanent staff monthly, on the same farm, is a common
arrangement and is fully supported.

**Set the farm default** on **Settings → Pay Cycle**. Most farms set this once
and never touch it again.

**Put an individual worker on a different cycle** on the **Workers** page, in
the *Pay Cycle* box on their record. Leaving it on *Farm default* is what you
want for almost everybody.

**Running payroll.** On the Payroll page, choose the cycle and a date, then
press Generate. The cycle box already shows the farm default, so if your farm
runs one cycle you can ignore it.

How the date is read depends on the cycle, and this catches people out:

| Cycle | What the date means |
| --- | --- |
| Weekly | The **last day** of the week you are paying |
| Fortnightly | The **last day** of the fortnight |
| Twice a month | **Any day** in the half-month — it fills in 1–15 or 16 to month end |
| Monthly | **Any day** in the month — it fills in the whole month |

So on a monthly cycle you can type any date in September and get September.

**Only workers on that cycle are paid.** Running a monthly period does not
touch the weekly casuals, and the message afterwards tells you how many were
left alone for that reason.

**Two protections you cannot switch off.**

A period already marked **paid** is never regenerated, so re-running after a
correction elsewhere is always safe.

And if a worker's days are already covered by a *different* paid period, they
are skipped with a red message naming the clash. This matters when you move
somebody from weekly to monthly: without it, the first monthly run would pay
again for days already settled in their weekly payslips. **If you see that
message, nothing went wrong — the system stopped a double payment.** Mark the
old period unpaid, or generate from the date after it ends.

**Changing the cycle does not change existing payslips.** Every payslip records
the period it covered, so a worker who moved from weekly to monthly sees their
old weeks correctly labelled as weeks.

---

## 9. Cameras and recordings

The CCTV page shows every active camera live, with green boxes on detected faces
and orange boxes on movement.

- **Health Check** opens every registered camera and records whether it responded.
  Results appear under Recent Hardware Health. Run it each morning: a solar-powered
  gate camera that died overnight shows up here rather than in a missing recording.
- **Record 10s Clip** records from the attendance camera on demand.
- **Recordings** lists stored clips with their trigger, length and size. Clips are
  recorded around each punch rather than continuously, which keeps a small disk
  from filling up while still giving a supervisor something to review.

---

## 10. Users and roles

**Users** page (administrators only).

| Role | Can do |
| --- | --- |
| Administrator | Everything, including users and settings |
| Supervisor | Workers, attendance, enrolment, payroll, CCTV, cloud sync |
| Viewer | Read only |

New users get a temporary password shown once on screen; they must change it at
first login. The last active administrator cannot be demoted or deactivated, so
you cannot lock everybody out.

Every action - logins, edits, enrolments, payroll runs, refused clock-ins - is
recorded on the **Audit Log** page with the username, time and IP address.

---

## 11. Cloud sync (optional)

Without cloud sync the system is fully usable: everything is stored on the office
machine. This is the normal state on a remote farm.

To mirror snapshots to Firebase, go to **Cloud Sync** and paste the service-account
JSON from the Firebase console (Project settings -> Service accounts -> Generate
new private key) plus the storage bucket name. A partial key will not work.

Once configured, snapshots upload as they are captured. When the link drops they
are queued; **Sync Queued Items** retries them. The counters at the top of the page
show what is waiting, uploaded and failed.

---

## 12. Data Hub

**Data Hub** browses every table directly - useful for checking raw records or
pulling figures for a report. Notable tables:

| Table | What it holds |
| --- | --- |
| `biometric_transactions` | Every verification attempt with its score, threshold and reason. The source for accuracy figures |
| `face_templates` | Enrolled samples, one row per sample, with a quality score |
| `daily_attendance_summary` | Hours, overtime, lateness and early departure per worker per day |
| `hardware_health_logs` | Camera checks and failures |
| `offline_sync_queue` | Uploads waiting for the link to return |

---

## 13. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| Page will not open at all | Wrong port, or the app is not running. Use 8010; check `docker compose ps` |
| Blank camera feed | Wrong source, another app is using the camera, or the USB device is not passed into Docker |
| Everyone is rejected at clock-in | Camera not working, or no samples enrolled. Check the Biometric page |
| One genuine worker keeps being rejected | Too few samples or poor light. Add samples in the conditions they actually clock in under |
| "Recognizer: correlation-fallback" warning | `opencv-contrib-python` is missing, or plain `opencv-python` is installed alongside it and shadowing it. Reinstall from `requirements.txt` |
| Payroll generates nothing | No recorded hours for that week, or summaries need rebuilding from the Attendance page |
| Everyone signed out after a restart | `FMS_SECRET_KEY` is not set, so a new key is generated on each boot |
| Clip button shows nothing | Clip recording is off in Settings, or the camera could not be reopened. Check Hardware Health |

---

## 14. Routine

**Every morning:** CCTV -> Health Check. Confirm the attendance camera is online.

**During the day:** watch the Attendance page. Refused attempts appear on the
Biometric page with the reason.

**At the end of each pay period** - Friday on a weekly cycle, month end on a
monthly one: Payroll -> choose the cycle and a date -> Generate -> export CSV ->
mark the rows paid once they have been paid. Marking them paid is also what
releases the payslip to the worker's phone.

**If the farm runs two cycles**, run each one separately. Generating the monthly
period does not touch the weekly casuals, and vice versa.

**When a worker joins:** add them on Workers, then enrol at least three face
samples before their first shift.

**When a worker leaves:** deactivate them on Workers. Their records stay for the
audit trail, but they can no longer clock in.

---

## 15. For workers: checking your own hours and payslips

Workers can look up their own records without asking anyone. This is separate
from clocking in, and it does **not** give access to the office dashboard.

**How to get there.** On the farm WiFi, open the same address the clock-in
screen uses and tap **My hours & payslips** at the bottom, or go straight to
`/me`.

**Signing in takes three things:**

1. Your Worker ID, for example `0001`
2. Your PIN
3. A photo of your face, taken there and then

The photo is the point. Anyone who saw you type your PIN at the terminal still
cannot open your payslips, because the system checks the face against the one
enrolled for that Worker ID. If your face has not been enrolled yet, you cannot
sign in here — ask a supervisor to enrol you on the Biometric page.

**What a worker sees:**

- **Home** — whether they are clocked in right now, hours and days this week and
  this month, their own details, and their last payslip
- **Attendance** — every shift recorded for them, newest first, with the photo
  taken at clock-in
- **Payslips** — each paid week, with hours, overtime, rate, gross pay, NAPSA,
  NHIMA and net pay all shown

**What a worker cannot do.** Everything here is read-only. They cannot see any
other worker, cannot reach any office page, and cannot change a single figure.
Corrections are made by a supervisor on the dashboard.

**Why the current week is missing.** A week appears only once it has been marked
paid. Until then the figure can still change when payroll is regenerated, and
showing a number that later moves causes more disputes than it settles.

**If somebody is locked out.** Five wrong attempts in fifteen minutes locks that
Worker ID for fifteen minutes. Waiting clears it; so does a supervisor resetting
the PIN on the Workers page.

**Switching it off.** Settings has two controls: one disables the portal
entirely, and one drops sign-in to Worker ID and PIN without the face check.
Leave the face check on — it is what makes a PIN safe to use for wage history.
