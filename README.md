# Farm Worker Management System (FMS)

## Overview
FMS is a Flask web application for:
- Worker clock-in / clock-out using Worker ID + PIN
- Camera photo capture on attendance events
- Face-required attendance validation
- Live camera streams with face/eye and motion overlays
- Worker, user, settings, and audit management from an admin panel

Tech stack:
- Flask
- Flask-SQLAlchemy
- SQLite
- OpenCV
- Bootstrap 5

---

## Project Structure
- `app.py`: Main application factory, helpers, and all routes
- `models.py`: SQLAlchemy models for settings, users, workers, attendance logs, audit logs
- `database.py`: Shared SQLAlchemy instance
- `templates/`: Jinja templates for login/admin pages
- `static/`: CSS and JS files
- `captures/`: Saved attendance images
- `fms.db`: SQLite database

---

## Database Schema

### 1) `settings`
System key-value configuration table.

Columns:
- `id` (Integer, PK)
- `key` (String(100), unique, not null)
- `value` (Text, nullable)

Common keys:
- `org_name`
- `camera_index`
- `worker_id_prefix`
- `worker_id_digits`
- `camera_sources` (JSON array string)
- `firebase_api_key`
- `firebase_bucket`
- `firebase_project_id`

### 2) `users`
Admin dashboard users.

Columns:
- `id` (Integer, PK)
- `username` (String(80), unique, not null)
- `name` (String(120), nullable)
- `email` (String(120), nullable)
- `phone` (String(30), nullable)
- `password_hash` (String(256), not null)
- `created_at` (DateTime, default UTC now)

### 3) `workers`
Worker master records.

Columns:
- `id` (Integer, PK)
- `worker_id` (String(20), unique, not null)
- `name` (String(120), not null)
- `pin_hash` (String(256), not null)
- `pin_fingerprint` (String(64), nullable, SHA-256 for uniqueness)
- `phone_number` (String(30), nullable)
- `address` (String(255), nullable)
- `emergency_contact` (String(120), nullable)
- `department` (String(80), nullable)
- `created_at` (DateTime, default UTC now)
- `is_active` (Boolean, default True)

Relationship:
- One `Worker` to many `attendance` records via `worker_id`

### 4) `attendance`
Clock-in and clock-out session records.

Columns:
- `attendance_id` (Integer, PK)
- `worker_id` (Integer, FK -> workers.id, not null)
- `check_in_time` (DateTime, default UTC now, not null)
- `check_out_time` (DateTime, nullable)
- `latitude` (Float, nullable)
- `longitude` (Float, nullable)
- `verified_by_cctv` (Boolean, default False)

### 5) `audit_logs`
System audit trail.

Columns:
- `id` (Integer, PK)
- `username` (String(80), not null)
- `action` (String(100), not null)
- `details` (Text, nullable)
- `ip_address` (String(45), nullable)
- `timestamp` (DateTime, default UTC now, not null)

---

## Core Function Inventory

### App/bootstrap
- `create_app()`: Initializes Flask, DB, schema updates, defaults, routes
- `_seed_defaults()`: Seeds default admin account and default settings
- `_ensure_schema()`: Applies lightweight schema updates for existing SQLite DBs

### Settings/helpers
- `_get_setting(key, default)`: Reads a setting row
- `_generate_password(length=8)`: Random alphanumeric password generator
- `_log_audit(action, details)`: Writes an audit log entry

### Worker/PIN helpers
- `_pin_fingerprint(pin)`: SHA-256 fingerprint used for PIN uniqueness checks
- `_is_pin_unique(pin, exclude_worker_id=None)`: Validates PIN uniqueness
- `_generate_worker_id()`: Generates next worker code using prefix+digits settings

### Camera source helpers
- `_coerce_camera_source(source_value)`: Converts numeric-like source strings to int
- `_get_camera_sources()`: Parses configured camera list or returns built-in fallback
- `_open_camera(source)`: Opens camera with platform-specific backend

### Attendance capture / media
- `_capture_photo(worker_id, require_face=False)`: Captures raw attendance photo (no overlay) and can enforce face presence
- `_upload_to_firebase(local_path)`: Optional Firebase upload, returns public URL or `None`
- `_build_attendance_sessions(raw_logs)`: Pairs IN/OUT logs into dashboard/attendance sessions

