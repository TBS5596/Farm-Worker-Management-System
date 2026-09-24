# Farm Worker Management System (FMS)

A workforce and attendance system for remote commercial farms. A worker clocks
in with their Worker ID and PIN, the camera checks that the face at the terminal
is **their** enrolled face, a snapshot and a short clip are stored against the
session, and payroll is calculated from the hours that were actually recorded.

Built for the Zambian context: it runs on a mini PC or Raspberry Pi 4 in the farm
office, works without an internet connection, and queues cloud uploads until the
link comes back.

---

## What it does

**Identity, not just presence.** Each worker is enrolled with several face
samples. On clock-in the live frame is matched against that worker's enrolled
template with OpenCV's LBPH recognizer, and a punch that does not match is
refused. A PIN alone cannot record attendance, so one worker cannot clock in for
another.

**Verified attendance.** Every session stores the match score, a clean snapshot,
a short event clip, and how far the worker was from the farm when they punched.

**Payroll from the record.** Hours, overtime, gross pay, NAPSA, NHIMA and net pay
are computed from the recorded sessions and a stored hourly rate. Nothing is
typed in by hand.

**Camera-only by design.** The project has no fingerprint scanner, so the camera
is the biometric. USB webcams and RTSP IP cameras are both supported.

**Offline first.** Everything is stored locally in SQLite. If Firebase is
configured, snapshots upload as they are captured; when the link drops they are
queued and retried.

---

## Feature summary

| Area | What is included |
| --- | --- |
| Face enrolment | Camera capture or photo upload, up to 8 samples per worker, quality score per sample, clear-and-redo |
| Verification | LBPH matching with a configurable threshold, eye-visibility check, every attempt logged with its score |
| Attendance | Open-session clock in/out, snapshot per event, event clip, geofence distance, daily summaries |
| Payroll | Weekly, fortnightly, semi-monthly or monthly generation from attendance, set farm-wide and overridable per worker. Overtime, NAPSA and NHIMA at configurable rates. Paid periods protected, and an overlap guard that refuses to pay the same day twice |
| CCTV | Multiple USB and RTSP feeds, live MJPEG views with face and motion overlays, event and manual clips, camera health checks |
| Access control | Enforced roles (administrator, supervisor, viewer), forced password change on first login, full audit trail |
| Reporting | Attendance trend chart, CSV exports for attendance, payroll, summaries, verification attempts and the audit log |
| Worker portal | Self-service at `/me`: a worker signs in with their code, PIN and face to see their own details, attendance and paid payslips on their phone. Read-only, and scoped to one person |
| Integration | JSON API at `/api/v1` with an API key, for Postman testing or a future mobile client |
| Cloud | Optional Firebase Storage upload with an offline retry queue and per-record sync state |

---

## Tech stack

- Flask, Flask-SQLAlchemy, SQLite
- OpenCV (`opencv-contrib-python>=4.10,<5.0` - contrib build required, 5.x breaks detection)
- Bootstrap 5.3, Bootstrap Icons, DataTables, Chart.js
- Docker and Docker Compose for deployment
- pytest for the test suite

---

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:8010** and sign in as `admin` / `admin`. You are required
to set a real password before anything else opens.

> **Step-by-step instructions for Windows, Linux, macOS and Docker are in
> [INSTALL.md](INSTALL.md)**, including camera permissions, running it as a
> service, backups and per-platform troubleshooting. Read that instead of this
> section if you are setting up a machine for the first time.

> **New to the codebase?** The developer wiki in **[wiki/](wiki/README.md)**
> explains how everything works, with diagrams — start at
> [01 — Start Here](wiki/01-start-here.md).

> **Install from `requirements.txt`, not by hand.** Two pins in it are load
> bearing. OpenCV must be the **contrib** build, because the LBPH recognizer
> lives in `cv2.face` and ships only there. And it must stay **below 5.0**:
> OpenCV 5 dropped the bundled Haar cascade files that `face_engine.py` loads
> its face and eye detectors from, so on 5.x no face is ever detected and every
> clock-in is refused.

