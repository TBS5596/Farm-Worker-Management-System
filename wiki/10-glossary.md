# 10 — Glossary

← [09 — Testing and Tools](09-testing-and-tools.md) · [Wiki index](README.md)

---

Every term, abbreviation and piece of project jargon, in one place.

## Project terms

**Punch** — one clock-in or one clock-out. From punch-card time clocks.
`record_punch()` handles both; `log_type` is `"IN"` or `"OUT"`.

**Session** — one work period: a clock-in and its matching clock-out. One row in
`attendance`. A session with no `check_out_time` is *open*.

**Template** — the stored numerical description of an enrolled face. 40,000
bytes: a 200×200 grayscale crop. **Not a photograph** — the original image
cannot be reconstructed from it. Lives in `face_templates.face_embedding`.

**Enrolment** — recording a worker's face templates. Done once per worker, three
or more samples. Until it happens, that worker cannot clock in.

**Enrolment reference** — the human-viewable crop saved to `captures/faces/`
alongside the template, so an operator can see what was enrolled.

**Snapshot** — the still image captured at an attendance event and stored as
evidence against that row. Row in `event_snapshots`.

**Clip** — a few seconds of video recorded around an attendance event. Row in
`cctv_recordings`.

**Score / confidence** — how well a face matched, 0–100, higher is better.
Derived from the LBPH distance as `100 − distance`.

**Threshold** — the score at or above which a match is accepted. Default 35, and
it is a setting, not a constant.

**Geofence** — the circle around the farm's registered coordinates. Distance is
always recorded; refusing outside it is optional and off by default.

**Card** — a printed identity card, optionally issued to each worker. Two sides:
the **front** carries the worker's photograph, name, ID and department; the
**back** carries the barcode, the code in readable type, and the owner's name
again in small print. Scanning it says *who is standing here* before any PIN is
typed.

**Fold / duplex** — the two ways the print sheet lays a two-sided card out.
*Fold* prints both sides side by side to be cut out as one piece and folded, and
cannot pair a barcode with the wrong photograph. *Duplex* prints fronts and backs
on alternating pages for a double-sided printer, and can, which is why every back
names its owner and the instructions tell you to check a test sheet.

**Card value** — what is actually encoded in the barcode. Depends on the
`barcode_source` setting: the NRC, a salted one-way hash of it, or a generated
`FMS-XXXX-XXXX` code. See [modules/barcode_engine.md](modules/barcode_engine.md).

**Void** — a card retired because it was lost. The status changes; the value
stays, so attendance recorded against it remains explicable.

**Keyboard wedge** — how a USB barcode scanner presents itself to a computer: as
a keyboard. It types the scanned value and presses Enter, which is why reading a
card needs no driver and no JavaScript.

**Three factors** — something the worker **has** (the card), **knows** (the PIN)
and **is** (the face). Each is independently switchable in Settings.

**Systemic lateness** — the case where most of the workforce is flagged late by a
similar small margin, which almost always means the configured shift start is
wrong rather than the workers. The Analytics page detects it and says so.

**Buddy punching** — one worker clocking in on behalf of an absent colleague.
The specific fraud this system exists to prevent.

**Ghost worker** — a name on the payroll that corresponds to nobody, or to
somebody who left.

**Refusal reason** — the machine code explaining why a punch was refused:
`no_face_detected`, `eyes_not_visible`, `worker_not_enrolled`,
`face_did_not_match`, `face_matched_another_worker`, `face_too_small`.

**Verification vs identification** — verification asks *"is this the worker
whose ID was typed?"*; identification asks *"who is this?"*. This system does
verification on the attendance path. The difference is the point of the project;
see [01 — Start Here](01-start-here.md).

**`worker_pk` vs `worker_code`** — `worker_pk` is the integer primary key
(`Worker.id`). `worker_code` is the four-digit string humans type
(`Worker.worker_id`, e.g. `"0001"`). The codebase uses these names consistently;
so should you.

## Abbreviations

