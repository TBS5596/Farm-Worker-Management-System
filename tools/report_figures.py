"""Generate every figure the project report uses, so they can be regenerated.

    python tools/report_figures.py

Writes PNGs into docs/figures/. Structural diagrams use Graphviz; charts use
matplotlib. One palette throughout, matching the system's own interface, so the
report's diagrams and its screenshots read as one piece of work.
"""

import json
import os
import subprocess
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", "figures"))
os.makedirs(OUT, exist_ok=True)

# Palette shared with static/css/admin.css
INK = "#14161c"
GREEN_DARK = "#1a4731"
GREEN = "#2e7d52"
GREEN_SOFT = "#e4efe7"
BLUE = "#2f4b8f"
BLUE_SOFT = "#e3e8f5"
AMBER = "#8f5a10"
AMBER_SOFT = "#f6eedb"
RED = "#a3342b"
RED_SOFT = "#f7e3e1"
GREY = "#6d7484"
GREY_SOFT = "#eef0f4"
FONT = "Helvetica"


def render(name, dot_source, engine="dot"):
    """Write a .dot file and render it to PNG at print resolution."""
    dot_path = os.path.join(OUT, f"{name}.dot")
    png_path = os.path.join(OUT, f"{name}.png")
    with open(dot_path, "w", encoding="utf-8") as handle:
        handle.write(dot_source)
    subprocess.run([engine, "-Tpng", "-Gdpi=200", dot_path, "-o", png_path], check=True)
    os.remove(dot_path)
    print(f"  {name}.png")


HEADER = f'''
  graph [fontname="{FONT}", fontsize=11, bgcolor="white", pad=0.3];
  node  [fontname="{FONT}", fontsize=10, color="{GREY}", fontcolor="{INK}"];
  edge  [fontname="{FONT}", fontsize=9, color="{GREY}", fontcolor="{GREY}"];
'''


# ---------------------------------------------------------------------------
# 3.1 Development methodology
# ---------------------------------------------------------------------------

def fig_methodology():
    render("fig_3_1_agile_model", f'''
digraph agile {{
  rankdir=LR;
  {HEADER}
  node [shape=box, style="rounded,filled", fillcolor="{GREEN_SOFT}", color="{GREEN}", height=0.6];

  req  [label="Sprint planning\\nrequirements for\\nthis increment"];
  des  [label="Design\\nmodule and\\ndata changes"];
  bld  [label="Build\\nimplement the\\nincrement"];
  tst  [label="Test\\nautomated suite\\nplus manual check"];
  rev  [label="Sprint review\\ndemonstrate to\\nsupervisor"];
  ret  [label="Retrospective\\nadjust the\\nnext sprint"];

  req -> des -> bld -> tst -> rev -> ret;
  ret -> req [label="  next sprint (1-2 weeks)", constraint=false, style=dashed, color="{GREEN}"];

  subgraph cluster_inc {{
    label="Increments delivered";
    labelloc=b;
    fontcolor="{GREY}";
    color="{GREY_SOFT}";
    style="filled,rounded";
    fillcolor="{GREY_SOFT}";
    i1 [shape=note, fillcolor=white, color="{GREY}", label="S1  worker records\\nand admin shell"];
    i2 [shape=note, fillcolor=white, color="{GREY}", label="S2  camera streaming\\nand snapshots"];
    i3 [shape=note, fillcolor=white, color="{GREY}", label="S3  enrolment and\\nface matching"];
    i4 [shape=note, fillcolor=white, color="{GREY}", label="S4  payroll, geofence,\\nclips, API"];
    i1 -> i2 -> i3 -> i4 [style=invis];
  }}
  tst -> i1 [style=invis];
}}
''')


# ---------------------------------------------------------------------------
# 3.2 Business process, before and after
# ---------------------------------------------------------------------------

def fig_business_process():
    render("fig_3_2_business_process", f'''
digraph process {{
  rankdir=TB;
  {HEADER}
  compound=true;
  node [shape=box, style="rounded,filled", height=0.55];

  subgraph cluster_old {{
    label="Current manual process";
    fontcolor="{RED}";
    color="{RED}";
    style="rounded";
    node [fillcolor="{RED_SOFT}", color="{RED}"];
    o1 [label="Worker signs the\\npaper register"];
    o2 [label="Supervisor observes\\nwhen present"];
    o3 [label="Sheets collected\\nweekly"];
    o4 [label="Hours transcribed\\nby hand"];
    o5 [label="Payroll typed into\\na spreadsheet"];
    o1 -> o2 -> o3 -> o4 -> o5;
    o6 [shape=note, fillcolor=white, label="No way to prove who\\nsigned; buddy punching\\nand ghost workers"];
    o2 -> o6 [style=dashed, color="{RED}"];
  }}

  subgraph cluster_new {{
    label="Proposed automated process";
    fontcolor="{GREEN}";
    color="{GREEN}";
    style="rounded";
    node [fillcolor="{GREEN_SOFT}", color="{GREEN}"];
    n1 [label="Worker enters ID and PIN\\nat the terminal"];
    n2 [label="Camera matches the face\\nagainst the enrolled template"];
    n3 [label="Location measured against\\nthe farm geofence"];
    n4 [label="Snapshot and event clip\\nstored with the session"];
    n5 [label="Hours, overtime and\\ndeductions computed"];
    n6 [label="Payroll and CSV\\nready for payment"];
    n1 -> n2 -> n3 -> n4 -> n5 -> n6;
    n7 [shape=note, fillcolor=white, label="Refused and logged\\nwith the reason"];
    n2 -> n7 [label=" no match", style=dashed, color="{RED}", fontcolor="{RED}"];
  }}
}}
''')