> **Port note:** the app listens on **8010**, set by `FMS_PORT`.
>
> - Port **6000 cannot be used at all**: Chrome and Firefox refuse it outright
>   (`ERR_UNSAFE_PORT`), so the page never loads however well the server runs.
> - **5000** collides with AirPlay Receiver on macOS, and **8000** and **8080** are
>   the ports most other projects grab first. 8010 keeps out of their way.
>
> If 8010 is taken on your machine, set `FMS_PORT=8011` (and the matching
> `ports:` line in `docker-compose.yml`).

### Optional: demo data

```bash
python tools/seed_demo.py          # 8 workers, 2 weeks of attendance, payroll
```

Useful for a demonstration or for screenshots before real data exists. Worker
PINs are `1000`, `1001`, `1002` and so on.

---

## Docker deployment

```bash
docker compose up -d --build
docker compose logs -f fms
```

Then open **http://localhost:8010**.

The database lives in `./data/fms.db` and snapshots in `./captures/`, both mounted
from the host so they survive a rebuild. (They are mounted as directories rather
than as a database file: Docker turns a bind mount of a missing file into a
directory, which SQLite cannot open.)

To carry an existing database into a Docker deployment:

```bash
mkdir -p data && cp fms.db data/fms.db
```

Two things to set for a real deployment:

1. **A stable secret key**, so a restart does not sign everyone out:
   ```bash
   echo "FMS_SECRET_KEY=$(python -c 'import secrets;print(secrets.token_hex(32))')" > .env
   ```
   Compose reads `.env` automatically.

2. **Camera passthrough**, if the clock-in terminal camera is a USB webcam on the
   host. Uncomment the `devices:` block in `docker-compose.yml`:
   ```yaml
   devices:
     - "/dev/video0:/dev/video0"
   ```
   Find the right index with `ls /dev/video*`. RTSP IP cameras need no
   passthrough - they are reached over the network.

The image installs `ffmpeg` and `v4l-utils`, so USB cameras, RTSP streams and mp4
clip writing all work inside the container. A health check polls
`/api/v1/health`, so `docker ps` shows whether the app is actually serving.

### Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `FMS_SECRET_KEY` | generated and cached in `.secret_key` | Session signing key |
| `FMS_HOST` | `0.0.0.0` | Bind address |
| `FMS_PORT` | `8010` | Port |
| `FMS_DEBUG` | off | Never enable on a shared network: the debugger allows code execution |
| `FMS_DATABASE_URI` | `sqlite:///fms.db` | Alternative database URI |

---

## Upgrading an existing database

Nothing to do by hand. On the first start, `migrations.py` compares the models
against the live tables and adds the missing columns - 28 of them for a database
created by the previous release - without dropping or renaming anything. The
change is logged, and a second start is a no-op.

Two things happen automatically to keep you from being locked out:

- An account whose role is not recognised becomes an administrator.
- If no active administrator exists at all (the previous release defaulted every
  account to `supervisor`), the account named `admin`, or else the oldest account,
  is promoted.

Existing accounts keep their current passwords; only newly created or reset
accounts are forced to change.

Existing workers have no enrolled face, so **they cannot clock in until they are
enrolled**. Enrol everyone on the Biometric page before the next shift, or switch
*Require a face match* off in Settings while you work through the list - with the
understanding that a PIN alone is then enough again.

---

## First-run checklist

1. Sign in as `admin` / `admin` and set a new password.
2. **Settings** - organisation name, farm coordinates, geofence radius, hourly
   rate defaults, NAPSA and NHIMA rates.
3. **CCTV** - register the clock-in camera, press *Test*, then the star button to
   make it the attendance camera. Add IP cameras for surveillance.
4. **Workers** - add each worker with an hourly rate and a unique PIN.
5. **Biometric** - enrol at least three face samples per worker. Nobody can
   clock in until this is done.
6. Have a worker clock in from the home page and confirm the session appears on
   **Attendance** with a match score.
