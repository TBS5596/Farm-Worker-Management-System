# Farm Worker Management System (FMS)

## Overview

FMS is a Flask web application for farm workforce and attendance operations.

Current capabilities include:

- Worker clock-in and clock-out using Worker ID + PIN.
- Face verification on clock-in (face + eye detection loop before attendance is saved).
- Clean image capture on attendance events, with optional Firebase upload.
- Frontend geolocation capture (latitude/longitude) when available.
- Live CCTV feed previews with motion and face overlays.
- Admin pages for Workers, Users, Attendance, CCTV, Biometric, Payroll, Cloud Sync, Audit Log, and Data Hub.

Tech stack:

- Flask
- Flask-SQLAlchemy
- SQLite
- OpenCV
- Bootstrap 5

---

## Project Structure

- `app.py`: app factory, business logic helpers, and routes.
- `models.py`: SQLAlchemy schema definitions.
- `database.py`: shared SQLAlchemy instance.
- `templates/`: Jinja templates.
- `static/css/`: page and shared styles.
- `static/js/`: page scripts and shared UI helpers.
- `captures/`: local attendance snapshots.
- `fms.db`: SQLite database (created via `db.create_all()`).

---

## Current Functional Areas

### Core Admin

- Dashboard (including upgraded Control Center quick actions)
- Workers
- Attendance
- Users
- Settings
- Audit Log
- Manual

### Grouped Operations

- CCTV (`/cctv`): camera settings, feed management, recording visibility.
- Biometric (`/biometric`): device setup and management.
- Payroll (`/payroll`): payroll creation and updates.
- Cloud Sync (`/cloud-sync`): Firebase settings and sync queue visibility.

### Data Hub

- `/tables-hub` for grouped navigation.
- `/tables-hub/<table_key>` for generic table browsing.

---

## Architecture Notes

### Routing Model

Edit and reset operations use parameterized routes, for example:

- `/workers/<int:worker_pk>/update`
- `/workers/<int:worker_pk>/reset-pin`
- `/users/<int:user_pk>/update`
- `/users/<int:user_pk>/reset-password`

Legacy flat routes were removed.

### Schema Initialization

- Startup uses `db.create_all()`.
- Runtime schema patching and `_ensure_schema()` were removed.

### Frontend Organization

- Inline JS/CSS was moved into `static/js` and `static/css`.
- Shared helpers are in `static/js/components.js`.
- Shared edit modal behavior is in `static/js/edit-modals.js`.

---

## Data Model Summary

### Core Tables

- `settings`: key/value system settings.
- `users`: admin users with profile fields and optional linked worker.
- `workers`: worker profile, status, PIN hash/fingerprint, enrollment and contact fields.
- `attendance`: check-in/check-out session rows with location and CCTV verification flag.
- `audit_logs`: admin activity trail.

### Operational Tables

- `cctv_feeds`, `cctv_recordings`, `event_snapshots`
- `biometric_devices`, `biometric_transactions`, `face_templates`
- `payroll`
- `offline_sync_queue`, `cloud_sync_metadata`
- `daily_attendance_summary`, `hardware_health_logs`

---

## Important Behavior

### Worker IDs

Worker IDs are auto-generated as strict 4-digit values (`0001`, `0002`, ...).

### Attendance Flow

- Clock-in requires successful face verification before attendance is created.
- Clock-out requires an existing open check-in session.
- Captured snapshots are saved as `EventSnapshot` records.
- `Attendance.verified_by_cctv` is set on successful clock-in verification.

### Live Feed

- Live camera streams include optional motion and face/eye overlay boxes.
- Snapshot capture uses clean frames (no overlays drawn into saved photo files).

### CCTV Defaults

- Built-in camera feed defaults are ensured at startup.
- A default marker recording row is maintained.

### Cloud Sync

- Firebase settings are managed in `/cloud-sync`.
- If Firebase is not configured, snapshots remain local under `captures/`.

---

## Route Reference

### Public

- `GET/POST /` (admin and worker login)
- `GET /worker-camera-stream`
- `GET /manual`

### Admin-Authenticated

- `GET /dashboard`
- `GET /workers`
- `POST /workers/add`
- `POST /workers/<int:worker_pk>/update`
- `POST /workers/<int:worker_pk>/reset-pin`
- `POST /workers/<int:worker_pk>/toggle`
- `GET /attendance`
- `GET /users`
- `POST /users/add`
- `POST /users/<int:user_pk>/update`
- `POST /users/<int:user_pk>/reset-password`
- `GET /audit-log`
- `GET/POST /settings`
- `GET /tables-hub`
- `GET /tables-hub/<string:table_key>`
- `GET /cctv`
- `POST /config/cctv/settings`
- `POST /config/cctv-feeds`
- `POST /config/cctv-feeds/<int:feed_id>/update`
- `POST /config/cctv-feeds/<int:feed_id>/deactivate`
- `GET /biometric`
- `POST /config/biometric-devices`
- `POST /config/biometric-devices/<int:device_id>/update`
- `POST /config/biometric-devices/<int:device_id>/deactivate`
- `GET /payroll`
- `POST /config/payroll`
- `POST /config/payroll/<int:payroll_id>/update`
- `POST /config/payroll/<int:payroll_id>/deactivate`
- `GET/POST /cloud-sync`
- `GET /camera-stream/<int:camera_idx>`
- `GET /captures/<path:filename>`
- `GET /logout`

---

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

App URL:

- `http://localhost:5000`

---

## Documentation

- In-app manual: `/manual`
- Markdown manual: `docs/manual.md`

The manual now includes workflow examples and flowcharts for onboarding, attendance, and edit/update operations.
