# The FMS Developer Wiki

Everything you need to understand this codebase, written for someone who knows
how software works in general but has never seen this project before.

**Never seen the project? Start at [01 — Start Here](01-start-here.md) and read
the numbered pages in order.** They are written as one continuous explanation,
about ninety minutes end to end. The module pages are reference material — go to
them when you need to change something specific.

---

## The guided tour

Read these in order. Each one assumes the ones before it.

| # | Page | What you will understand afterwards |
| --- | --- | --- |
| 01 | [Start Here](01-start-here.md) | What the system is for, the one idea the whole design turns on, and how to get it running |
| 02 | [The Big Picture](02-the-big-picture.md) | The four layers, the eight service modules, and what talks to what |
| 03 | [Follow a Clock-In](03-follow-a-clock-in.md) | Every step of the most important transaction, from button press to database row |
| 04 | [The Database](04-the-database.md) | All sixteen tables, how they relate, and how the schema upgrades itself |
| 05 | [Face Recognition Explained](05-face-recognition-explained.md) | How LBPH actually works, with no computer-vision background assumed |
| 06 | [Security and Roles](06-security-and-roles.md) | Who can do what, how it is enforced, and where the audit trail comes from |
| 07 | [Design Decisions](07-design-decisions.md) | Why the odd-looking parts are the way they are |
| 08 | [Making Your First Change](08-making-your-first-change.md) | Six worked recipes: add a field, a page, an endpoint, a setting, a refusal reason, a report |
| 09 | [Testing and Tools](09-testing-and-tools.md) | The 63 tests, what they cover, and the scripts in `tools/` |
| 10 | [Glossary](10-glossary.md) | Every term and abbreviation this project uses |

## Module reference

One page per source file. See [modules/README.md](modules/README.md) for the index.

| Module | One line |
| --- | --- |
| [app.py](modules/app.md) | The application factory and all 49 web routes |
| [models.py](modules/models.md) | The sixteen tables, defined once |
| [face_engine.py](modules/face_engine.md) | Enrolment, matching, and the refusal reasons |
| [attendance_service.py](modules/attendance_service.md) | The clock-in/clock-out transaction |
| [cctv_engine.py](modules/cctv_engine.md) | Cameras, streaming, clips, health checks |
| [payroll_engine.py](modules/payroll_engine.md) | Daily summaries and pay computation |
| [geofence.py](modules/geofence.md) | Distance from the farm |
| [security.py](modules/security.md) | Roles and permissions |
| [sync_engine.py](modules/sync_engine.md) | Cloud upload with an offline queue |
| [exports.py](modules/exports.md) | CSV generation |
| [api.py](modules/api.md) | The JSON API |
| [Front end](modules/frontend.md) | Templates, CSS and JavaScript |
| [Support modules](modules/support-modules.md) | `database.py`, `paths.py`, `migrations.py` |

## Other documentation

This wiki explains **the code**. These cover other things:

- [../README.md](../README.md) — project overview and feature summary
- [../INSTALL.md](../INSTALL.md) — installing on Windows, Linux, macOS, Docker
- [../manual.md](../manual.md) — the operator manual, for the people using the system
- [../FMS_PROJECT_OVERVIEW.md](../FMS_PROJECT_OVERVIEW.md) — the original technical overview

---

## A note on the diagrams

Diagrams are written as [Mermaid](https://mermaid.js.org/) code blocks. They
render automatically on GitHub, GitLab, in VS Code's Markdown preview
(`Ctrl+Shift+V`), and in Obsidian. In a plain text editor you will see the
diagram source instead, which is still readable — it is just a list of boxes and
arrows.
