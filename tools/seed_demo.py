"""Populate the database with realistic demo data.

Useful for two things: showing the system to a supervisor without waiting for a
week of real punches, and giving the report something to screenshot. Face
samples are synthetic patterns, so enrolment badges and matching statistics are
populated without needing a camera.

    python tools/seed_demo.py            # refuses if workers already exist
    python tools/seed_demo.py --force    # wipes attendance/payroll demo data first
"""

import os
import random
import sys
from datetime import date, datetime, time, timedelta

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import face_engine  # noqa: E402
import payroll_engine  # noqa: E402
from app import _generate_worker_id, _pin_fingerprint, app  # noqa: E402
from database import db  # noqa: E402
from models import (  # noqa: E402
    Attendance,
    BiometricTransaction,
    CCTVFeed,
    DailyAttendanceSummary,
    FaceTemplate,
    HardwareHealthLog,
    Payroll,
    Setting,
    Worker,
)

# Fictional workers. No name here belongs to anyone connected with the project,
# and none is drawn from the live database - the demonstration dataset must be
# safe to screenshot for a report or a presentation.
WORKERS = [
    ("Musonda Banda", "Harvesting", 18.0),
    ("Mwiza Tembo", "Irrigation", 22.0),
    ("Kondwani Zulu", "Packhouse", 22.0),
    ("Chipo Mwale", "Harvesting", 18.0),
    ("Lubasi Nyambe", "Security", 20.0),
    ("Thandiwe Kunda", "Packhouse", 19.0),
    ("Kabwe Mulenga", "Maintenance", 25.0),
    ("Bwalya Chanda", "Harvesting", 18.0),
]


def _synthetic_face(seed: int):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 60, size=face_engine.FACE_SIZE, dtype=np.uint8)
    gradient = np.linspace(40 + (seed % 6) * 20, 200 - (seed % 4) * 10,
                           face_engine.FACE_SIZE[0], dtype=np.uint8)
    return np.clip(base + gradient[None, :], 0, 255).astype(np.uint8)


def _set(key: str, value: str) -> None:
    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))


