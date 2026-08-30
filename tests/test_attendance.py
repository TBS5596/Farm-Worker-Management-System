"""The clock-in pipeline: verification, session rules and geofencing."""

from datetime import datetime

import numpy as np

import attendance_service
import geofence
from database import db
from models import Attendance, BiometricTransaction, EventSnapshot


def _frames(count=3):
    return [np.full((240, 320, 3), 120, dtype=np.uint8) for _ in range(count)]


def test_clock_in_is_refused_when_the_face_is_not_enrolled(app_context, make_worker, setting):
    setting("face_verification_required", "on")
    worker = make_worker(name="Unenrolled", pin="1234")

    outcome = attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())

    assert outcome["ok"] is False
    assert outcome["code"] == "worker_not_enrolled"
    assert Attendance.query.count() == 0


def test_every_verification_attempt_is_logged(app_context, make_worker, setting):
    setting("face_verification_required", "on")
    worker = make_worker(name="Unenrolled", pin="1234")

    attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())

    transaction = BiometricTransaction.query.one()
    assert transaction.success is False
    assert transaction.worker_id == worker.id
    assert transaction.modality == "face"
    assert transaction.error_message == "worker_not_enrolled"


def test_clock_in_records_a_session_and_a_snapshot(app_context, make_worker, setting):
    setting("face_verification_required", "off")   # no camera in the test environment
    setting("clip_recording_enabled", "off")
    worker = make_worker(name="Picker", pin="1234")

    outcome = attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())

    assert outcome["ok"] is True
    row = Attendance.query.one()
    assert row.worker_id == worker.id
    assert row.check_out_time is None
    assert row.verified_by_cctv is True
    assert EventSnapshot.query.filter_by(attendance_id=row.attendance_id).count() == 1


def test_clocking_in_twice_is_refused(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    worker = make_worker(name="Picker", pin="1234")

    attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())
    second = attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())

    assert second["ok"] is False
    assert second["code"] == "already_clocked_in"
    assert Attendance.query.count() == 1


def test_clock_out_closes_the_open_session(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    worker = make_worker(name="Picker", pin="1234")
    attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())

    outcome = attendance_service.record_punch(app_context, worker, "OUT", None, None, frames=_frames())

    assert outcome["ok"] is True
    row = Attendance.query.one()
    assert row.check_out_time is not None


def test_clock_out_without_an_open_session_is_refused(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    worker = make_worker(name="Picker", pin="1234")

    outcome = attendance_service.record_punch(app_context, worker, "OUT", None, None, frames=_frames())

    assert outcome["ok"] is False
    assert outcome["code"] == "no_open_session"


def test_geofence_records_distance_without_enforcing_it(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    setting("farm_latitude", "-15.4067")
    setting("farm_longitude", "28.2871")
    setting("geofence_radius_m", "500")
    setting("geofence_enforce", "off")
    worker = make_worker(name="Picker", pin="1234")

    # Roughly 3 km away.
    outcome = attendance_service.record_punch(app_context, worker, "IN", -15.4340, 28.2871,
                                             frames=_frames())

    assert outcome["ok"] is True
    row = Attendance.query.one()
    assert row.within_geofence is False
    assert row.distance_from_farm_m > 2000


def test_geofence_refuses_a_distant_punch_when_enforced(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    setting("farm_latitude", "-15.4067")
    setting("farm_longitude", "28.2871")
    setting("geofence_radius_m", "500")
    setting("geofence_enforce", "on")
    worker = make_worker(name="Picker", pin="1234")

    outcome = attendance_service.record_punch(app_context, worker, "IN", -15.4340, 28.2871,
                                             frames=_frames())

    assert outcome["ok"] is False
    assert outcome["code"] == "outside_geofence"
    assert Attendance.query.count() == 0


def test_geofence_accepts_a_punch_inside_the_radius(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    setting("farm_latitude", "-15.4067")
    setting("farm_longitude", "28.2871")
    setting("geofence_enforce", "on")
    worker = make_worker(name="Picker", pin="1234")

    outcome = attendance_service.record_punch(app_context, worker, "IN", -15.4069, 28.2873,
                                             frames=_frames())

    assert outcome["ok"] is True
    assert Attendance.query.one().within_geofence is True


def test_geofence_evaluation_reports_an_unconfigured_farm(app_context, setting):
    setting("farm_latitude", "")
    setting("farm_longitude", "")

    result = geofence.evaluate(-15.4, 28.3)

    assert result["configured"] is False
    assert result["within"] is None


def test_clock_in_updates_the_daily_summary(app_context, make_worker, setting):
    setting("face_verification_required", "off")
    setting("clip_recording_enabled", "off")
    worker = make_worker(name="Picker", pin="1234")

    attendance_service.record_punch(app_context, worker, "IN", None, None, frames=_frames())
    attendance_service.record_punch(app_context, worker, "OUT", None, None, frames=_frames())

    from models import DailyAttendanceSummary
    summary = DailyAttendanceSummary.query.filter_by(worker_id=worker.id).one()
    assert summary.sessions_count == 1
    assert summary.check_out_time is not None
