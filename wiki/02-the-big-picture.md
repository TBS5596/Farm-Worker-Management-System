# 02 — The Big Picture

← [01 — Start Here](01-start-here.md) · [Wiki index](README.md) · Next: [03 — Follow a Clock-In](03-follow-a-clock-in.md)

---

## Four layers

The code is arranged in four layers. Each layer only talks to the one below it.

```mermaid
flowchart TB
    subgraph L1["PRESENTATION - what the user sees"]
        T["templates/ - 18 Jinja HTML files"]
        CSS["static/css - 9 stylesheets"]
        JS["static/js - 13 scripts"]
    end

    subgraph L2["APPLICATION - handling requests"]
        R["app.py - 49 web routes"]
        A["api.py - 15 JSON endpoints"]
    end

    subgraph L3["SERVICE - the actual logic"]
        FE["face_engine"]
        AS["attendance_service"]
        CE["cctv_engine"]
        PE["payroll_engine"]
        GF["geofence"]
        SE["sync_engine"]
        SEC["security"]
        EX["exports"]
    end

    subgraph L4["DATA - persistence"]
        M["models.py - 16 tables"]
        MIG["migrations.py"]
        DB[("fms.db")]
    end

    subgraph HW["HARDWARE"]
        CAM["USB webcam and RTSP cameras"]
    end

    L1 --> L2
    L2 --> L3
    L3 --> L4
    L4 --> DB
    CE --> CAM
    FE --> CAM
```

Two properties of that arrangement matter, and both were chosen deliberately.

**Only two modules touch the camera.** `cctv_engine` opens it; `face_engine`
reads pixels it is handed. Nothing else in the codebase knows a camera exists.
Swap the webcam for a different device and exactly one file changes.

**The service layer's core computations are pure.** `compute_pay()` takes hours
and a rate and returns money. It does not read the database, does not look at
the current request, does not know Flask exists. That is why the test suite can
drive it through hundreds of edge cases in milliseconds. Whenever you add logic,
push it down into a function shaped like that if you possibly can.

## What each service module does

| Module | Responsibility | The one function to read first |
| --- | --- | --- |
| [`face_engine`](modules/face_engine.md) | Turn camera frames into an identity decision | `verify_worker()` |
| [`attendance_service`](modules/attendance_service.md) | Run the whole clock-in transaction in the right order | `record_punch()` |
| [`cctv_engine`](modules/cctv_engine.md) | Open cameras, stream them, record clips, check health | `grab_frames()` |
| [`payroll_engine`](modules/payroll_engine.md) | Turn attendance rows into hours, and hours into money | `compute_pay()` |
| [`geofence`](modules/geofence.md) | How far is this from the farm? | `evaluate()` |
| [`security`](modules/security.md) | May this user do this thing? | `permission_required()` |
| [`sync_engine`](modules/sync_engine.md) | Upload to the cloud, or queue it for later | `upload_or_queue()` |
| [`exports`](modules/exports.md) | Turn tables into CSV | `EXPORTS` |

## Who calls whom

This is the dependency graph. Notice that it flows one way — there are no cycles
between service modules, which is what keeps them independently testable.

```mermaid
flowchart TD
    APP["app.py<br/>web routes"]
    API["api.py<br/>JSON endpoints"]
    AS["attendance_service"]
    FE["face_engine"]
    CE["cctv_engine"]
    PE["payroll_engine"]
    GF["geofence"]
    SE["sync_engine"]
    SEC["security"]
    EX["exports"]
    MOD["models.py"]

    APP --> AS
    APP --> CE
    APP --> PE
    APP --> FE
    APP --> SEC
    APP --> EX
    APP --> SE

    API --> AS
    API --> PE
    API --> CE
    API --> FE
    API --> SE

    AS --> FE
    AS --> CE
    AS --> GF
    AS --> PE
    AS --> SE

    FE --> MOD
    CE --> MOD
    PE --> MOD
    SE --> MOD
    EX --> MOD
    AS --> MOD
```

The important edge is `app.py → attendance_service → everything else`. The
routes do not orchestrate the clock-in themselves; they hand it to one service
function. [03 — Follow a Clock-In](03-follow-a-clock-in.md) explains why that
consolidation mattered.

## How a request is actually served

Flask is a small framework, and it helps to know the four things it does with an
incoming request before your code runs.

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as Flask
    participant BR as "before_request hook"
    participant D as "Route decorators"
    participant V as "Your view function"
    participant J as "Jinja template"

    B->>F: GET /payroll
    F->>BR: _enforce_password_change()
    Note over BR: On a temporary password?<br/>Redirect to the change page.
    BR-->>F: continue
    F->>D: @admin_required, @permission_required(...)
    Note over D: Not signed in? Redirect to login.<br/>Wrong role? Refuse.
    D-->>F: continue
    F->>V: payroll()
    V->>V: call payroll_engine, query models
    V->>J: render_template("payroll.html", ...)
    J-->>B: HTML
```

**1. The application factory.** `create_app()` in `app.py` builds the Flask
object: reads config from environment variables, connects the database, runs
migrations, seeds defaults, registers the API blueprint, then registers the 49
routes. It runs once at start-up. The module ends with `app = create_app()`.

**2. The `before_request` hook.** One hook, `_enforce_password_change()`. If the
signed-in user is still on a temporary password, every request is redirected to
the change-password page except the handful needed to actually change it. A hook
rather than a check in each route, because a route added next year cannot forget
to apply a hook.

**3. Route decorators.** `@admin_required` means signed in. `@permission_required(...)`
means signed in *and* holding a named permission. See
[06 — Security and Roles](06-security-and-roles.md).

**4. The view function, then a template.** The view gathers data and calls
`render_template()`. Templates contain no business logic — they ask for a value
and display it.

## Where things are stored

```mermaid
flowchart LR
    subgraph disk["On disk"]
        DB[("fms.db<br/>all records")]
        FACES["captures/faces/<br/>enrolment reference crops"]
        SNAPS["captures/<br/>attendance snapshots"]
        CLIPS["captures/clips/<br/>event video"]
    end

    subgraph inrows["Inside the database rows"]
        TPL["face_templates.face_embedding<br/>40,000 bytes per sample"]
        PATHS["file_path columns<br/>pointing into captures/"]
    end

    TPL -.-> DB
    PATHS -.-> DB
    PATHS --> SNAPS
    PATHS --> CLIPS
```

The rule: **the database holds records and templates; the filesystem holds
images and video; rows point at files by relative path.** Relative, not
absolute, so moving the project or running it in a container does not break
every stored reference. `paths.py` is the single place those locations are
defined.

## What you can safely ignore at first

- `Workers.sql` — a generated snapshot of the schema, produced by
  `tools/export_schema.py`. `models.py` is the source of truth; this file is a
  convenience for anyone who wants to look at the schema in a SQL client.
- `BiometricDevice` in `models.py` — a table for a fingerprint scanner that was
  never bought. Nothing writes to it. It is there so a scanner could be added
  later without a schema change.
- `Worker.fingerprint_template` — same story, at the column level.
- The `correlation fallback` branch in `face_engine._predict()` — only runs when
  OpenCV is installed wrongly. If your install is correct you will never hit it.

---

Next: [03 — Follow a Clock-In](03-follow-a-clock-in.md) — the single most useful
page in this wiki.