| | |
| --- | --- |
| **API** | Application Programming Interface — here, the JSON endpoints under `/api/v1` |
| **CCTV** | Closed-Circuit Television |
| **CSV** | Comma-Separated Values |
| **Code 128** | The striped barcode symbology used by default. Reads fastest on a laser scanner |
| **CVD** | Colour Vision Deficiency |
| **ERD** | Entity Relationship Diagram |
| **FAR** | False Acceptance Rate — how often an impostor is wrongly accepted |
| **FRR** | False Rejection Rate — how often a genuine worker is wrongly refused |
| **HTTP** | HyperText Transfer Protocol |
| **JSON** | JavaScript Object Notation |
| **LBP** | Local Binary Pattern — the texture code |
| **LBPH** | Local Binary Patterns **Histograms** — the recognizer built from those codes |
| **MJPEG** | Motion JPEG — video as a stream of JPEG frames, which any browser renders in an `<img>` tag |
| **NAPSA** | National Pension Scheme Authority (Zambia). 10% of earnings split equally, so **5% from the employee** |
| **NHIMA** | National Health Insurance Management Authority (Zambia). **1% employee**, matched by 1% employer |
| **NRC** | National Registration Card — the Zambian national ID |
| **ORM** | Object Relational Mapper — here, SQLAlchemy: Python classes mapped to database tables |
| **PIN** | Personal Identification Number — the worker's 4-digit code |
| **QR** | Quick Response code — the square barcode. Survives a creased card better and can be read by a phone |
| **RBAC** | Role-Based Access Control |
| **RTSP** | Real Time Streaming Protocol — how IP cameras are addressed, `rtsp://…` |
| **SQL** | Structured Query Language |
| **V4L2** | Video for Linux 2 — the Linux camera capture backend |
| **ZMW** | Zambian Kwacha, the currency |

## Library and framework terms

**Flask** — the web framework. Maps URLs to Python functions.

**Application factory** — the `create_app()` pattern: a function that builds and
configures the app object, rather than doing it at module level. Makes testing
and configuration cleaner.

**Blueprint** — a Flask way of grouping routes with a shared URL prefix. `api.py`
is one, carrying `/api/v1`.

**`before_request` hook** — a function Flask runs before *every* request. This
project has one, enforcing password changes.

**Decorator** — the `@something` above a function, wrapping it in extra
behaviour. `@admin_required` and `@permission_required(...)` are the ones you
will use.

**Jinja** — the template language. `{{ value }}` inserts, `{% if %}` controls
flow, `{% block %}` is filled in by a child template.

**Flash message** — a one-off message stored in the session and displayed on the
next page. `flash("Saved.", "success")`. The category becomes the colour.

**SQLAlchemy** — the ORM. `Worker.query.filter_by(status="active").all()` instead
of writing SQL.

**Session** — two different meanings in this codebase, unfortunately. Flask's
`session` is the signed cookie holding who is signed in. A *work* session is a
clock-in/clock-out pair. Context tells them apart.

**OpenCV / `cv2`** — the computer vision library. The **contrib** build is
required, because the face recognizer lives in `cv2.face`.

**Haar cascade** — the fast face *detector*. Finds where a face is, not whose.

**Werkzeug** — the library underneath Flask; supplies the password hashing.

**pytest** — the test runner. A *fixture* is reusable setup a test asks for by
naming it as an argument.

## Configuration keys

The settings you will meet most often. All live in the `settings` table, all
stored as strings.

| Key | Default | Meaning |
| --- | --- | --- |
| `face_match_threshold` | `35` | Accept at or above this confidence |
| `face_verification_required` | `on` | Off means a PIN alone is enough — verification is bypassed |
| `face_require_eyes` | `on` | Reject a face with no detectable eyes |
| `camera_index` | `0` | Which camera is the attendance camera |
| `geofence_radius_m` | `500` | The clock-in circle, in metres |
| `geofence_enforce` | `off` | Whether distance can actually refuse a punch |
| `standard_day_hours` | `8` | Hours before overtime starts |
| `overtime_multiplier` | `1.5` | Overtime rate multiplier |
| `napsa_rate` | `0.05` | Employee pension contribution |
| `nhima_rate` | `0.01` | Employee health insurance contribution |
| `default_hourly_rate` | `15` | Used when a worker has no rate of their own |
| `clip_recording_enabled` | `on` | Record video at attendance events |
| `clip_seconds` | `6` | Clip length |

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `FMS_SECRET_KEY` | generated, cached in `.secret_key` | Signs the session cookie |
| `FMS_DATABASE_URI` | `sqlite:///fms.db` | Where the database lives |
| `FMS_HOST` | `0.0.0.0` | Bind address |
| `FMS_PORT` | `8010` | Port |
| `FMS_DEBUG` | off | **Never enable on a shared network** — the debugger allows code execution |

---

[Back to the wiki index](README.md)
