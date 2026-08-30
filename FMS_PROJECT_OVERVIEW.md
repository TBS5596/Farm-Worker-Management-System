# Farm Worker Management System - Technical Documentation

Reference document for the implementation: architecture, modules, data model,
routes, algorithms and deployment. Written to be readable alongside the code and
usable as source material for the project report.

- **Project:** Remote Farm Worker Management System integrated with CCTV cameras
  and biometrics
- **Stack:** Flask, Flask-SQLAlchemy, SQLite, OpenCV (contrib), Bootstrap 5
- **Biometric modality:** face, via OpenCV LBPH. Camera-only - the project has no
  fingerprint scanner, and none is budgeted
- **Target hardware:** mini PC or Raspberry Pi 4 in the farm office, USB webcam at
  the clock-in point, RTSP IP cameras for surveillance

---

## 1. Executive overview

The system answers three questions with recorded evidence:

1. **Was this worker actually here?** A clock-in is accepted only when the face at
   the camera matches the samples enrolled for that Worker ID. Every attempt,
   accepted or refused, is stored with its match score.
2. **Where were they?** Each punch stores the reported coordinates and the measured
   distance from the farm centre; enforcement is optional.
3. **What are they owed?** Hours come from the recorded sessions. Gross pay,
   NAPSA, NHIMA and net pay are computed, never typed.

Everything runs on one machine with SQLite, so a dropped internet link does not
stop attendance. Cloud upload is optional and queued.

### 1.1 What changed from the first release

| Area | Before | Now |
| --- | --- | --- |
| Identity | Haar cascade confirmed *a* face was present; a PIN plus any face recorded attendance | LBPH matching against per-worker enrolled templates; a mismatch is refused |
| `face_templates` | Table existed, never written | One row per enrolled sample, with quality score and reference crop |
| `biometric_transactions` | Never written | Every verification attempt, with score, threshold and reason |
| Payroll | Every figure read from the submitted form | Hours from attendance; gross, NAPSA, NHIMA, net computed |
| `daily_attendance_summary` | Never written | Rebuilt on each punch and on demand; drives payroll and the trend chart |
| `cctv_feeds.rtsp_url` | Stored and ignored | The stream source; feeds and live views are one list |
| Recordings | One marker row, no video | mp4 clips written per attendance event and on demand |
| Geolocation | Stored, never checked | Distance from the farm centre, with optional enforcement |
| `offline_sync_queue` | Never written | Failed uploads queued and retried |
| `hardware_health_logs` | Never written | Camera probes and failures recorded |
| Roles | `users.role` stored, never enforced | Permissions enforced in the routes and reflected in the UI |
| API | None | `/api/v1`, 14 endpoints, API key auth |
| Tests | None | 63 pytest tests |
| Secret key | Regenerated every boot | From env, else cached in `.secret_key` |
| Debug server | `debug=True` on `0.0.0.0` | Off unless `FMS_DEBUG` is set |
| Default credentials | `admin`/`admin`, documented | Same, but a password change is forced before anything opens |
| Port | 6000 in code, 5000 in docs | 8010 everywhere (browsers refuse 6000: `ERR_UNSAFE_PORT`) |
| Schema source | `models.py` and a hand-written MySQL `Workers.sql` disagreed | `Workers.sql` generated from `models.py` |

---

## 2. Module map

The route layer is thin; the logic lives in focused modules. Every module,
template, stylesheet and script carries a header comment explaining its purpose,
and worked examples where the behaviour is not obvious from the code.

| File | Responsibility |
| --- | --- |
| `app.py` | App factory, seeding, routes, request guards |
| `models.py` | Schema. Single source of truth |
| `migrations.py` | Additive `ALTER TABLE ADD COLUMN` for existing databases |
| `database.py` | Shared SQLAlchemy instance |
| `paths.py` | `BASE_DIR`, `CAPTURES_DIR`, `FACES_DIR`, `CLIPS_DIR` |
| `face_engine.py` | Detection, normalisation, template storage, LBPH training, matching |
| `attendance_service.py` | The clock in/out pipeline, shared by the web page and the API |
| `cctv_engine.py` | Camera source resolution, capture, MJPEG streaming, clip recording, health |
| `payroll_engine.py` | Daily summaries, pay arithmetic, weekly generation, trend data |
| `geofence.py` | Coordinate validation and distance from the farm centre |
| `sync_engine.py` | Firebase upload, offline queue, per-record sync state |
| `security.py` | Role to permission mapping and route decorators |
| `exports.py` | CSV builders |
| `api.py` | JSON API blueprint |
| `tools/export_schema.py` | Regenerates `Workers.sql` from the models |
| `tools/seed_demo.py` | Realistic demo data |