7. **Payroll** - choose a week ending date and generate.

---

## Project structure

```
app.py                  Route layer and app factory
models.py               Schema - the single source of truth
migrations.py           Additive column migrations for existing databases
database.py             Shared SQLAlchemy instance
paths.py                Filesystem locations

face_engine.py          Face enrolment, LBPH training, identity matching
attendance_service.py   The clock in/out pipeline, shared by the web page and API
cctv_engine.py          Camera sources, MJPEG streaming, clip recording, health
payroll_engine.py       Daily summaries and computed payroll
geofence.py             Distance checks against the farm centre
sync_engine.py          Firebase upload with an offline retry queue
security.py             Role-based access control
exports.py              CSV exports
api.py                  JSON API blueprint (/api/v1)

templates/              Jinja templates
static/css/, static/js/ Page styles and scripts
tests/                  pytest suite
tools/export_schema.py  Regenerates Workers.sql from models.py
tools/seed_demo.py      Demo data
tools/benchmark.py      Times every operation and page, writes benchmark_results.json
tools/accuracy_experiment.py  Face verification accuracy and threshold sweep
captures/               Snapshots, enrolment references (faces/), clips (clips/)
fms.db                  SQLite database

requirements.txt        Runtime dependencies
requirements-dev.txt    Test dependencies (includes the runtime ones)
Dockerfile              Container image
docker-compose.yml      Container orchestration and volumes
INSTALL.md              Installation guide for Windows, Linux, macOS and Docker
```

---

## How verification works

```
Worker ID + PIN
      |
      v
credentials valid? ------ no ---> refused
      |
      v
open camera once, grab ~8 frames
      |
      v
detect largest face, check eyes visible, normalise to 200x200 grayscale
      |
      v
LBPH match against this worker's enrolled samples
      |
      +--> score < threshold, or matches a different worker ---> refused, logged
      |
      v
inside the geofence? (refused only if enforcement is on)
      |
      v
save clean snapshot -> create/close attendance row -> record clip
      |
      v
update the daily summary -> upload snapshot or queue it
```

Every attempt, accepted or refused, is written to `biometric_transactions` with
its score, the threshold in force and the reason. That table is the evidence base
for reporting accuracy, false accepts and false rejects.

### Tuning the threshold

Match scores are expressed as a confidence percentage where higher is better; the
default threshold is 35. Raise it if the wrong worker is ever accepted, lower it
if genuine workers are turned away. Three or more enrolled samples per worker
makes far more difference than any threshold change.

---

## JSON API

Send the key from **Settings -> API Access** as an `X-API-Key` header.