# ---------------------------------------------------------------------------
# 3.3 High-level architecture
# ---------------------------------------------------------------------------

def fig_architecture():
    render("fig_3_3_architecture", f'''
digraph arch {{
  rankdir=TB;
  {HEADER}
  node [shape=box, style="rounded,filled", height=0.5];
  newrank=true;

  subgraph cluster_p {{
    label="Presentation layer";
    style="rounded,filled"; fillcolor="{BLUE_SOFT}"; color="{BLUE}"; fontcolor="{BLUE}";
    node [fillcolor=white, color="{BLUE}"];
    term [label="Clock-in terminal\\n(browser at the gate)"];
    dash [label="Manager dashboard\\n(Bootstrap 5, Jinja)"];
    mob  [label="Future mobile client\\n(via JSON API)", style="rounded,filled,dashed", fillcolor="{GREY_SOFT}", color="{GREY}", fontcolor="{GREY}"];
  }}

  subgraph cluster_a {{
    label="Application layer  ·  Flask";
    style="rounded,filled"; fillcolor="{GREEN_SOFT}"; color="{GREEN}"; fontcolor="{GREEN}";
    node [fillcolor=white, color="{GREEN}"];
    routes [label="Route layer\\napp.py"];
    att    [label="Attendance service\\nverification pipeline"];
    face   [label="Face engine\\nOpenCV LBPH"];
    cctv   [label="CCTV engine\\nstreams, clips, health"];
    pay    [label="Payroll engine\\nsummaries, deductions"];
    geo    [label="Geofence"];
    sec    [label="Security\\nroles, audit"];
    api    [label="JSON API\\n/api/v1"];
  }}

  subgraph cluster_d {{
    label="Data layer";
    style="rounded,filled"; fillcolor="{AMBER_SOFT}"; color="{AMBER}"; fontcolor="{AMBER}";
    node [fillcolor=white, color="{AMBER}"];
    db   [shape=cylinder, label="SQLite\\n16 tables"];
    fsys [shape=folder, label="captures/\\nsnapshots, faces, clips"];
    fb   [shape=cylinder, style="filled,dashed", color="{GREY}", fontcolor="{GREY}", label="Firebase Storage\\n(optional mirror)"];
  }}

  subgraph cluster_h {{
    label="Hardware";
    style="rounded"; color="{GREY}"; fontcolor="{GREY}";
    node [shape=box3d, fillcolor=white, color="{GREY}"];
    cam  [label="USB webcam\\n(attendance)"];
    ip   [label="IP cameras\\n(surveillance)"];
    pi   [label="Raspberry Pi 4 /\\nmini PC, solar backed"];
  }}

  term -> routes; dash -> routes; mob -> api [style=dashed];
  routes -> att; routes -> pay; routes -> cctv; routes -> sec; api -> att;
  att -> face; att -> geo; att -> cctv;
  att -> db; pay -> db; sec -> db; cctv -> db;
  att -> fsys; cctv -> fsys;
  fsys -> fb [style=dashed, label=" queued"];
  cam -> cctv [dir=back]; ip -> cctv [dir=back];
  pi -> db [style=invis];
}}
''')


# ---------------------------------------------------------------------------
# 3.4 Use case diagram
# ---------------------------------------------------------------------------

def fig_use_case():
    render("fig_3_4_use_case", f'''
digraph usecase {{
  rankdir=LR;
  {HEADER}
  node [shape=ellipse, style=filled, fillcolor=white, color="{GREEN}", fontsize=9];

  worker [shape=box, style="filled", fillcolor="{GREY_SOFT}", color="{GREY}", label="Worker"];
  sup    [shape=box, style="filled", fillcolor="{GREY_SOFT}", color="{GREY}", label="Supervisor"];
  admin  [shape=box, style="filled", fillcolor="{GREY_SOFT}", color="{GREY}", label="Administrator"];

  subgraph cluster_sys {{
    label="Remote Farm Worker Management System";
    style="rounded"; color="{GREEN}"; fontcolor="{GREEN}";
    uc1 [label="Clock in"];
    uc2 [label="Clock out"];
    uc3 [label="Verify identity\\nby face"];
    uc4 [label="Enrol worker face"];
    uc5 [label="Manage workers"];
    uc6 [label="View attendance\\nand snapshots"];
    uc7 [label="Monitor live cameras"];
    uc8 [label="Review event clips"];
    uc9 [label="Generate payroll"];
    uc10 [label="Export CSV reports"];
    uc11 [label="Run camera\\nhealth check"];
    uc12 [label="Manage users\\nand roles"];
    uc13 [label="Configure system\\nsettings"];
    uc14 [label="Review audit trail"];
    uc15 [label="Sync to cloud"];
  }}

  worker -> uc1; worker -> uc2;
  uc1 -> uc3 [label="«include»", style=dashed];
  uc2 -> uc3 [label="«include»", style=dashed];

  sup -> uc4; sup -> uc5; sup -> uc6; sup -> uc7; sup -> uc8;
  sup -> uc9; sup -> uc10; sup -> uc11; sup -> uc15;

  admin -> uc12; admin -> uc13; admin -> uc14;
  admin -> uc5 [style=dotted, label=" inherits\\n supervisor"];
}}
''')