Import direction is one-way: `app.py` and `api.py` depend on the engines; the
engines depend only on `models`, `database` and `paths`. `cctv_engine` imports
`face_engine` lazily inside a function to keep overlay drawing available without a
module cycle.

---

## 3. Runtime lifecycle

### 3.1 Entry point

```python
app = create_app()

if __name__ == "__main__":
    app.run(debug=FMS_DEBUG, host=FMS_HOST, port=FMS_PORT)   # 0.0.0.0:8010
```

### 3.2 `create_app()`

1. Resolve the secret key: `FMS_SECRET_KEY`, else a key cached in `.secret_key`
   (mode 0600), else an in-memory fallback.
2. Database URI from `FMS_DATABASE_URI`, default `sqlite:///fms.db`.
3. `MAX_CONTENT_LENGTH` 16 MB for enrolment photo uploads.
4. `db.create_all()` - creates missing tables.
5. `apply_migrations()` - adds missing columns to existing tables, logged.
6. `_seed_defaults()` - default admin, settings rows, API key, baseline feed.
7. `ensure_dirs()` - `captures/`, `captures/faces/`, `captures/clips/`.
8. Register Jinja globals `can`, `role_labels`, `face_engine_info`.
9. Register the `/api/v1` blueprint, then the page routes.

### 3.3 Seeded settings

| Key | Default | Used by |
| --- | --- | --- |
| `org_name` | FMS Farm | UI |
| `camera_index` | 0 | Built-in camera fallback |
| `camera_sources` | empty | Extra JSON-defined sources |
| `face_match_threshold` | 35 | Verification |
| `face_verification_required` | on | Verification |
| `face_require_eyes` | on | Detection quality gate |
| `farm_latitude` / `farm_longitude` | empty | Geofence |
| `geofence_radius_m` | 500 | Geofence |
| `geofence_enforce` | off | Geofence |
| `standard_day_hours` | 8 | Overtime split |
| `overtime_multiplier` | 1.5 | Pay |
| `napsa_rate` | 0.05 | Deductions |
| `nhima_rate` | 0.01 | Deductions |
| `default_hourly_rate` | 15 | Pay |
| `shift_start_time` / `shift_end_time` | 07:00 / 17:00 | Lateness, early departure |
| `clip_recording_enabled` | on | Event clips |
| `clip_seconds` | 6 | Clip length |
| `firebase_bucket` / `firebase_project_id` / `firebase_credentials_json` | empty | Cloud sync |
| `api_key` | generated | API auth |

Deduction rates are settings rather than constants because statutory rates change;
a hard-coded 5% would quietly become wrong.

### 3.4 Request guards

`before_request` blocks a signed-in user whose account still has a temporary
password: every endpoint except the password-change flow, logout, the manual and
static files redirects to `/profile/password-change`.

---

## 4. Face verification

### 4.1 Why LBPH

The available biometric is a camera. LBPH (Local Binary Patterns Histograms) ships
in `opencv-contrib-python`, trains on a handful of samples per person, runs on a
Raspberry Pi without a GPU, and returns a distance that maps cleanly onto a
threshold. Deep-learning encoders (dlib, FaceNet) are more accurate but need a
build toolchain and far more compute than the target hardware has.

If `cv2.face` is unavailable the engine falls back to a normalised-correlation
matcher so the app still runs, and says so in `engine_info()`, on the Biometric
page and on the dashboard. The fallback is measurably weaker and should not be
used to collect evaluation results.

> **Packaging trap:** `opencv-python` and `opencv-contrib-python` both provide
> `cv2`. If both are installed the plain build wins and `cv2.face` becomes an empty
> namespace, silently disabling LBPH. `requirements.txt` lists only the contrib
> build and the Dockerfile removes the plain one after install.

### 4.2 Normalisation

Every enrolled sample and every probe goes through the same steps, so the
recognizer always compares like with like:

1. Detect faces with `haarcascade_frontalface_default`, take the largest.
2. Reject a face smaller than 60 px.
3. Require at least one eye via `haarcascade_eye` (configurable). This is a cheap
   quality gate that also rejects some printed-photo attempts.
4. Crop, convert to grayscale, resize to 200x200, `equalizeHist`.
5. Quality score = Laplacian variance (blur measure), stored per sample.

### 4.3 Storage

One `face_templates` row per sample: `face_embedding` holds the raw 40 000-byte
uint8 crop, plus `algorithm`, `sample_index`, `quality_score` and a reference JPEG
under `captures/faces/`. Up to 8 samples per worker; the UI treats 3 as the
minimum for reliable matching.

### 4.4 Training and cache invalidation

The recognizer is trained lazily and cached in memory behind a re-entrant lock.
The cache key is `(row count, max face_id)`, so any enrolment or clearing forces a
retrain on next use. `face_engine.invalidate()` clears it explicitly.

### 4.5 Matching

```python
label, distance = model.predict(crop)      # LBPH: lower distance is better
confidence = max(0.0, 100.0 - distance)    # expressed so "higher is better"
matched = (label == worker_pk) and (confidence >= threshold)
```

`verify_worker()` walks the captured frames, keeps the best-scoring frame, and
returns early on the first accepted match. Its result distinguishes:

| Reason | Meaning |
| --- | --- |
| `no_face_detected` | No face in any frame |
| `eyes_not_visible` | Face found, quality gate failed |
| `face_too_small` | Worker too far from the camera |
| `worker_not_enrolled` | No samples for this worker |
| `face_did_not_match` | Best score below the threshold |
| `face_matched_another_worker` | Best match was a different enrolled worker |

The last case is the buddy-punching signal and is reported as such to the worker.

`identify()` does the same 1:N without a claimed identity, for the API.

### 4.6 Accuracy evidence

`accuracy_snapshot()` reads `biometric_transactions`: attempts, accepted,
rejected, acceptance rate and mean accepted score - shown on the dashboard and the
Biometric page, and exportable as CSV. Because every attempt is stored with its
score, threshold and reason, false accepts and false rejects can be counted
directly from the table rather than estimated.

---

## 5. The attendance pipeline

`attendance_service.record_punch(app, worker, log_type, lat, lon, frames=None)`

Order matters: identity first, because a punch that cannot be attributed should
never reach the attendance table.

1. **Camera.** `cctv_engine.grab_frames(count=8)` opens the attendance camera
   **once** and returns several frames. The first release opened the camera twice -
   once to verify, once to snapshot - which fought over a single webcam and caused
   intermittent failures. A camera failure is written to `hardware_health_logs`.
2. **Identity.** `face_engine.verify_worker(...)`. The attempt is written to
   `biometric_transactions` whether it passed or not. If verification is required
   and failed, the function returns with a plain-language message.
3. **Location.** `geofence.evaluate(lat, lon)`. Distance is always recorded; the
   punch is refused only when enforcement is on, the farm centre is configured and
   the worker is outside the radius (or sent no position).
4. **Snapshot.** The best frame is written to `captures/` with no overlays drawn
   into it. If the write fails, nothing is recorded.
5. **Attendance row.**
   - `IN`: refused if an open session already exists, else a new row with
     `verified_by_face`, `check_in_match_score`, `within_geofence`,
     `distance_from_farm_m`.
   - `OUT`: closes the most recent row with a null `check_out_time`, storing
     `check_out_match_score`; refused if there is none.
   An `EventSnapshot` is linked and `verified_by_cctv` set.
6. **Cloud.** `sync_engine.upload_or_queue(...)` - upload, or queue for retry.
7. **Clip.** `cctv_engine.record_clip(...)` in a background thread.
8. **Summary.** `payroll_engine.rebuild_day(...)` for that worker and date.

Two flags are kept deliberately separate: `verified_by_cctv` means a snapshot was
captured and linked; `verified_by_face` means the identity matched. Conflating them
was a defect in the first release.

---

## 6. Cameras, streaming and clips

### 6.1 Source resolution

`get_camera_sources()` returns, in order:

1. Active `cctv_feeds` rows with a source, primary first.
2. Extra entries from the `camera_sources` JSON setting.
3. A built-in fallback, so the list is never empty.