### Vision functions (live stream)
- `_detect_faces_and_eyes(frame)`: Face + eye bounding box detection
- `_draw_detections(frame, detections)`: Draws face/eye overlays on frame
- `_detect_motion_regions(prev_gray, frame)`: Movement region detection
- `_draw_motion_regions(frame, boxes)`: Draws movement overlays
- `_camera_frame_generator(source, fallback_source, overlay_faces=True, overlay_motion=True)`: MJPEG stream generator with overlays

### Auth / route registration
- `admin_required(f)`: Session-based admin auth decorator
- `_register_routes(app)`: Registers all web routes

---

## Route Reference

### Public routes
- `GET/POST /`: Login page (admin mode and worker mode)
- `GET /worker-camera-stream`: Worker preview stream (face+motion overlays)
- `GET /manual`: Manual page

### Admin-authenticated routes
- `GET /logout`
- `GET /dashboard`
- `GET/POST /workers`
- `GET /attendance`
- `POST /workers/add`
- `POST /workers/<int:worker_pk>/update`
- `POST /workers/<int:worker_pk>/reset-pin`
- `POST /workers/<int:worker_pk>/toggle`
- `POST /workers/<int:worker_pk>/delete` (deactivates worker; permanent delete disabled)
- `GET/POST /settings`
- `POST /workers/update` (flat/fallback update route)
- `POST /workers/reset-pin` (flat/fallback reset route)
- `GET /users`
- `POST /users/add`
- `POST /users/update`
- `POST /users/reset-password`
- `POST /profile/change-password`
- `GET /audit-log`
- `GET /api/logs`
- `GET /camera-stream/<int:camera_idx>`
- `GET /captures/<path:filename>`

---

## How the System Operates

### 1) Startup
1. Flask app starts via `create_app()`
2. DB tables are created if missing
3. Schema evolution runs via `_ensure_schema()`
4. Default settings and admin user are seeded
5. `captures/` directory is created if missing
6. Routes are registered

### 2) Worker Attendance Flow
1. Worker opens login page and stays on Worker tab
2. Worker sees live preview from `/worker-camera-stream`
3. Worker submits Worker ID, PIN, and action (IN/OUT)
4. System validates active worker + PIN
5. `_capture_photo(..., require_face=True)` captures frame and validates face detection
6. If no face is detected, attendance is blocked and not written
7. If capture succeeds, attendance record is created/updated in `attendance`
8. Image remains local (or is uploaded to Firebase if configured)
9. Audit entry is written for success/failure

### 3) Live Camera Dashboard Flow
1. Dashboard loads configured camera sources
2. Feed requests go to `/camera-stream/<camera_idx>`
3. `_camera_frame_generator` streams MJPEG frames
4. Stream overlays include:
   - Face/eye boxes and face status text
   - Motion boxes and movement status text

### 4) Worker Management Flow
1. Admin adds, updates, resets PIN, or toggles worker status
2. PIN uniqueness enforced via SHA-256 fingerprint
3. Delete endpoint is soft behavior (deactivate only)
4. Every action is written to `audit_logs`

### 5) User Management Flow
1. Admin can add users with generated random default passwords
2. Admin can update name/email/phone
3. Admin can reset other users' passwords
4. Any user can change own password via profile modal
5. Actions are audited

### 6) Settings Flow
1. Admin updates configuration values on settings page
2. JSON camera source validation is enforced
3. Worker ID digit limits are validated
4. Changes are committed and audited

---

## Security and Validation Notes
- Admin area protected by session check via `admin_required`
- Worker attendance requires active worker + valid PIN
- Worker attendance currently requires face detection on capture
- Audit logs track who did what and from which IP
- PINs and admin passwords are hashed (Werkzeug)

---

## Running the App
From project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Default URL:
- `http://localhost:5000`

---

## Notes for Maintenance
- This project uses lightweight runtime schema updates in `_ensure_schema()` for SQLite migrations.
- Camera behavior may differ by OS/backend; `_open_camera()` applies platform-specific backend hints.
- For production, replace ad-hoc schema updates with a migration tool (e.g., Flask-Migrate/Alembic).