# ---------------------------------------------------------------------------
# 3.5 Activity diagram
# ---------------------------------------------------------------------------

def fig_activity():
    render("fig_3_5_activity_clockin", f'''
digraph activity {{
  rankdir=TB;
  {HEADER}
  node [shape=box, style="rounded,filled", fillcolor=white, color="{GREEN}", height=0.45];

  start [shape=circle, label="", width=0.22, style=filled, fillcolor="{INK}", color="{INK}"];
  a1 [label="Worker enters Worker ID and PIN"];
  d1 [shape=diamond, style=filled, fillcolor="{AMBER_SOFT}", color="{AMBER}", label="Credentials\\nvalid?", height=0.8, width=1.5];
  a2 [label="Open camera once, grab 8 frames"];
  d2 [shape=diamond, style=filled, fillcolor="{AMBER_SOFT}", color="{AMBER}", label="Face detected\\nwith eyes?", height=0.8, width=1.6];
  a3 [label="Match against this worker's\\nenrolled templates (LBPH)"];
  d3 [shape=diamond, style=filled, fillcolor="{AMBER_SOFT}", color="{AMBER}", label="Score >=\\nthreshold?", height=0.8, width=1.5];
  a4 [label="Log the attempt in\\nbiometric_transactions"];
  d4 [shape=diamond, style=filled, fillcolor="{AMBER_SOFT}", color="{AMBER}", label="Inside\\ngeofence?", height=0.8, width=1.4];
  a5 [label="Save clean snapshot to captures/"];
  a6 [label="Create or close the attendance session"];
  a7 [label="Record event clip (background)"];
  a8 [label="Rebuild the daily summary"];
  a9 [label="Upload snapshot, or queue it"];
  refuse [label="Refuse and show the reason", style="rounded,filled", fillcolor="{RED_SOFT}", color="{RED}"];
  stop [shape=doublecircle, label="", width=0.22, style=filled, fillcolor="{INK}", color="{INK}"];

  start -> a1 -> d1;
  d1 -> refuse [label=" no"];
  d1 -> a2 [label=" yes"];
  a2 -> d2;
  d2 -> refuse [label=" no"];
  d2 -> a3 [label=" yes"];
  a3 -> d3;
  d3 -> a4 [label=" both\\n outcomes"];
  d3 -> refuse [label=" no"];
  d3 -> d4 [label=" yes"];
  d4 -> refuse [label=" no, if\\n enforced"];
  d4 -> a5 [label=" yes"];
  a5 -> a6 -> a7 -> a8 -> a9 -> stop;
  refuse -> stop;
  a4 -> stop [style=invis];
}}
''')


# ---------------------------------------------------------------------------
# 3.6 State diagram
# ---------------------------------------------------------------------------

def fig_state():
    render("fig_3_6_state_session", f'''
digraph state {{
  rankdir=LR;
  {HEADER}
  node [shape=box, style="rounded,filled", fillcolor="{GREEN_SOFT}", color="{GREEN}", height=0.5];

  init [shape=circle, label="", width=0.2, style=filled, fillcolor="{INK}", color="{INK}"];
  none [label="No open session"];
  open [label="Open\\ncheck_out_time NULL"];
  closed [label="Complete\\nhours computed"];
  summ [label="Summarised\\nin daily summary"];
  paid [label="Paid\\npayroll row settled", fillcolor="{BLUE_SOFT}", color="{BLUE}"];
  refused [label="Refused\\nno session created", fillcolor="{RED_SOFT}", color="{RED}"];
  fin [shape=doublecircle, label="", width=0.2, style=filled, fillcolor="{INK}", color="{INK}"];

  init -> none;
  none -> open [label=" verified clock-in"];
  none -> refused [label=" verification fails"];
  refused -> none [label=" retry"];
  open -> open [label=" second clock-in refused"];
  open -> closed [label=" verified clock-out"];
  closed -> summ [label=" summary rebuilt"];
  summ -> paid [label=" payroll generated\\n and marked paid"];
  paid -> fin;
  summ -> summ [label=" recomputed on demand"];
}}
''')


# ---------------------------------------------------------------------------
# 3.7 Class diagram
# ---------------------------------------------------------------------------