`coerce_source()` maps `"0"` to device index `0`, strips `builtin://`, and passes
`rtsp://...` through unchanged. `primary_source()` is what attendance uses.

### 6.2 Opening a camera

`open_camera()` picks the platform backend - V4L2 on Linux (skipping the noisy
FFMPEG fallback when `/dev/videoN` does not exist), AVFoundation on macOS, DSHOW
on Windows - then retries with no hint. `open_best_camera()` falls back to the
configured built-in index.

### 6.3 Streaming

`frame_generator()` yields multipart JPEG frames with optional face/eye and motion
overlays, and a readable "camera unavailable" frame when nothing opens. It touches
no database - it runs outside the request context, so all values are resolved
before it starts. Overlays are drawn only on the live view; saved snapshots are
clean frames.

### 6.4 Clips

`record_clip()` runs in a daemon thread: opens the source, writes mp4v frames for
N seconds into `captures/clips/`, then registers a `cctv_recordings` row with
duration, size, trigger type and the linked `attendance_id`. Event clips rather
than continuous recording is a deliberate choice - continuous capture fills a
Pi's SD card in hours, while a few seconds around a punch is what a supervisor
actually reviews.

### 6.5 Health

`probe_feed()` opens a feed, reads one frame, updates `status` and
`last_heartbeat`, and writes a `hardware_health_logs` row with the response time
or the failure reason. Exposed per camera (Test) and for all cameras (Health
Check).

---

## 7. Payroll and analytics

### 7.1 Daily summaries

`rebuild_day(worker_pk, day)` reads that worker's sessions for the day and writes
one `daily_attendance_summary` row:

- `total_hours` - sum of closed sessions only; an open session contributes zero
- `overtime_hours` - `max(0, total_hours - standard_day_hours)`
- `late_minutes` - first check-in minus `shift_start_time`, floored at zero
- `early_departure_minutes` - `shift_end_time` minus last check-out, floored at zero
- `sessions_count`, `verified_by_cctv`, `verified_by_face`

`refresh_range(from, to)` rebuilds a window; the Attendance page exposes it as
*Rebuild Daily Summaries*.

### 7.2 Pay arithmetic

`compute_pay()` is pure, so the tests can pin it down:

```
overtime_hours = min(overtime_hours, total_hours)
regular_hours  = total_hours - overtime_hours
basic_pay      = regular_hours  x rate
overtime_pay   = overtime_hours x rate x overtime_multiplier
gross_pay      = basic_pay + overtime_pay
napsa          = gross_pay x napsa_rate
nhima          = gross_pay x nhima_rate
net_pay        = gross_pay - napsa - nhima
```

Worked example - 42 hours of which 2 overtime, ZMW 20/hour, 5% and 1%:

| Item | Value |
| --- | --- |
| Regular 40 h x 20 | 800.00 |
| Overtime 2 h x 20 x 1.5 | 60.00 |
| Gross | 860.00 |
| NAPSA 5% | 43.00 |
| NHIMA 1% | 8.60 |
| **Net** | **808.40** |

All amounts are ZMW. The rates in force are stored on each payroll row
(`napsa_rate`, `nhima_rate`), so a historical payslip stays reproducible after the
settings change.

### 7.3 Weekly generation

`generate_week(week_ending)`:

1. Rebuild summaries for the seven days ending on that date.
2. For each active worker, total hours and overtime from those summaries.
3. Skip workers with no hours (counted and reported).
4. Compute pay from the worker's rate, or the default.
5. Create or update the `payroll` row - **never** if it is already `paid`.
6. Mark `computed_from_attendance` and stamp `generated_at`.

A unique constraint on `(worker_id, week_ending)` prevents duplicate weeks.
Manual rows go through the same `compute_pay()`, so a hand-entered correction still
has calculated deductions; only hours and rate are entered.

### 7.4 Trend data

`attendance_trend(days=14)` buckets summaries by date into workers present, hours
worked and face-verified counts - rendered with Chart.js on the dashboard and
served at `/api/v1/attendance/trend`.

---

## 8. Geofencing

`geofence.evaluate(lat, lon)` returns `configured`, `has_position`, `within`,
`distance_m`, `radius_m`, `enforce`. Distance is `geopy.distance.geodesic` between
the configured farm centre and the reported position.

