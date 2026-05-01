# Farm Worker Management System (FMS)

## Overview

FMS is a Flask web application for farm workforce operations.

Key capabilities:

- Worker clock-in / clock-out using Worker ID + PIN.
- Camera photo capture on attendance events.
- Frontend geolocation capture (latitude/longitude).
- Admin panel for Workers, Users, Attendance, Audit, and grouped data operations.
- Dedicated grouped pages for CCTV, Biometric, Payroll, and Cloud Sync.

Tech stack:

- Flask
- Flask-SQLAlchemy
- SQLite
- OpenCV
- Bootstrap 5

---

## Project Structure

- `app.py`: App factory, helpers, schema updates, and all routes.
- `models.py`: SQLAlchemy models (core + Workers.sql-aligned tables).
- `database.py`: Shared SQLAlchemy instance.
- `templates/`: Jinja templates for login/admin pages.
- `static/`: CSS/JS files.
- `captures/`: Saved attendance images.
- `fms.db`: SQLite database.

---

## Current Functional Areas

### 1) Core Admin

- Dashboard
- Workers
- Attendance
- Users
- Audit Log
- Settings (organization-level settings)

### 2) Grouped Data Operations

- CCTV (`/cctv`): camera index, camera sources JSON, feed management, recordings.
- Biometric (`/biometric`): device setup and access to biometric tables.
- Payroll (`/payroll`): payroll entry and payroll records.
- Cloud Sync (`/cloud-sync`): Firebase settings, metadata, and sync queue.

### 3) Data Hub

- `/tables-hub` provides grouped launch points.
- `/tables-hub/<table_key>` provides generic table records pages.

---

## Data Model Summary

### Core tables

- `settings`: key/value system config.
- `users`: admin users, including `role` and `linked_worker_id`.
- `workers`: worker profiles including contact, NRC, enrollment, and status fields.
- `attendance`: check-in/check-out sessions including location fields.
- `audit_logs`: admin audit trail.

### Additional operational tables

- `cctv_feeds`, `cctv_recordings`, `event_snapshots`
- `biometric_devices`, `biometric_transactions`, `face_templates`
- `payroll`
- `offline_sync_queue`, `cloud_sync_metadata`
- `daily_attendance_summary`, `hardware_health_logs`

---

## Important Behavior

### Worker IDs

- Worker IDs are auto-generated as a strict 4-digit sequence: `0001`, `0002`, `0003`, ...

### Attendance capture

- Worker login captures a photo on IN/OUT events.
- Geolocation is accepted from frontend when available.
- Face/motion overlays are not required for attendance capture.

### CCTV defaults

- On startup, the app ensures a built-in default CCTV feed entry exists.
- A default marker recording row is also ensured.

### Firebase / Cloud Sync

- Firebase settings are managed from `/cloud-sync`.
- If Firebase is not configured, images stay local under `captures/`.

---

## Route Reference

### Public

- `GET/POST /` (admin + worker login)
- `GET /worker-camera-stream`
- `GET /manual`

### Admin-authenticated

- `GET /dashboard`
- `GET /workers`
- `POST /workers/add`
- `POST /workers/update`
- `POST /workers/reset-pin`
- `POST /workers/<int:worker_pk>/toggle`
- `GET /attendance`
- `GET /users`
- `POST /users/add`
- `POST /users/update`
- `POST /users/reset-password`
- `GET /audit-log`
- `GET/POST /settings`
- `GET /tables-hub`
- `GET /tables-hub/<string:table_key>`
- `GET /cctv`
- `POST /config/cctv/settings`
- `POST /config/cctv-feeds`
- `GET /biometric`
- `POST /config/biometric-devices`
- `GET /payroll`
- `POST /config/payroll`
- `GET/POST /cloud-sync`
- `GET /api/logs`
- `GET /camera-stream/<int:camera_idx>`
- `GET /captures/<path:filename>`
- `GET /logout`

---

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

App URL:

- `http://localhost:5000`

---

## Maintenance Notes

- Runtime schema adaptation is done in `app.py` via `_ensure_schema()`.
- Default built-in CCTV seed records are ensured via `_ensure_default_cctv_entries()`.
- Prefer proper migrations (Flask-Migrate/Alembic) for production environments.