def main(force: bool) -> None:
    with app.app_context():
        if Worker.query.count() and not force:
            print("Workers already exist. Re-run with --force to reseed demo data.")
            return

        if force:
            for model in (BiometricTransaction, DailyAttendanceSummary, Payroll,
                          Attendance, FaceTemplate, HardwareHealthLog):
                model.query.delete()
            Worker.query.delete()
            db.session.commit()
            face_engine.invalidate()

        _set("farm_latitude", "-15.4067")
        _set("farm_longitude", "28.2871")
        _set("geofence_radius_m", "500")
        _set("org_name", "Chisamba Green Farms")
        db.session.commit()

        random.seed(7)
        workers = []
        for index, (name, department, rate) in enumerate(WORKERS):
            worker = Worker(
                worker_id=_generate_worker_id(),
                name=name,
                department=department,
                hourly_rate=rate,
                # Masked, deliberately not a dialable number: the format is
                # shown so the field looks realistic in a screenshot, but no
                # real subscriber can be reached on it.
                phone_number=f"+260 97X XXX {index + 1:03d}",
                address="Chisamba District",  # district only, never a plot or box number
                emergency_contact="Next of kin",
                status="active" if index < 7 else "inactive",
                enrollment_date=datetime.utcnow() - timedelta(days=40 - index),
                pin_fingerprint=_pin_fingerprint(f"{1000 + index}"),
            )
            worker.set_pin(f"{1000 + index}")
            db.session.add(worker)
            workers.append(worker)
        db.session.commit()

        # Enrol most workers with three synthetic samples each.
        for index, worker in enumerate(workers):
            if index >= 6:
                continue  # leave two unenrolled so the dashboard shows the gap
            for sample in range(3):
                db.session.add(FaceTemplate(
                    worker_id=worker.id,
                    face_embedding=face_engine._encode(_synthetic_face(index * 10 + sample)),
                    algorithm="LBPH",
                    sample_index=sample + 1,
                    quality_score=round(random.uniform(90, 260), 1),
                ))
            worker.face_enrolled_at = datetime.utcnow() - timedelta(days=30 - index)
        db.session.commit()
        face_engine.invalidate()

        # Two weeks of attendance for the enrolled workers.
        today = date.today()
        start = today - timedelta(days=13)
        for offset in range(14):
            day = start + timedelta(days=offset)
            if day.weekday() == 6:      # no Sunday shift
                continue
            for index, worker in enumerate(workers[:6]):
                if random.random() < 0.12:   # occasional absence
                    continue
                in_hour, in_minute = 7, random.choice([0, 3, 8, 12, 25, 41])
                worked = random.choice([8, 8, 8, 8.5, 9, 9.5, 7.5])
                check_in = datetime.combine(day, time(in_hour, in_minute))
                check_out = check_in + timedelta(hours=worked)
                score = round(random.uniform(52, 88), 2)
                near = random.random() > 0.1
                db.session.add(Attendance(
                    worker_id=worker.id,
                    check_in_time=check_in,
                    check_out_time=check_out,
                    latitude=-15.4067 + random.uniform(-0.0015, 0.0015),
                    longitude=28.2871 + random.uniform(-0.0015, 0.0015),
                    verified_by_cctv=True,
                    verified_by_face=True,
                    check_in_match_score=score,
                    check_out_match_score=round(score - random.uniform(0, 6), 2),
                    within_geofence=near,
                    distance_from_farm_m=round(random.uniform(20, 260) if near
                                               else random.uniform(700, 2400), 1),
                ))
                db.session.add(BiometricTransaction(
                    worker_id=worker.id,
                    transaction_type="face_verify_in",
                    modality="face",
                    success=True,
                    match_score=score,
                    threshold_used=35.0,
                    timestamp=check_in,
                ))
        db.session.commit()

        # A handful of rejected attempts, so the accuracy figures are honest.
        for _ in range(6):
            worker = random.choice(workers)
            db.session.add(BiometricTransaction(
                worker_id=worker.id,
                transaction_type="face_verify_in",
                modality="face",
                success=False,
                match_score=round(random.uniform(4, 30), 2),
                threshold_used=35.0,
                error_message=random.choice(["face_did_not_match", "no_face_detected",
                                             "eyes_not_visible", "worker_not_enrolled"]),
                timestamp=datetime.utcnow() - timedelta(hours=random.randint(1, 200)),
            ))

        db.session.add(HardwareHealthLog(
            device_type="camera", device_id=1, device_label="Built-in Camera 0",
            status="online", response_time_ms=140,
        ))
        db.session.add(HardwareHealthLog(
            device_type="camera", device_id=2, device_label="North Gate IP Camera",
            status="offline", error_code="open_failed",
            error_message="Could not read frames from rtsp://10.0.0.5:554/stream1",
            response_time_ms=3120,
        ))
        if not CCTVFeed.query.filter_by(camera_name="North Gate IP Camera").first():
            db.session.add(CCTVFeed(
                camera_name="North Gate IP Camera",
                camera_location="North gate, solar powered",
                rtsp_url="rtsp://10.0.0.5:554/stream1",
                status="offline",
            ))
        db.session.commit()

        # Summaries and payroll for the last two full weeks.
        payroll_engine.refresh_range(start, today)
        last_sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        for week in (last_sunday - timedelta(days=7), last_sunday):
            outcome = payroll_engine.generate_week(week)
            print(f"Payroll week ending {week}: "
                  f"{outcome['created']} created, {outcome['updated']} updated")

        print(f"Seeded {len(workers)} workers, "
              f"{Attendance.query.count()} attendance sessions, "
              f"{DailyAttendanceSummary.query.count()} daily summaries, "
              f"{Payroll.query.count()} payroll rows.")
        print("Worker PINs are 1000, 1001, 1002 ... in the order listed in this script.")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