Coordinates are self-reported by the worker's browser, so this is corroboration,
not proof - it catches a punch from the wrong side of the district, not a
determined spoof. That is why enforcement defaults to off: run it in recording
mode first, look at real distances on the Attendance page, then decide on a radius.

---

## 9. Cloud sync

Optional. Without it, everything stays local - the normal state on a remote farm.

`is_configured()` requires both a bucket and a service-account JSON. The first
release built a credential dictionary from three settings fields and omitted
`private_key`, so it could never authenticate against a real service account; the
whole JSON is now pasted in and validated for a `private_key` field on save.

- `upload_file(path)` - returns `(url, error)`; a missing configuration is
  `not_configured`, not an error the user must act on.
- `upload_or_queue(...)` - on failure, enqueues `snapshot_upload` in
  `offline_sync_queue` and marks `cloud_sync_metadata` pending; the local path is
  kept so the record is never lost.
- `drain(base_dir, limit=25)` - retries pending and failed items up to
  `MAX_RETRIES = 5`, updating snapshot `cloud_url` and per-record sync state.
- `queue_stats()` - pending, failed, synced, tracked, configured.

---

## 10. Access control

`security.py` maps roles to named permissions:

| Permission | admin | supervisor | viewer |
| --- | --- | --- | --- |
| `view` | yes | yes | yes |
| `worker.manage` | yes | yes | - |
| `attendance.manage` | yes | yes | - |
| `payroll.manage` | yes | yes | - |
| `cctv.manage` | yes | yes | - |
| `biometric.manage` | yes | yes | - |
| `sync.manage` | yes | yes | - |
| `user.manage` | yes | - | - |
| `settings.manage` | yes | - | - |

- `admin_required` - any signed-in dashboard user.
- `permission_required(perm)` - signed in **and** permitted, else a flash and a
  redirect.
- `can(perm)` is a Jinja global, so the UI hides what the role cannot do while the
  route still enforces it.

Unknown roles degrade to `viewer`. On startup any pre-existing account with an
unrecognised role is promoted to `admin` once, so nobody is locked out by the new
checks. The last active administrator cannot be demoted or deactivated.

Other hardening: passwords and PINs hashed with Werkzeug; generated passwords are
10 characters and temporary; minimum password length 8; every mutation audited
with username, action, detail and IP.

`_pin_fingerprint()` is a SHA-256 of the PIN used solely to enforce PIN uniqueness
across workers. It is not a biometric - the misleading name in the first release
caused exactly that confusion.

---

## 11. Data model

`models.py` is authoritative. `Workers.sql` is generated by
`python tools/export_schema.py`. `migrations.py` adds any missing column at
startup and never drops or renames.

### 11.1 Core

| Table | Notes |
| --- | --- |
| `settings` | Key/value configuration |
| `users` | Dashboard accounts: `role`, `is_active`, `must_change_password`, `last_login_at` |
| `workers` | Profile, `hourly_rate`, `pin_hash`, `pin_fingerprint`, `face_enrolled_at`, status |
| `attendance` | Session with `verified_by_cctv`, `verified_by_face`, `check_in_match_score`, `check_out_match_score`, `within_geofence`, `distance_from_farm_m` |
| `audit_logs` | Username, action, details, IP, timestamp |

### 11.2 Biometric

| Table | Notes |
| --- | --- |
| `face_templates` | One enrolled sample per row: crop bytes, algorithm, sample index, quality score, reference image |
| `biometric_transactions` | Every attempt: type, modality, success, `match_score`, `threshold_used`, reason |
| `biometric_devices` | Registry of cameras and terminals; `device_type` defaults to `camera` |

### 11.3 CCTV

| Table | Notes |
| --- | --- |
| `cctv_feeds` | `rtsp_url` is the live source; `is_primary` marks the attendance camera |
| `cctv_recordings` | Real clips: `attendance_id`, `trigger_type`, duration, size |
| `event_snapshots` | Photo per attendance event, with optional `cloud_url` |

### 11.4 Payroll and analytics

| Table | Notes |
| --- | --- |
| `payroll` | Hours, overtime, rate, gross, rates used, deductions, net, `computed_from_attendance`; unique per `(worker, week_ending)` |
| `daily_attendance_summary` | Per worker per day: hours, overtime, sessions, lateness, early departure, verification flags |

### 11.5 Operations