def fig_class():
    render("fig_3_7_class", f'''
digraph classes {{
  rankdir=TB;
  {HEADER}
  node [shape=record, style=filled, fillcolor=white, color="{BLUE}", fontsize=9];

  Worker [label="{{Worker|+ worker_id: str\\l+ name: str\\l+ pin_hash: str\\l+ pin_fingerprint: str\\l+ hourly_rate: float\\l+ face_enrolled_at: datetime\\l+ status: str\\l|+ set_pin(pin)\\l+ check_pin(pin): bool\\l}}"];
  FaceTemplate [label="{{FaceTemplate|+ face_embedding: bytes\\l+ algorithm: str\\l+ sample_index: int\\l+ quality_score: float\\l}}"];
  Attendance [label="{{Attendance|+ check_in_time: datetime\\l+ check_out_time: datetime\\l+ verified_by_face: bool\\l+ verified_by_cctv: bool\\l+ check_in_match_score: float\\l+ within_geofence: bool\\l+ distance_from_farm_m: float\\l}}"];
  EventSnapshot [label="{{EventSnapshot|+ snapshot_type: str\\l+ file_path: str\\l+ cloud_url: str\\l}}"];
  CCTVRecording [label="{{CCTVRecording|+ trigger_type: str\\l+ recording_path: str\\l+ duration_seconds: float\\l}}"];
  BiometricTransaction [label="{{BiometricTransaction|+ transaction_type: str\\l+ success: bool\\l+ match_score: float\\l+ threshold_used: float\\l+ error_message: str\\l}}"];
  DailySummary [label="{{DailyAttendanceSummary|+ summary_date: date\\l+ total_hours: float\\l+ overtime_hours: float\\l+ late_minutes: int\\l}}"];
  Payroll [label="{{Payroll|+ week_ending: date\\l+ total_hours: float\\l+ gross_pay: float\\l+ napsa_deduction: float\\l+ nhima_deduction: float\\l+ net_pay: float\\l+ computed_from_attendance: bool\\l}}"];
  User [label="{{User|+ username: str\\l+ role: str\\l+ is_active: bool\\l+ must_change_password: bool\\l|+ set_password(p)\\l+ check_password(p): bool\\l}}"];
  CCTVFeed [label="{{CCTVFeed|+ camera_name: str\\l+ rtsp_url: str\\l+ is_primary: bool\\l+ status: str\\l}}"];
  AuditLog [label="{{AuditLog|+ username: str\\l+ action: str\\l+ details: str\\l+ ip_address: str\\l}}"];

  Worker -> FaceTemplate [label=" 1..*", arrowhead=none];
  Worker -> Attendance [label=" 1..*", arrowhead=none];
  Worker -> BiometricTransaction [label=" 1..*", arrowhead=none];
  Worker -> DailySummary [label=" 1..*", arrowhead=none];
  Worker -> Payroll [label=" 1..*", arrowhead=none];
  Attendance -> EventSnapshot [label=" 1..2", arrowhead=none];
  Attendance -> CCTVRecording [label=" 0..*", arrowhead=none];
  CCTVFeed -> CCTVRecording [label=" 0..*", arrowhead=none];
  CCTVFeed -> EventSnapshot [label=" 0..*", arrowhead=none];
  User -> AuditLog [label=" 1..*", arrowhead=none];
  User -> Worker [label=" 0..1 linked", style=dashed, arrowhead=none];
}}
''')


# ---------------------------------------------------------------------------
# 3.9 ERD
# ---------------------------------------------------------------------------

