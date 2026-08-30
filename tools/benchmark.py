"""Measure the figures the project report quotes, so they are reproducible.

Every number in Chapter 4's performance table comes from here rather than from
an estimate. Run against a seeded database:

    python tools/seed_demo.py --force
    python tools/benchmark.py

Timings are wall-clock on the host that runs it, so the report states the
machine alongside the results. No camera is required: face matching is measured
on frames held in memory, which is also the fairest way to time the recognizer
without a webcam's exposure delay confounding it.
"""

import json
import os
import platform
import statistics
import sys
import time
from datetime import date, timedelta

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import face_engine  # noqa: E402
import payroll_engine  # noqa: E402
from app import app  # noqa: E402
from database import db  # noqa: E402
from models import (  # noqa: E402
    Attendance,
    BiometricTransaction,
    DailyAttendanceSummary,
    FaceTemplate,
    Payroll,
    Worker,
)

REPEATS = 30


def _summarise(name, samples, unit="ms"):
    return {
        "operation": name,
        "n": len(samples),
        "mean": round(statistics.mean(samples), 2),
        "median": round(statistics.median(samples), 2),
        "min": round(min(samples), 2),
        "max": round(max(samples), 2),
        "stdev": round(statistics.stdev(samples), 2) if len(samples) > 1 else 0.0,
        "unit": unit,
    }


def _probe_frames(count=6):
    """Deterministic frames standing in for a camera feed."""
    rng = np.random.default_rng(4)
    return [rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8) for _ in range(count)]


def measure_face_matching():
    """Time a 1:N match against the enrolled population."""
    results = []
    face_engine.invalidate()

    start = time.perf_counter()
    model, labels = face_engine._ensure_model()
    train_ms = (time.perf_counter() - start) * 1000
    results.append(_summarise("Recognizer training (all templates)", [train_ms]))

    if model is None:
        return results, 0

    crop = face_engine._decode(FaceTemplate.query.first().face_embedding)

    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        face_engine._predict(model, crop)
        samples.append((time.perf_counter() - start) * 1000)
    results.append(_summarise("Single face match (1:N)", samples))

    samples = []
    for _ in range(REPEATS):
        start = time.perf_counter()
        face_engine.extract_face(np.zeros((480, 640, 3), dtype=np.uint8), require_eyes=False)
        samples.append((time.perf_counter() - start) * 1000)
    results.append(_summarise("Face detection pass over one frame", samples))

    return results, len(labels)


def measure_verification_pipeline():
    """Time verify_worker over a batch of frames, which is what a punch does."""
    worker = Worker.query.filter(Worker.face_enrolled_at.isnot(None)).first()
    if not worker:
        return []
    frames = _probe_frames(8)
    samples = []
    for _ in range(15):
        start = time.perf_counter()
        face_engine.verify_worker(worker.id, frames, threshold=35.0, require_eyes=True)
        samples.append((time.perf_counter() - start) * 1000)
    return [_summarise("Verification decision over 8 frames", samples)]


def measure_payroll():
    today = date.today()
    week_ending = today - timedelta(days=(today.weekday() + 1) % 7)
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        payroll_engine.generate_week(week_ending)
        samples.append((time.perf_counter() - start) * 1000)
    return [_summarise("Weekly payroll generation (all active workers)", samples)]


def measure_summaries():
    today = date.today()
    samples = []
    for _ in range(5):
        start = time.perf_counter()
        payroll_engine.refresh_range(today - timedelta(days=13), today)
        samples.append((time.perf_counter() - start) * 1000)
    return [_summarise("Rebuild 14 days of daily summaries", samples)]


def measure_pages():
    """Server-side render time for each page, measured through the test client."""
    client = app.test_client()
    with client.session_transaction() as session:
        session["admin_logged_in"] = True
        session["admin_username"] = "admin"
        session["admin_role"] = "admin"
        session["must_change_password"] = False

    pages = {
        "Dashboard": "/dashboard",
        "Workers": "/workers",
        "Attendance": "/attendance",
        "Biometric": "/biometric",
        "Payroll": "/payroll",
        "CCTV": "/cctv",
        "Audit log": "/audit-log",
        "Attendance CSV export": "/export/attendance.csv",
        "Payroll CSV export": "/export/payroll.csv",
        "API: workers": "/api/v1/workers",
        "API: attendance": "/api/v1/attendance",
    }

    rows = []
    for label, path in pages.items():
        samples = []
        for _ in range(10):
            start = time.perf_counter()
            response = client.get(path)
            samples.append((time.perf_counter() - start) * 1000)
            assert response.status_code == 200, f"{path} returned {response.status_code}"
        rows.append(_summarise(label, samples))
    return rows


def verification_statistics():
    total = BiometricTransaction.query.count()
    accepted = BiometricTransaction.query.filter_by(success=True).count()
    reasons = {}
    for row in BiometricTransaction.query.filter_by(success=False).all():
        key = (row.error_message or "unspecified")
        reasons[key] = reasons.get(key, 0) + 1

    scores_ok = [r.match_score for r in BiometricTransaction.query.filter_by(success=True).all()
                 if r.match_score is not None]
    scores_no = [r.match_score for r in BiometricTransaction.query.filter_by(success=False).all()
                 if r.match_score is not None]

    return {
        "attempts": total,
        "accepted": accepted,
        "refused": total - accepted,
        "acceptance_rate_pct": round(accepted / total * 100, 1) if total else 0.0,
        "accepted_score_mean": round(statistics.mean(scores_ok), 2) if scores_ok else None,
        "accepted_score_min": round(min(scores_ok), 2) if scores_ok else None,
        "accepted_score_max": round(max(scores_ok), 2) if scores_ok else None,
        "refused_score_mean": round(statistics.mean(scores_no), 2) if scores_no else None,
        "refusal_reasons": reasons,
        "threshold_pct": 35.0,
    }


def dataset_profile():
    db_path = app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")
    size_kb = round(os.path.getsize(db_path) / 1024, 1) if os.path.exists(db_path) else None
    return {
        "workers": Worker.query.count(),
        "workers_enrolled": Worker.query.filter(Worker.face_enrolled_at.isnot(None)).count(),
        "face_templates": FaceTemplate.query.count(),
        "template_bytes_each": face_engine.FACE_SIZE[0] * face_engine.FACE_SIZE[1],
        "attendance_sessions": Attendance.query.count(),
        "daily_summaries": DailyAttendanceSummary.query.count(),
        "payroll_rows": Payroll.query.count(),
        "database_size_kb": size_kb,
    }


def main():
    with app.app_context():
        timings = []
        face_rows, enrolled_labels = measure_face_matching()
        timings += face_rows
        timings += measure_verification_pipeline()
        timings += measure_summaries()
        timings += measure_payroll()
        page_rows = measure_pages()

        report = {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "host": {
                "platform": platform.platform(),
                "processor": platform.processor() or platform.machine(),
                "python": platform.python_version(),
                "cpu_count": os.cpu_count(),
            },
            "engine": face_engine.engine_info(),
            "enrolled_labels": enrolled_labels,
            "dataset": dataset_profile(),
            "operation_timings_ms": timings,
            "page_timings_ms": page_rows,
            "verification": verification_statistics(),
        }

    out = os.path.join(os.path.dirname(__file__), "..", "docs", "benchmark_results.json")
    with open(os.path.abspath(out), "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(json.dumps(report, indent=2))
    print(f"\nWrote {os.path.abspath(out)}")


if __name__ == "__main__":
    main()