| Table | Notes |
| --- | --- |
| `offline_sync_queue` | Queued uploads with retry count and last error |
| `cloud_sync_metadata` | Per-record sync state, unique per `(table, record)` |
| `hardware_health_logs` | Device probes: status, error code, response time |

Every table is now written by the application. Nothing in the schema is decorative.

---

## 12. Route reference

### Public

| Route | Purpose |
| --- | --- |
| `GET/POST /` | Worker clock in/out and admin login |
| `GET /worker-camera-stream` | Live preview on the clock-in page |
| `GET /manual` | In-app manual |
| `GET /api/v1/health` | Service status |

### Dashboard (signed in)

`GET /dashboard`, `/workers`, `/attendance`, `/cctv`, `/biometric`, `/payroll`,
`/cloud-sync`, `/audit-log`, `/tables-hub`, `/tables-hub/<key>`, `/settings`,
`/users` (admin), `/captures/<path>`, `/camera-stream/<idx>`,
`/export/<key>.csv`, `/profile/password-change`, `/logout`

### Mutations, by permission

| Permission | Routes |
| --- | --- |
| `worker.manage` | `/workers/add`, `/workers/<pk>/update`, `/workers/<pk>/reset-pin`, `/workers/<pk>/toggle` |
| `biometric.manage` | `/workers/<pk>/face/enroll`, `/workers/<pk>/face/clear`, `/config/biometric-devices...` |
| `attendance.manage` | `/attendance/refresh-summaries` |
| `payroll.manage` | `/payroll/generate`, `/config/payroll`, `/config/payroll/<id>/update`, `/config/payroll/<id>/deactivate` |
| `cctv.manage` | `/config/cctv-feeds`, `/config/cctv-feeds/<id>/update`, `/deactivate`, `/primary`, `/test`, `/cctv/health-check`, `/cctv/record-now`, `/config/cctv/settings` |
| `sync.manage` | `POST /cloud-sync`, `/cloud-sync/drain` |
| `user.manage` | `/users`, `/users/add`, `/users/<pk>/update`, `/users/<pk>/reset-password`, `/users/<pk>/toggle` |
| `settings.manage` | `POST /settings`, `/settings/api-key/regenerate` |

### JSON API (`X-API-Key` or session)

`/api/v1/health`, `/verification/stats`, `/workers`, `/workers/<code>`,
`/attendance`, `POST /attendance/clock`, `/attendance/trend`, `/summary/daily`,
`/payroll`, `POST /payroll/generate`, `/cctv/feeds`, `/cctv/recordings`,
`/biometric/transactions`, `/sync/queue`, `POST /sync/drain`

### CSV exports

`attendance`, `payroll`, `daily-summary`, `biometric`, `audit-log`

---

## 13. Frontend

`base_admin.html` provides the shell: sidebar, sticky top bar with the role
badge, flash area and the change-password modal. Palette: `#1a4731` sidebar,
`#2e7d52` primary green, `#f4f6f9` page background. Bootstrap 5.3 and Bootstrap
Icons via CDN; DataTables for table search, sort and paging; Chart.js for the
trend chart.

### 13.1 The shell layout

The page is a two-column flexbox on `body`:

```
body (display: flex)
|-- nav.sidebar        240px, position: sticky, height: 100dvh
|   |-- .brand         fixed at the top
|   |-- .sidebar-nav   the only scrolling region
|   +-- .sidebar-footer logout, pinned to the bottom
+-- main.main-content  flex: 1, min-width: 0
```

The sidebar is **sticky, not fixed**, and only its middle section scrolls. Three
defects made that necessary, all reproduced with Playwright at real window
sizes:

1. **The nav wrapped into a hidden second column.** Bootstrap's `.nav` sets
   `flex-wrap: wrap`, so with `.flex-column` any item that did not fit wrapped
   sideways instead of overflowing downwards - inside a 240px panel, where it
   was clipped. Measured at 1470x720: six items visible, Payroll through Manual
   laid out in a second column behind them, and `scrollHeight` reporting no
   overflow at all. Fixed with `flex-wrap: nowrap` on `.sidebar-nav`.

2. **The panel overflowed a short window with no way to reach the rest.** The
   nav needed 808px while a MacBook Air offers about 720px of content height,
   and a `position: fixed` panel does not scroll with the page - so Manual and
   Logout were permanently off screen. Now the nav region scrolls on its own and
   logout sits outside it, always visible.

