# Farm Worker Management System (FMS) Manual

## 1. Overview

FMS is a Flask-based operations platform for worker onboarding, attendance capture, CCTV monitoring, and admin data management.
It stores operational data in SQLite and uses live camera input for attendance verification and snapshots.

## 2. Start The App

1. Open terminal and move to the project folder.
1. Activate the virtual environment.
1. Start the app:

```bash
python app.py
```

1. Open:

```text
http://127.0.0.1:5000
```

## 3. Default Admin Login

- Username: `admin`
- Password: `admin`

## 4. Example: Worker Onboarding

1. Go to **Workers** and click **Add Worker**.
2. Fill profile details and assign a unique PIN.
3. Set status to **active**.
4. Save and confirm generated worker ID.

Flowchart:

```text
[Open Workers]
  |
  v
[Add Worker]
  |
  v
[Fill Details + PIN]
  |
  v
[Save]
  |
  v
[Worker ID Generated]
```

## 5. Example: Worker Clock In

1. Worker enters ID and PIN on login page.
2. System validates credentials.
3. Face and eye verification runs.
4. System captures a clean snapshot.
5. Attendance IN row + event snapshot are saved.

Flowchart:

```text
[Worker ID + PIN]
  |
  v
[Validate Credentials]
   |            \\
 pass           fail
   |              \\
   v               [Show Error]
[Face/Eye Verification]
   |            \\
 pass           fail
   |              \\
   v               [Retry Prompt]
[Capture Snapshot]
  |
  v
[Save Attendance IN]
```

## 6. Example: Edit and Reset Operations

1. Click row **Edit** button.
2. Modal loads existing record fields.
3. Update and submit changes.
4. For worker PIN or user password resets, use the key icon actions.

Flowchart:

```text
[Click Edit]
  |
  v
[Read data-record JSON]
  |
  v
[Populate Modal Inputs]
  |
  v
[Submit to /entity/{id}/update]
```

## 7. Operational Pages

- **CCTV**: camera setup, feed records, recording views.
- **Biometric**: device setup and status.
- **Payroll**: weekly payroll capture and payment status.
- **Cloud Sync**: cloud settings and sync queue visibility.
- **Users**: admin user profiles and password reset actions.

## 8. Troubleshooting

- **Blank camera feed**: verify camera source, close other camera apps, test built-in fallback.
- **Clock-in failure**: verify worker is active, PIN is correct, face is visible to camera.
- **Import warnings in editor**: ensure VS Code interpreter is set to project `.venv`.