```bash
curl http://localhost:8010/api/v1/health
curl -H "X-API-Key: $KEY" http://localhost:8010/api/v1/workers
curl -H "X-API-Key: $KEY" "http://localhost:8010/api/v1/attendance?from=2026-08-01&to=2026-08-28"
curl -H "X-API-Key: $KEY" -X POST -H "Content-Type: application/json" \
     -d '{"week_ending":"2026-08-23"}' http://localhost:8010/api/v1/payroll/generate
```

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/api/v1/health` | Service, camera and recognizer status (open, no key) |
| GET | `/api/v1/workers`, `/api/v1/workers/<code>` | Worker list and detail with enrolment state |
| GET | `/api/v1/attendance` | Sessions, filterable by `from`, `to`, `worker` |
| POST | `/api/v1/attendance/clock` | Record a punch through the same verification pipeline |
| GET | `/api/v1/attendance/trend` | Daily counts for charting |
| GET | `/api/v1/summary/daily` | Daily hours, overtime and lateness |
| GET | `/api/v1/payroll` | Payroll rows, filterable by `week_ending` |
| POST | `/api/v1/payroll/generate` | Generate a week from attendance |
| GET | `/api/v1/cctv/feeds`, `/api/v1/cctv/recordings` | Cameras and stored clips |
| GET | `/api/v1/biometric/transactions` | Verification attempts |
| GET | `/api/v1/verification/stats` | Acceptance rate and average score |
| GET | `/api/v1/sync/queue`, POST `/api/v1/sync/drain` | Offline queue state and retry |

---

## Roles

| Role | Can do |
| --- | --- |
| Administrator | Everything, including users and system settings |
| Supervisor | Workers, attendance, enrolment, payroll, CCTV, cloud sync |
| Viewer | Read only |

Roles are enforced in the routes, not only hidden in the interface. New accounts
and reset passwords are temporary: the holder must set a new password before the
dashboard opens.

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

63 tests covering worker ID generation and PIN uniqueness, face template storage
and matching, the clock in/out session rules, geofence behaviour, payroll
arithmetic and weekly generation, role enforcement, the API and CSV exports. The
suite uses a temporary database and never touches `fms.db`.

Four of those tests use a real photograph - enrolling it through the actual HTTP
endpoint, then checking that the same face is accepted for its own Worker ID and
refused when it claims another worker's. They need `scikit-image`, which
`requirements-dev.txt` installs; without it those four skip automatically and
the rest of the suite still passes.

---

## Database schema

`models.py` is the single source of truth. `Workers.sql` is generated from it:

```bash
python tools/export_schema.py
```

Existing databases are upgraded automatically at startup - `migrations.py`
compares each model against the live tables and adds missing columns. It never
drops or renames anything.

### Tables

**Core:** `settings`, `users`, `workers`, `attendance`, `audit_logs`

**Biometric:** `face_templates` (one enrolled sample per row),
`biometric_transactions` (every verification attempt), `biometric_devices`

**CCTV:** `cctv_feeds`, `cctv_recordings`, `event_snapshots`

**Payroll and analytics:** `payroll`, `daily_attendance_summary`

**Operations:** `offline_sync_queue`, `cloud_sync_metadata`, `hardware_health_logs`

---

## Troubleshooting

**"Your face is not enrolled yet"** - enrol the worker on the Biometric page.
Nobody can clock in without samples.

**Genuine workers are being rejected** - add more samples (three to five, with
small changes of angle), improve the lighting, or lower the match threshold in
Settings.

**Blank camera feed** - check the source on the CCTV page and press *Test*. Close
any other application using the webcam. In Docker, confirm the `devices:` block
is uncommented and the index is right.

**"Recognizer: correlation-fallback" on the Biometric page** - `cv2.face` is
missing. Install `opencv-contrib-python`, and make sure plain `opencv-python` is
not installed alongside it: both packages provide `cv2`, and the plain one wins,
silently disabling LBPH.

**The page will not load at all** - check the port. Browsers refuse port 6000.

**The sidebar scrolls away, or Logout is off screen** - fixed in the current
version. If you are running an older copy, the shell layout in
`static/css/admin.css` is the file to update: the sidebar must be `position:
sticky` inside a flex body, with `flex-wrap: nowrap` and `overflow-y: auto` on
the nav list.

**Payroll shows nothing** - generate for a week that has attendance, and rebuild
the daily summaries from the Attendance page if sessions were imported directly.

**Everyone is signed out after a restart** - set `FMS_SECRET_KEY`.

---

## Documentation

| Document | What it covers |
| --- | --- |
| **[wiki/](wiki/README.md)** | **The developer manual.** How the code works, in plain English, with 38 diagrams and 12 annotated screenshots: a guided tour plus a page per module |
| [INSTALL.md](INSTALL.md) | Installing on Windows, Linux, macOS and Docker; services, backups, troubleshooting |
| `/manual` (in the app) | Operator manual, reachable from the sidebar while signed in |
| [manual.md](manual.md) | The same operator manual as a file, for printing |
| [FMS_PROJECT_OVERVIEW.md](FMS_PROJECT_OVERVIEW.md) | Technical documentation: architecture, modules, schema, design decisions |
| `docs/Sikapula_Natasha_2022017692_project_report.pdf` | The final year project report: methodology, design, measured results |