3. **`overflow-x: hidden` on `body`.** It was there to hide the horizontal
   overflow the old `margin-left: 240px` hack could cause, but in WebKit that
   combination can make `position: fixed` children scroll away with the content
   - the reported symptom. The flex layout needs no such hack; `min-width: 0` on
   the main column lets wide tables scroll inside their own
   `.table-responsive` wrapper instead.

Below 992px the sidebar switches back to `position: fixed`, which takes it out
of the flex flow so the main column gets the full width, and slides in as a
drawer when `static/js/admin-layout.js` puts `.sidebar-open` on the body.

Verified after the change at 1280x560, 1440x640, 1470x720, 1512x850 and
1440x900, on Dashboard, Attendance and Biometric: the panel holds at viewport
top 0 after scrolling to the bottom of the page, the brand and logout stay
visible, the nav scrolls when it needs to, and no page gains a horizontal
scrollbar.

| Template | Notes |
| --- | --- |
| `login.html` | Worker clock-in and admin tabs, live preview, geolocation capture |
| `dashboard.html` | Stat cards, Control Center, trend chart, System Readiness, live feeds |
| `workers.html` | Roster with rate and enrolment badge; quick capture button |
| `biometric.html` | Enrolment centre: live preview, per-worker samples, upload, recent attempts |
| `attendance.html` | Sessions with identity score, location badge, photos and clip links |
| `payroll.html` | Generate-from-attendance panel, computed table, correction form |
| `cctv.html` | Live feeds, feeds table with test/primary, clips, hardware health |
| `cloud_sync.html` | Queue counters, service-account JSON, drain action |
| `settings.html` | All configuration, grouped; API key panel |
| `users.html` | Accounts with role and account-state badges |
| `force_password_change.html` | The gate for temporary passwords |
| `manual.html` | In-app manual with flowcharts |
| `tables_hub.html`, `table_records.html`, `audit_log.html` | Raw table browsing and the audit trail |

Shared scripts: `components.js` (DataTables helper, delegated clicks),
`edit-modals.js` (declarative record-to-modal binding), `admin-layout.js`
(responsive sidebar), plus one script per page.

Blob columns are rendered as `<N bytes>` in the Data Hub rather than dumped, so
browsing `face_templates` does not print 40 KB of pixels per row.

---

## 14. Tests

`pytest` - 63 tests, temporary database, never touches `fms.db`.

| File | Covers |
| --- | --- |
| `test_workers.py` | Sequential 4-digit IDs, collision skipping, PIN uniqueness |
| `test_face_engine.py` | Template round trip, malformed blobs, unenrolled rejection, correct-worker matching, two-worker separation, clearing, retrain on change |
| `test_attendance.py` | Unenrolled refusal, transaction logging, session creation and snapshot, double clock-in, clock-out rules, geofence recording and enforcement, summary update |
| `test_payroll.py` | Pay arithmetic, overtime clamping, hours/lateness/overtime from sessions, open sessions, weekly generation, paid-week protection, rate fallback |
| `test_cctv_and_sync.py` | Feeds as sources, inactive exclusion, primary selection, source coercion, non-empty list, queueing on failure, drain without configuration, stats, tracking |
| `test_security_and_api.py` | Permission hierarchy, role degradation, viewer/supervisor/admin route access, anonymous redirect, temporary-password gate, API auth, clock credentials, payroll validation, exports |
| `test_real_face.py` | A real photograph: detection and normalisation, enrolment through the HTTP endpoint, acceptance for its own Worker ID, refusal when claiming another's (`face_matched_another_worker`), 1:N identification, rejection of an image with no face. Skips unless `scikit-image` is installed, which supplies the sample photograph |

Fixtures: `app_context` (fresh schema and seed per test), `client`, `setting`,
`make_worker`, `signed_in(role)`.

The real-photograph test is the one that exercises the whole claim end to end.
A measured result on the bundled photograph: three enrolled samples, a held-out
capture of the same person scores **71.8%** against a threshold of 35 and is
accepted; the same capture claiming a different enrolled worker's ID is refused
with `face_matched_another_worker`.

---

## 15. Deployment

### 15.1 Docker