def fig_erd():
    render("fig_3_9_erd", f'''
digraph erd {{
  rankdir=LR;
  {HEADER}
  node [shape=record, style=filled, fontsize=9];
  edge [arrowhead=crow, arrowtail=none, dir=both, arrowsize=0.7];

  workers [fillcolor="{GREEN_SOFT}", color="{GREEN}", label="{{<t>workers|PK id\\lUQ worker_id\\l   name\\lUQ nrc_number\\l   pin_hash\\l   pin_fingerprint\\l   hourly_rate\\l   face_enrolled_at\\l   status\\l}}"];
  attendance [fillcolor="{GREEN_SOFT}", color="{GREEN}", label="{{<t>attendance|PK attendance_id\\lFK worker_id\\l   check_in_time\\l   check_out_time\\l   verified_by_face\\l   verified_by_cctv\\l   check_in_match_score\\l   within_geofence\\l   distance_from_farm_m\\l}}"];
  face_templates [fillcolor="{BLUE_SOFT}", color="{BLUE}", label="{{<t>face_templates|PK face_id\\lFK worker_id\\l   face_embedding\\l   algorithm\\l   sample_index\\l   quality_score\\l}}"];
  biometric_transactions [fillcolor="{BLUE_SOFT}", color="{BLUE}", label="{{<t>biometric_transactions|PK transaction_id\\lFK worker_id\\lFK device_id\\l   transaction_type\\l   success\\l   match_score\\l   threshold_used\\l   error_message\\l}}"];
  biometric_devices [fillcolor="{BLUE_SOFT}", color="{BLUE}", label="{{<t>biometric_devices|PK device_id\\l   device_name\\lUQ device_serial\\l   device_type\\l   status\\l}}"];
  event_snapshots [fillcolor="{AMBER_SOFT}", color="{AMBER}", label="{{<t>event_snapshots|PK snapshot_id\\lFK attendance_id\\lFK camera_id\\l   snapshot_type\\l   file_path\\l   cloud_url\\l}}"];
  cctv_feeds [fillcolor="{AMBER_SOFT}", color="{AMBER}", label="{{<t>cctv_feeds|PK feed_id\\l   camera_name\\l   rtsp_url\\l   is_primary\\l   status\\l}}"];
  cctv_recordings [fillcolor="{AMBER_SOFT}", color="{AMBER}", label="{{<t>cctv_recordings|PK recording_id\\lFK camera_id\\lFK attendance_id\\l   trigger_type\\l   recording_path\\l   duration_seconds\\l}}"];
  daily [fillcolor="{GREEN_SOFT}", color="{GREEN}", label="{{<t>daily_attendance_summary|PK summary_id\\lFK worker_id\\lUQ (worker, date)\\l   total_hours\\l   overtime_hours\\l   late_minutes\\l}}"];
  payroll [fillcolor="{GREEN_SOFT}", color="{GREEN}", label="{{<t>payroll|PK payroll_id\\lFK worker_id\\lUQ (worker, week)\\l   total_hours\\l   gross_pay\\l   napsa_deduction\\l   nhima_deduction\\l   net_pay\\l}}"];
  users [fillcolor="#ede7f6", color="#6d4a9c", label="{{<t>users|PK id\\lUQ username\\l   role\\lFK linked_worker_id\\l   password_hash\\l   must_change_password\\l}}"];
  audit [fillcolor="#ede7f6", color="#6d4a9c", label="{{<t>audit_logs|PK id\\lFK user_id\\l   username\\l   action\\l   details\\l   ip_address\\l}}"];
  settings [fillcolor="{GREY_SOFT}", color="{GREY}", label="{{<t>settings|PK id\\lUQ key\\l   value\\l}}"];
  queue [fillcolor="{GREY_SOFT}", color="{GREY}", label="{{<t>offline_sync_queue|PK sync_id\\lFK worker_id\\l   operation_type\\l   payload\\l   sync_status\\l   retry_count\\l}}"];
  meta [fillcolor="{GREY_SOFT}", color="{GREY}", label="{{<t>cloud_sync_metadata|PK sync_id\\lUQ (table, record)\\l   cloud_status\\l   cloud_record_id\\l}}"];
  health [fillcolor="{GREY_SOFT}", color="{GREY}", label="{{<t>hardware_health_logs|PK log_id\\l   device_type\\l   device_id\\l   status\\l   error_code\\l   response_time_ms\\l}}"];

  workers -> attendance;
  workers -> face_templates;
  workers -> biometric_transactions;
  workers -> daily;
  workers -> payroll;
  workers -> queue;
  biometric_devices -> biometric_transactions;
  attendance -> event_snapshots;
  attendance -> cctv_recordings;
  cctv_feeds -> cctv_recordings;
  cctv_feeds -> event_snapshots;
  users -> audit;
  workers -> users [style=dashed, arrowhead=none, label=" 0..1"];
  settings -> health [style=invis];
  meta -> queue [style=invis];
}}
''')


# ---------------------------------------------------------------------------
# 3.10 Component and deployment
# ---------------------------------------------------------------------------

def fig_deployment():
    render("fig_3_10_deployment", f'''
digraph deploy {{
  rankdir=TB;
  {HEADER}
  node [shape=box, style="rounded,filled", height=0.5];

  subgraph cluster_farm {{
    label="Farm site  ·  local network, solar-backed";
    style="rounded"; color="{GREEN}"; fontcolor="{GREEN}";

    subgraph cluster_host {{
      label="Office host  ·  Raspberry Pi 4 or mini PC  ·  Docker";
      style="rounded,filled"; fillcolor="{GREEN_SOFT}"; color="{GREEN}"; fontcolor="{GREEN}";
      node [fillcolor=white, color="{GREEN}"];
      cont [shape=component, label="fms-app container\\nPython 3.11, Flask, OpenCV contrib\\nport 8010"];
      vol1 [shape=folder, label="./data\\nfms.db"];
      vol2 [shape=folder, label="./captures\\nsnapshots · faces · clips"];
      cont -> vol1 [label=" bind mount"];
      cont -> vol2 [label=" bind mount"];
    }}

    node [fillcolor=white, color="{GREY}"];
    gate [shape=box3d, label="Clock-in terminal\\nbrowser + USB webcam"];
    cam1 [shape=box3d, label="IP camera\\nnorth gate"];
    cam2 [shape=box3d, label="IP camera\\npackhouse"];
    sw   [shape=box3d, label="Router / switch"];
    mgr  [shape=box3d, label="Manager laptop\\nor phone"];

    gate -> sw; cam1 -> sw; cam2 -> sw; mgr -> sw;
    sw -> cont [label=" HTTP 8010 / RTSP 554"];
  }}

  subgraph cluster_cloud {{
    label="Optional, when the link is up";
    style="rounded,dashed"; color="{GREY}"; fontcolor="{GREY}";
    node [fillcolor=white, color="{GREY}", fontcolor="{GREY}"];
    fb [shape=cylinder, label="Firebase Storage\\nsnapshot mirror"];
  }}

  cont -> fb [style=dashed, label=" queued upload, retried"];
}}
''')


# ---------------------------------------------------------------------------
# 3.11 Security design
# ---------------------------------------------------------------------------

