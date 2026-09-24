# Installing the Farm Worker Management System

Four ways to install, all producing the same running system at
**http://localhost:8010**:

| Path | Best for | Jump to |
| --- | --- | --- |
| **Docker** | The farm office machine. One command, nothing to install by hand. | [Docker](#4-docker-any-platform) |
| **Linux** | A mini PC or Raspberry Pi 4 running permanently at the farm. | [Linux](#2-linux) |
| **Windows** | An office PC, or a laptop for development and demonstrations. | [Windows](#1-windows-10-and-11) |
| **macOS** | Development only. | [macOS](#3-macos) |

If you are setting up the machine that will actually run at the farm, use
**Docker on Linux**. If you are working on the code, use the native install for
your own operating system.

---

## Before you start

### What you need

| | Minimum | Recommended |
| --- | --- | --- |
| Computer | Raspberry Pi 4, quad-core, 2 GB RAM | Mini PC, quad-core, 8 GB RAM |
| Storage | 32 GB microSD | 128 GB SSD |
| Clock-in camera | 720p USB webcam | 1080p USB webcam on a fixed mount at face height |
| Surveillance cameras | One RTSP IP camera | Two to four, covering the terminal and the gate |
| Network | None needed to record attendance | Local Wi-Fi for the IP cameras |
| Python | 3.10 | **3.11 or 3.12** |

Attendance recording never needs the internet. A network connection is only
used for IP cameras and for optional cloud upload of snapshots.

### About the Python version

**Use Python 3.11 or 3.12.** Those are the versions the system was built and
tested on. 3.10 works. 3.13 and 3.14 will probably work — the OpenCV wheels are
`abi3` and are not tied to a specific Python version — but they are untested
here, and if a wheel is ever missing for your version `pip` will try to compile
OpenCV from source, which takes hours on a Raspberry Pi and usually fails.

If you are on a Raspberry Pi, use the **64-bit** Raspberry Pi OS. There is no
prebuilt OpenCV wheel for 32-bit ARM, so a 32-bit system hits the
compile-from-source problem above.

### Two dependency traps worth knowing about

Both are handled by `requirements.txt`, but they explain errors you may see if
you install packages by hand.

**OpenCV must be the contrib build.** The face recognizer lives in `cv2.face`,
which ships only in `opencv-contrib-python`. Plain `opencv-python` provides a
module with the same name, `cv2`, so if both are installed the plain one can win
and `cv2.face` silently disappears. The application does not crash — it falls
back to a much weaker match and the Biometric page reports
`Recognizer: correlation-fallback`. If you ever see that, run:

```
pip uninstall -y opencv-python opencv-python-headless
pip install --force-reinstall "opencv-contrib-python>=4.10.0,<5.0"
```

**A barcode scanner needs no driver.** If you use USB scanners for the worker
cards, plug one in and it behaves as a keyboard: it types the card number and
presses Enter. Nothing to install. If instead you want to scan with the
computer's own camera, the browser must be Chrome or Edge on a desktop — the
button that opens the camera scanner hides itself on browsers that cannot do it,
and the PIN and face steps still work.

**OpenCV must stay below version 5.** OpenCV 5 removed the Haar cascade XML
files that used to ship inside the wheel, and the face and eye detectors are
loaded from `cv2.data.haarcascades`. On OpenCV 5 that folder is empty, both
detectors fail to load, and every clock-in is refused with *no face detected*.
The pin in `requirements.txt` is `>=4.10.0,<5.0`; do not remove the upper bound.

---

## 1. Windows 10 and 11

### Step 1 — Install Python

Download Python **3.12** from [python.org/downloads/windows](https://www.python.org/downloads/windows/)
and run the installer.

On the first screen of the installer, tick **Add python.exe to PATH** before
clicking Install. This is easy to miss and is the cause of most "python is not
recognized" errors afterwards.

Open **PowerShell** and check it worked:

```powershell
python --version
```

You should see `Python 3.12.x`. If you see nothing, or the Microsoft Store
opens instead, the PATH box was not ticked — re-run the installer, choose
*Modify*, and enable it.

### Step 2 — Get the project

If you have Git installed:

```powershell
git clone <repository-url> fms
cd fms
```

Otherwise copy the project folder onto the machine and open PowerShell in it:

```powershell
cd "C:\Users\<you>\Documents\fms"
```

### Step 3 — Create a virtual environment

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`.

If PowerShell refuses with *running scripts is disabled on this system*, allow
signed local scripts for your own account and try again:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Command Prompt users activate with `.venv\Scripts\activate.bat` instead and do
not need the policy change.

### Step 4 — Install the dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

This downloads about 90 MB, mostly OpenCV. To run the test suite as well, use
`requirements-dev.txt` instead.

### Step 5 — Set a session key

Without this, everyone is signed out whenever the application restarts.

```powershell
$key = python -c "import secrets; print(secrets.token_hex(32))"
Set-Content -Path .env -Value "FMS_SECRET_KEY=$key"
```

### Step 6 — Start it

```powershell
python app.py
```

Open **http://localhost:8010** and sign in as `admin` / `admin`. You are
required to set a real password before anything else opens.

Stop the server with `Ctrl+C`. To start it again later, `cd` into the folder,
run `.venv\Scripts\Activate.ps1`, then `python app.py`.

### Windows notes

**Camera permission.** Windows blocks camera access per application. Open
**Settings → Privacy & security → Camera** and make sure *Let desktop apps
access your camera* is on. Without it the camera opens but every frame is
black.

**Which camera index.** With one webcam the index is `0`. With a built-in laptop
camera plus a USB one, the USB camera is usually `1`. Set it on the CCTV page
and press *Test* — the preview tells you immediately which one you have.

**Firewall.** The first time you run it, Windows asks whether to allow Python
through the firewall. Allow it on **private networks** only if a supervisor will
open the dashboard from another machine on the farm network. Deny it if you are
only using this computer.

**Antivirus.** Some antivirus products scan every frame the webcam produces and
slow verification noticeably. If a clock-in takes several seconds on Windows but
under a second elsewhere, add the project folder to your antivirus exclusions.

**Running it as a background service.** `python app.py` stops when you close
PowerShell. To keep it running after sign-out, install
[NSSM](https://nssm.cc/download) and register the virtual environment's Python:

```powershell
nssm install FMS "C:\Users\<you>\Documents\fms\.venv\Scripts\python.exe" "C:\Users\<you>\Documents\fms\app.py"
nssm set FMS AppDirectory "C:\Users\<you>\Documents\fms"
nssm start FMS
```

---

## 2. Linux

Written for Ubuntu, Debian and Raspberry Pi OS (64-bit). On Fedora or RHEL the
steps are identical with `dnf` in place of `apt`.

### Step 1 — Install the system packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git \
                    ffmpeg v4l-utils \
                    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1
```

The last line is the set of shared libraries the OpenCV wheel links against.
Server and Raspberry Pi Lite images do not have them, and without them the
import fails with `libGL.so.1: cannot open shared object file` — an error that
looks like a broken install but is only a missing package.

### Step 2 — Get the project

```bash
git clone <repository-url> fms
cd fms
```

### Step 3 — Create a virtual environment and install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

On a Raspberry Pi this takes a few minutes. If `pip` starts *building* OpenCV
rather than downloading a `.whl`, stop it — you are on a 32-bit system or an
unsupported Python version, and compiling will take hours. Check with
`uname -m`: you want `aarch64`, not `armv7l`.

### Step 4 — Give the account access to the camera

```bash
sudo usermod -aG video $USER
```

Log out and back in for this to take effect. Confirm the camera is visible:

```bash
v4l2-ctl --list-devices
```

### Step 5 — Set a session key

```bash
echo "FMS_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env
```

### Step 6 — Start it

```bash
python app.py
```

Open **http://localhost:8010**, or `http://<the machine's IP>:8010` from another
computer on the same network. Sign in as `admin` / `admin` and set a real
password.

### Running it permanently with systemd

`python app.py` stops when you close the terminal. For a machine that runs at
the farm, create a service so it starts at boot and restarts after a power cut.

```bash
sudo tee /etc/systemd/system/fms.service > /dev/null <<'EOF'
[Unit]
Description=Farm Worker Management System
After=network.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/fms
EnvironmentFile=/home/pi/fms/.env
ExecStart=/home/pi/fms/.venv/bin/python /home/pi/fms/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now fms
```

Replace `pi` and `/home/pi/fms` with your own user and path. Then:

```bash
systemctl status fms      # is it running?
journalctl -u fms -f      # follow the log
sudo systemctl restart fms
```

A farm host will lose power without warning. `Restart=always` and
`WantedBy=multi-user.target` between them mean it comes back on its own.

---

## 3. macOS

For development. A Mac is not the intended deployment target.

```bash
brew install python@3.12
git clone <repository-url> fms
cd fms
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "FMS_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env
python app.py
```

**Camera permission.** The first camera access raises a system prompt. If you
dismiss it, the camera returns black frames from then on; re-enable it under
**System Settings → Privacy & Security → Camera** for Terminal (or your editor,
if you run the app from there).

**Port 5000 is taken.** macOS uses it for AirPlay Receiver. This is one reason
the application listens on 8010 instead.

**A virtual environment is tied to its path.** If you move or rename the project
folder, `.venv` breaks with a confusing "no such file or directory" for Python
itself. Delete `.venv` and recreate it — nothing else is lost.

---

## 4. Docker (any platform)

The recommended way to run the system at the farm. Nothing is installed on the
host except Docker itself, and an upgrade is one command that cannot leave the
machine half-updated.

### Step 1 — Install Docker

- **Linux:** `curl -fsSL https://get.docker.com | sudo sh`, then
  `sudo usermod -aG docker $USER` and log out and back in.
- **Windows and macOS:** install
  [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.

Check it:

```bash
docker --version
docker compose version
```

### Step 2 — Set a session key

```bash
echo "FMS_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')" > .env
```

On Windows PowerShell:

```powershell
$key = python -c "import secrets; print(secrets.token_hex(32))"
Set-Content -Path .env -Value "FMS_SECRET_KEY=$key"
```

Compose reads `.env` automatically. Skip this and sessions are signed with a key
that changes on every restart, so everyone is logged out each time.

### Step 3 — Pass the camera through (Linux hosts only)

If the clock-in camera is a USB webcam plugged into the host, uncomment the
`devices:` block in `docker-compose.yml`:

```yaml
devices:
  - "/dev/video0:/dev/video0"
```

Find the right index with `ls /dev/video*`.

**Docker Desktop on Windows and macOS cannot pass a USB webcam into a
container** — the container runs inside a Linux virtual machine that has no
access to the host's USB devices. On those platforms either run the native
install instead, or use an RTSP IP camera, which is reached over the network and
needs no passthrough.

### Step 4 — Build and start

```bash
docker compose up -d --build
docker compose logs -f fms
```

The first build takes a few minutes. Open **http://localhost:8010** and sign in
as `admin` / `admin`.

### Step 5 — Confirm it is healthy

```bash
docker ps
```

The status column should read `healthy`, not merely `Up`. The image declares a
health check that polls `/api/v1/health`, so a container that is running but
cannot open its database reports as unhealthy rather than looking fine.

### Day-to-day commands

```bash
docker compose ps                  # what is running
docker compose logs -f fms         # follow the log
docker compose restart fms         # restart
docker compose down                # stop and remove the container
docker compose up -d --build       # rebuild after a code change
```

### Where the data lives

The database and the captured media are held on the host, not inside the image,
so rebuilding the application never touches them:

| Host path | Container path | Contents |
| --- | --- | --- |
| `./data/` | `/app/data/` | `fms.db`, the SQLite database |
| `./captures/` | `/app/captures/` | Snapshots, enrolment references, event clips |

Both are mounted as **directories**, not as a database file. A bind mount naming
a file that does not exist yet makes Docker create a directory in its place,
which SQLite then cannot open — mounting the parent directory avoids that
entirely.

To carry an existing database into a Docker deployment:

```bash
mkdir -p data && cp fms.db data/fms.db
```

---

## After installation, whichever path you took

### First-run checklist

1. Sign in as `admin` / `admin` and set a real password.
2. **Settings** — organisation name, farm coordinates, geofence radius, hourly
   rate default, NAPSA and NHIMA rates, match threshold.
3. **CCTV** — register the clock-in camera, press *Test*, then use the star
   button to make it the attendance camera. Add IP cameras for surveillance.
4. **Workers** — add each worker with an hourly rate and a unique PIN.
5. **Biometric** — enrol at least three face samples per worker, at slightly
   different angles in even light. **Nobody can clock in until this is done.**
6. Have a worker clock in from the home page and confirm the session appears on
   **Attendance** with a match score and a snapshot.
7. **Payroll** — choose a week ending date and generate.
8. *Optional:* **Settings → Worker cards** — if you want workers to clock in
   with a printed card, switch cards on there first, choose what the barcode
   carries, then go to **Workers → Issue cards** and print the sheet. See
   [the operator manual](manual.md) for what each barcode option means.

### Optional: demonstration data

```bash
python tools/seed_demo.py
```

Creates eight fictional workers, two weeks of attendance and payroll — useful
for a demonstration or for screenshots before real data exists. Worker PINs are
`1000`, `1001`, `1002` and so on. Do not run this on a live database.

### Run the tests

```bash
pip install -r requirements-dev.txt
pytest
```

195 tests, about a minute. All should pass.

### Check the recognizer really loaded

```bash
curl http://localhost:8010/api/v1/health
```

`"contrib_available": true` means `cv2.face` was found and LBPH is in use. If it
is `false`, re-read [the two dependency traps](#two-dependency-traps-worth-knowing-about) above.

---

## Upgrading

```bash
git pull
pip install -r requirements.txt      # native install
# or
docker compose up -d --build         # Docker
```

There is no migration step to run by hand. On start-up `migrations.py` compares
the models against the live tables and adds any missing columns. It is additive
only — it never drops or renames anything — so an existing installation keeps
its data and a failed upgrade leaves the database readable by the old version.

Two protections run at the same time so that an upgrade cannot lock you out: an
unrecognised role is treated as the least privileged rather than the most, and
if the database contains no active administrator at all, the account named
`admin` (or else the oldest account) is promoted to one.

---

## Backing up

Everything that matters is in two places:

```bash
# Native install
tar czf fms-backup-$(date +%F).tar.gz fms.db captures/

# Docker
tar czf fms-backup-$(date +%F).tar.gz data/ captures/
```

Copy the archive off the machine. A single-file database on a farm host is one
power event away from being the only copy. Restore by stopping the application,
unpacking the archive in place, and starting it again.

---

## Troubleshooting

**`python` is not recognized (Windows)** — Python was installed without *Add
python.exe to PATH*. Re-run the installer, choose *Modify*, tick the box.

**`running scripts is disabled on this system` (Windows)** — run
`Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`, or use
Command Prompt and `.venv\Scripts\activate.bat`.

**`libGL.so.1: cannot open shared object file` (Linux)** — the OpenCV shared
libraries are missing. Install them:
`sudo apt install -y libgl1 libglib2.0-0 libsm6 libxext6 libxrender1`.

**`pip` starts compiling OpenCV instead of downloading it** — there is no wheel
for your platform or Python version. Check `uname -m` reports `aarch64` rather
than `armv7l`, and use Python 3.11 or 3.12.

**The Biometric page shows `Recognizer: correlation-fallback`** — `cv2.face` is
missing. Plain `opencv-python` is installed alongside the contrib build and is
shadowing it. Uninstall both OpenCV packages and reinstall only
`opencv-contrib-python`.

**Every clock-in is refused with *no face was detected*, even in good light** —
check the OpenCV version with `pip show opencv-contrib-python`. If it is 5.x,
the bundled Haar cascades are gone; reinstall with the `<5.0` pin.

**The camera preview is black** — camera permission. Windows: *Settings →
Privacy & security → Camera*. macOS: *System Settings → Privacy & Security →
Camera*. Linux: add the account to the `video` group. Also close any other
application holding the webcam; only one process can open it at a time.

**The page will not load at all** — check the port. Browsers refuse port 6000
outright (`ERR_UNSAFE_PORT`), macOS uses 5000 for AirPlay, and 8000 and 8080 are
commonly taken. The application uses 8010 for exactly these reasons. Change it
with `FMS_PORT` if something else on your machine already has 8010.

**Everyone is signed out after a restart** — `FMS_SECRET_KEY` is not set. See
step 5 of your platform's instructions.

**Docker: the container is `Up` but the page does not load** — check
`docker ps` for the health state and `docker compose logs fms` for the reason.
The usual cause is a `data/` directory that the container cannot write to.

**Docker Desktop: the camera does not work** — expected. Docker Desktop on
Windows and macOS cannot pass a USB webcam into a container. Use an RTSP camera
or the native install.

**A virtual environment stopped working after moving the project** — a `.venv`
records absolute paths. Delete it and recreate it; nothing else is affected.

---

## Uninstalling

Nothing is installed outside the project folder except, if you created them, the
systemd service or the NSSM service.

```bash
# Docker
docker compose down
docker image rm fms-fms

# systemd
sudo systemctl disable --now fms
sudo rm /etc/systemd/system/fms.service

# Windows service
nssm remove FMS confirm
```

Then delete the project folder — but take a backup of `fms.db` (or `data/`) and
`captures/` first if the installation ever held real attendance records.