`python:3.11-slim` with `ffmpeg`, `libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`,
`libxrender1`, `v4l-utils` and `curl`. Requirements installed, then plain
`opencv-python` removed so `cv2.face` survives. `captures/faces` and
`captures/clips` created. Exposes 8010. `HEALTHCHECK` polls
`/api/v1/health` every 30 s, so `docker ps` shows real health.

`docker-compose.yml` maps 8010, passes `FMS_SECRET_KEY` and `FMS_DEBUG`, persists
`fms.db` and `captures/`, restarts unless stopped, and carries a commented
`devices:` block for USB camera passthrough.

```bash
echo "FMS_SECRET_KEY=$(python -c 'import secrets;print(secrets.token_hex(32))')" > .env
docker compose up -d --build
```

### 15.2 Port choice

8010. Port 6000 is on the Chrome and Firefox blocked-port list (it is the X11
range), so `http://localhost:6000` fails with `ERR_UNSAFE_PORT` no matter what the
server does. 5000 collides with AirPlay Receiver on macOS.

### 15.3 Raspberry Pi notes

- Both `opencv-contrib-python` and the base image publish arm64 wheels.
- V4L2 is selected automatically for integer device indexes on Linux.
- Event clips instead of continuous recording keeps SD card writes down.
- Keep `captures/` on external storage if long retention is needed.

---

## 16. Design decisions worth defending

| Decision | Rationale |
| --- | --- |
| Face instead of fingerprint | No scanner exists or is budgeted; dusty hands are a known accuracy problem in field work; the hardware list already specifies a webcam |
| LBPH instead of a deep encoder | Trains on a handful of samples, runs on a Pi, no build toolchain; accuracy is adequate at a controlled clock-in point |
| Fallback matcher when contrib is missing | The app must still boot and be demonstrable; the degraded state is stated in the UI rather than hidden |
| Refuse rather than flag an unmatched punch | The problem statement is fraud. A flagged-but-recorded punch still pays a ghost worker |
| SQLite | The deployment is a single edge machine on unreliable power and network; a server database adds a failure mode with no benefit at this scale |
| Event clips, not continuous recording | Storage on a Pi is small; supervisors review the moment of the punch |
| Geofence off by default | Browser coordinates are corroboration, not proof; measure before enforcing |
| Deduction rates as settings | Statutory rates change |
| Never overwrite a paid payroll week | Re-running generation must be safe |
| Threshold as a setting | The right value depends on camera, lighting and enrolment quality at each site |

---

## 17. Known limits and future work

- **Coordinates are self-reported.** A determined worker could spoof the browser
  position. Anchoring location to the terminal, or a QR/beacon at the gate, would
  close it.
- **LBPH is illumination-sensitive.** Enrol in the conditions workers actually
  clock in under, or add a light at the terminal.
- **No liveness detection.** The eye check rejects some printed photos, not a phone
  screen. Blink or challenge-response detection would be the next step.
- **Single-machine deployment.** Multiple gates would need one instance per gate
  syncing to a central store; the offline queue is the foundation for this.
- **No mobile application.** The proposal mentions a Flutter prototype; the
  delivered client is a responsive web dashboard. The JSON API exists so a mobile
  client can be added without touching the core.
- **TAM study outstanding.** The Technology Acceptance Model evaluation in the
  proposal methodology is a research deliverable, not a code one. The system now
  produces the quantitative material it needs: verification attempts with scores,
  acceptance rates, hours recorded and payroll accuracy.
- **Continuous recording and cloud video** are deliberately out of scope for the
  target hardware.

---

## 18. Quick navigation

**Backend:** `app.py`, `models.py`, `migrations.py`, `database.py`, `paths.py`

**Engines:** `face_engine.py`, `attendance_service.py`, `cctv_engine.py`,
`payroll_engine.py`, `geofence.py`, `sync_engine.py`, `security.py`,
`exports.py`, `api.py`

**Infra:** `Dockerfile`, `docker-compose.yml`, `requirements.txt`

**Tools:** `tools/export_schema.py`, `tools/seed_demo.py`

**Docs:** `README.md`, `INSTALL.md`, `manual.md`, `FMS_PROJECT_OVERVIEW.md`

**UI:** `templates/`, `static/css/`, `static/js/`

**Tests:** `tests/`

**Data:** `fms.db`, `Workers.sql`, `captures/`