def fig_security():
    render("fig_3_11_security", f'''
digraph security {{
  rankdir=LR;
  {HEADER}
  node [shape=box, style="rounded,filled", height=0.5];

  subgraph cluster_id {{
    label="Identity and access";
    style="rounded,filled"; fillcolor="{BLUE_SOFT}"; color="{BLUE}"; fontcolor="{BLUE}";
    node [fillcolor=white, color="{BLUE}"];
    s1 [label="Passwords and PINs\\nhashed with scrypt"];
    s2 [label="Forced change of\\ntemporary passwords"];
    s3 [label="Role permissions\\nenforced in routes"];
    s4 [label="API key for /api/v1"];
  }}

  subgraph cluster_bio {{
    label="Biometric data";
    style="rounded,filled"; fillcolor="{GREEN_SOFT}"; color="{GREEN}"; fontcolor="{GREEN}";
    node [fillcolor=white, color="{GREEN}"];
    b1 [label="Templates stored as\\nnormalised crops, not\\nraw photographs"];
    b2 [label="Purpose limited to\\nattendance verification"];
    b3 [label="Snapshots served only\\nto signed-in users"];
    b4 [label="Consent recorded\\nat enrolment"];
  }}

  subgraph cluster_acc {{
    label="Accountability";
    style="rounded,filled"; fillcolor="{AMBER_SOFT}"; color="{AMBER}"; fontcolor="{AMBER}";
    node [fillcolor=white, color="{AMBER}"];
    c1 [label="Audit log of every\\nmutation, with IP"];
    c2 [label="Every verification\\nattempt recorded"];
    c3 [label="Paid payroll weeks\\nnever rewritten"];
  }}

  subgraph cluster_ops {{
    label="Operational hardening";
    style="rounded,filled"; fillcolor="{GREY_SOFT}"; color="{GREY}"; fontcolor="{GREY}";
    node [fillcolor=white, color="{GREY}"];
    d1 [label="Debug server off\\nby default"];
    d2 [label="Secret key from\\nenvironment"];
    d3 [label="Local-only data,\\ncloud opt-in"];
    d4 [label="Camera health\\nmonitoring"];
  }}

  s1 -> b1 [style=invis]; b1 -> c1 [style=invis]; c1 -> d1 [style=invis];
}}
''')


def diagrams():
    print("Structural diagrams:")
    fig_methodology()
    fig_business_process()
    fig_architecture()
    fig_use_case()
    fig_activity()
    fig_state()
    fig_class()
    fig_erd()
    fig_deployment()
    fig_security()


# ===========================================================================
# Charts for Chapter 4.
#
# Colour follows the job, not decoration:
#   * one measure  -> a single hue (the project green), which passes contrast
#                     against the chart surface on its own
#   * two measures -> blue + orange. Green + orange was the natural choice for
#                     this project's palette but fails colour-vision separation
#                     (ΔE 5.9 under protanopia, against a floor of 8), so it is
#                     not used. Blue + orange separates at ΔE 24.7.
#   * thresholds and targets -> a neutral dashed reference line, labelled
#
# No chart here uses two y-axes: where two measures have different units they
# are drawn as separate stacked panels sharing one x-axis.
# ===========================================================================

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402

SERIES_1 = "#2a78d6"   # validated categorical slot 1
SERIES_2 = "#eb6834"   # validated categorical slot 2
SINGLE = "#2e7d52"     # project green, single-measure charts
REFERENCE = "#6d7484"  # neutral, for threshold and target lines
TEXT = "#14161c"
TEXT_MUTED = "#52514e"
GRID = "#e2e5ea"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": GRID,
    "axes.labelcolor": TEXT_MUTED,
    "axes.titlecolor": TEXT,
    "text.color": TEXT,
    "xtick.color": TEXT_MUTED,
    "ytick.color": TEXT_MUTED,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def _finish(fig, name):
    path = os.path.join(OUT, f"{name}.png")
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  {name}.png")


def _despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def _load(name):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docs", name))
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


# ---------------------------------------------------------------------------
# 3.8 Sequence diagram — drawn rather than generated, for UML lifelines
# ---------------------------------------------------------------------------

def fig_sequence():
    actors = [
        ("Worker", 0.0),
        ("Clock-in\npage", 1.0),
        ("Attendance\nservice", 2.0),
        ("CCTV\nengine", 3.0),
        ("Face\nengine", 4.0),
        ("Database", 5.0),
    ]
    messages = [
        (0, 1, "Worker ID + PIN, position", 0),
        (1, 2, "record_punch()", 1),
        (2, 5, "look up worker, verify PIN", 2),
        (2, 3, "grab_frames(count=8)", 3),
        (3, 2, "8 frames  [one camera open]", 4),
        (2, 4, "verify_worker(id, frames)", 5),
        (4, 4, "detect face, crop, equalise,\nmatch against enrolled templates", 6),
        (4, 2, "matched, score 71.8%", 7),
        (2, 5, "log biometric_transaction", 8),
        (2, 2, "evaluate geofence", 9),
        (2, 5, "save snapshot + attendance row", 10),
        (2, 3, "record_clip()  [background thread]", 11),
        (2, 5, "rebuild daily summary", 12),
        (2, 1, "recorded at 07:12, match 72%", 13),
        (1, 0, "confirmation shown", 14),
    ]

    fig, ax = plt.subplots(figsize=(10.5, 8.2))
    top, bottom = 0.0, -(len(messages) + 1) * 0.62

    for label, x in actors:
        ax.add_patch(Rectangle((x - 0.36, 0.15), 0.72, 0.5, facecolor="#e4efe7",
                               edgecolor=SINGLE, linewidth=1.2, zorder=3))
        ax.text(x, 0.4, label, ha="center", va="center", fontsize=8.5, zorder=4)
        ax.plot([x, x], [0.15, bottom], color=REFERENCE, linewidth=0.9,
                linestyle=(0, (4, 3)), zorder=1)

    for src, dst, text, index in messages:
        y = -(index + 1) * 0.62
        x1, x2 = actors[src][1], actors[dst][1]
        if src == dst:  # a self-call, drawn as a loop
            ax.add_patch(FancyArrowPatch((x1, y + 0.06), (x1, y - 0.16),
                                         connectionstyle="arc3,rad=-2.6",
                                         arrowstyle="-|>", mutation_scale=9,
                                         color=SERIES_1, linewidth=1.1, zorder=2))
            # Keep the label inside the frame: lifelines near the right edge
            # get their self-call text on the left instead.
            if x1 >= actors[-1][1] - 1.2:
                ax.text(x1 - 0.42, y - 0.05, text, ha="right", va="center", fontsize=7.6,
                        color=TEXT_MUTED, zorder=4)
            else:
                ax.text(x1 + 0.42, y - 0.05, text, ha="left", va="center", fontsize=7.6,
                        color=TEXT_MUTED, zorder=4)
        else:
            ax.add_patch(FancyArrowPatch((x1, y), (x2, y), arrowstyle="-|>",
                                        mutation_scale=9, color=SERIES_1,
                                        linewidth=1.1, zorder=2))
            ax.text((x1 + x2) / 2, y + 0.1, text, ha="center", va="bottom", fontsize=7.6,
                    color=TEXT_MUTED, zorder=4)

    ax.set_xlim(-0.7, 5.7)
    ax.set_ylim(bottom - 0.3, 0.9)
    ax.axis("off")
    _finish(fig, "fig_3_8_sequence_clockin")


# ---------------------------------------------------------------------------
# 4.1 Match score by capture condition
# ---------------------------------------------------------------------------

def fig_match_scores():
    acc = _load("accuracy_results.json")
    rows = acc["per_condition"]
    labels = [r["condition"] for r in rows]
    scores = [r["genuine_score"] for r in rows]
    threshold = 35.0

    order = sorted(range(len(scores)), key=lambda i: scores[i])
    labels = [labels[i] for i in order]
    scores = [scores[i] for i in order]

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    bars = ax.barh(labels, scores, color=SINGLE, height=0.62)
    for bar in bars:
        bar.set_capstyle("round")

    ax.axvline(threshold, color=REFERENCE, linestyle=(0, (5, 3)), linewidth=1.4, zorder=3)
    # Label above the topmost bar, clear of the axis and of every data label.
    ax.text(threshold + 1.5, len(labels) - 0.35, f"acceptance threshold {threshold:.0f}%",
            fontsize=8, color=TEXT_MUTED, va="center")
    ax.set_ylim(-0.7, len(labels) + 0.1)

    for bar, score in zip(bars, scores):
        ax.text(score + 1.2, bar.get_y() + bar.get_height() / 2, f"{score:.1f}",
                va="center", fontsize=8, color=TEXT_MUTED)

    ax.set_xlim(0, 108)
    ax.set_xlabel("Match confidence against the worker's enrolled templates (%)")
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _despine(ax)
    ax.tick_params(length=0)
    _finish(fig, "fig_4_1_match_scores_by_condition")


# ---------------------------------------------------------------------------
# 4.2 Threshold sweep
# ---------------------------------------------------------------------------

def fig_threshold_sweep():
    acc = _load("accuracy_results.json")
    sweep = acc["threshold_sweep"]
    thresholds = [s["threshold_pct"] for s in sweep]
    frr = [s["frr_pct"] for s in sweep]
    far = [s["far_pct"] for s in sweep]

    fig, ax = plt.subplots(figsize=(7.6, 4.0))
    ax.plot(thresholds, frr, color=SERIES_1, linewidth=2.0, marker="o", markersize=5,
            label="False rejection rate (genuine worker refused)")
    ax.plot(thresholds, far, color=SERIES_2, linewidth=2.0, marker="s", markersize=5,
            label="False acceptance rate (impostor accepted)")

    ax.axvline(35, color=REFERENCE, linestyle=(0, (5, 3)), linewidth=1.4)
    ax.text(35.8, max(frr) * 0.72 + 1, "default\nthreshold 35%", fontsize=8,
            color=TEXT_MUTED, va="center")

    # Direct labels on the endpoints rather than a number on every point.
    ax.annotate(f"{frr[-1]:.0f}%", (thresholds[-1], frr[-1]), textcoords="offset points",
                xytext=(6, 2), fontsize=8, color=TEXT_MUTED)
    ax.annotate("0% throughout", (thresholds[len(thresholds) // 2], far[len(far) // 2]),
                textcoords="offset points", xytext=(-14, 8), fontsize=8, color=TEXT_MUTED)

    ax.set_xlabel("Acceptance threshold (match confidence, %)")
    ax.set_ylabel("Error rate (%)")
    ax.set_ylim(-1.5, max(max(frr), max(far)) + 6)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _despine(ax)
    ax.tick_params(length=0)
    ax.legend(frameon=False, loc="upper left", fontsize=8.5)
    _finish(fig, "fig_4_2_threshold_sweep")


# ---------------------------------------------------------------------------
# 4.3 Refusal reasons
# ---------------------------------------------------------------------------

def fig_refusal_reasons():
    bench = _load("benchmark_results.json")
    reasons = bench["verification"]["refusal_reasons"]
    pretty = {
        "no_face_detected": "No face detected",
        "eyes_not_visible": "Eyes not visible",
        "face_did_not_match": "Face did not match",
        "worker_not_enrolled": "Worker not enrolled",
        "face_matched_another_worker": "Face belonged to another worker",
        "unspecified": "Unspecified",
    }
    items = sorted(reasons.items(), key=lambda kv: kv[1])
    labels = [pretty.get(k, k.replace("_", " ")) for k, _ in items]
    counts = [v for _, v in items]

    fig, ax = plt.subplots(figsize=(7.0, 3.0))
    bars = ax.barh(labels, counts, color=SINGLE, height=0.58)
    for bar, count in zip(bars, counts):
        ax.text(count + 0.06, bar.get_y() + bar.get_height() / 2, str(count),
                va="center", fontsize=8.5, color=TEXT_MUTED)

    accepted = bench["verification"]["accepted"]
    total = bench["verification"]["attempts"]
    ax.set_xlabel(f"Refused attempts by reason  (of {total} attempts, {accepted} accepted)")
    ax.set_xlim(0, max(counts) + 0.8)
    ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _despine(ax)
    ax.tick_params(length=0)
    _finish(fig, "fig_4_3_refusal_reasons")


# ---------------------------------------------------------------------------
# 4.4 Attendance trend — two panels, never two y-axes
# ---------------------------------------------------------------------------

def fig_attendance_trend():
    from app import app as flask_app
    import payroll_engine

    with flask_app.app_context():
        trend = payroll_engine.attendance_trend(14)

    labels = trend["labels"]
    workers = trend["workers"]
    verified = trend["verified"]
    hours = trend["hours"]
    x = list(range(len(labels)))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.8, 5.0), sharex=True,
                                   gridspec_kw={"height_ratios": [1.25, 1], "hspace": 0.18})

    width = 0.38
    ax1.bar([i - width / 2 - 0.01 for i in x], workers, width=width, color=SERIES_1,
            label="Workers present")
    ax1.bar([i + width / 2 + 0.01 for i in x], verified, width=width, color=SERIES_2,
            label="Of those, face verified")
    ax1.set_ylabel("Workers")
    ax1.yaxis.set_major_locator(matplotlib.ticker.MaxNLocator(integer=True))
    ax1.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax1.set_axisbelow(True)
    _despine(ax1)
    ax1.tick_params(length=0)
    ax1.legend(frameon=False, fontsize=8.5, loc="upper left", ncol=2)

    ax2.fill_between(x, hours, color=SINGLE, alpha=0.16)
    ax2.plot(x, hours, color=SINGLE, linewidth=2.0)
    ax2.scatter([x[-1]], [hours[-1]], color=SINGLE, s=28, zorder=4)
    ax2.annotate(f"{hours[-1]:.1f} h", (x[-1], hours[-1]), textcoords="offset points",
                 xytext=(-6, 8), fontsize=8, color=TEXT_MUTED, ha="right")
    ax2.set_ylabel("Hours worked")
    ax2.set_xticks(x)
    ax2.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax2.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax2.set_axisbelow(True)
    _despine(ax2)
    ax2.tick_params(length=0)

    _finish(fig, "fig_4_4_attendance_trend")


# ---------------------------------------------------------------------------
# 4.5 Page render times
# ---------------------------------------------------------------------------

def fig_page_times():
    bench = _load("benchmark_results.json")
    rows = sorted(bench["page_timings_ms"], key=lambda r: r["median"])
    labels = [r["operation"] for r in rows]
    medians = [r["median"] for r in rows]
    maxima = [r["max"] for r in rows]

    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    bars = ax.barh(labels, medians, color=SINGLE, height=0.6, label="Median")
    ax.scatter(maxima, range(len(labels)), color=SERIES_2, s=26, zorder=4,
               label="Slowest of 10 requests")

    for bar, median in zip(bars, medians):
        ax.text(median + 0.6, bar.get_y() + bar.get_height() / 2, f"{median:.1f}",
                va="center", fontsize=8, color=TEXT_MUTED)

    ax.axvline(200, color=REFERENCE, linestyle=(0, (5, 3)), linewidth=1.2)
    ax.set_xlabel("Server-side response time (ms) — lower is better")
    ax.set_xlim(0, max(maxima) * 1.25)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _despine(ax)
    ax.tick_params(length=0)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    _finish(fig, "fig_4_5_page_response_times")


def main():
    diagrams()
    print("Charts:")
    fig_sequence()
    fig_match_scores()
    fig_threshold_sweep()
    fig_refusal_reasons()
    fig_attendance_trend()
    fig_page_times()


if __name__ == "__main__":
    main()
