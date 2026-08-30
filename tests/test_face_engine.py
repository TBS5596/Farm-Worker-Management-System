"""Identity matching: the check that makes attendance attributable."""

import numpy as np

import face_engine
from database import db
from models import FaceTemplate


def _synthetic_face(seed: int):
    """A deterministic 200x200 grayscale pattern standing in for a face crop.

    Detection is not exercised here - these tests pin down the matching and
    storage logic, which is what decides whether a punch is accepted.
    """
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 60, size=face_engine.FACE_SIZE, dtype=np.uint8)
    gradient = np.linspace(40 + seed * 20, 200 - seed * 10, face_engine.FACE_SIZE[0], dtype=np.uint8)
    return np.clip(base + gradient[None, :], 0, 255).astype(np.uint8)


def _enrol_directly(worker, crops):
    for index, crop in enumerate(crops, start=1):
        db.session.add(FaceTemplate(
            worker_id=worker.id,
            face_embedding=face_engine._encode(crop),
            algorithm="LBPH",
            sample_index=index,
            quality_score=100.0,
        ))
    db.session.commit()
    face_engine.invalidate()


def test_template_round_trip_preserves_the_crop():
    crop = _synthetic_face(1)

    restored = face_engine._decode(face_engine._encode(crop))

    assert restored.shape == (face_engine.FACE_SIZE[1], face_engine.FACE_SIZE[0])
    assert np.array_equal(restored, crop)


def test_decode_rejects_a_blob_of_the_wrong_size():
    assert face_engine._decode(b"too-short") is None
    assert face_engine._decode(b"") is None


def test_unenrolled_worker_cannot_be_verified(app_context, make_worker):
    worker = make_worker(name="Not Enrolled", pin="1234")

    result = face_engine.verify_worker(worker.id, [np.zeros((240, 320, 3), dtype=np.uint8)])

    assert result["matched"] is False
    assert result["reason"] == face_engine.NOT_ENROLLED


def test_sample_counts_report_enrolment_progress(app_context, make_worker):
    worker = make_worker(name="Enrolled", pin="1234")
    _enrol_directly(worker, [_synthetic_face(2), _synthetic_face(2)])

    assert face_engine.sample_count_for(worker.id) == 2
    assert face_engine.sample_counts()[worker.id] == 2


def test_matcher_recognises_the_enrolled_worker(app_context, make_worker):
    worker = make_worker(name="Enrolled", pin="1234")
    crop = _synthetic_face(3)
    _enrol_directly(worker, [crop, crop])

    model, labels = face_engine._ensure_model()
    label, score = face_engine._predict(model, crop)

    assert worker.id in labels
    assert label == worker.id
    assert score > 35.0


def test_matcher_separates_two_different_workers(app_context, make_worker):
    first = make_worker(name="First", pin="1111")
    second = make_worker(name="Second", pin="2222")
    _enrol_directly(first, [_synthetic_face(4)])
    _enrol_directly(second, [_synthetic_face(9)])

    model, _labels = face_engine._ensure_model()
    label_first, _ = face_engine._predict(model, _synthetic_face(4))
    label_second, _ = face_engine._predict(model, _synthetic_face(9))

    assert label_first == first.id
    assert label_second == second.id


def test_clearing_templates_removes_enrolment(app_context, make_worker):
    worker = make_worker(name="Enrolled", pin="1234")
    _enrol_directly(worker, [_synthetic_face(5)])

    removed = face_engine.clear_templates(worker)

    assert removed == 1
    assert face_engine.sample_count_for(worker.id) == 0
    assert worker.face_enrolled_at is None


def test_model_retrains_when_templates_change(app_context, make_worker):
    worker = make_worker(name="Enrolled", pin="1234")
    _enrol_directly(worker, [_synthetic_face(6)])
    _model, labels_before = face_engine._ensure_model()

    second = make_worker(name="Second", pin="2222")
    _enrol_directly(second, [_synthetic_face(7)])
    _model, labels_after = face_engine._ensure_model()

    assert labels_before == {worker.id}
    assert labels_after == {worker.id, second.id}


def test_engine_reports_which_recognizer_is_in_use():
    info = face_engine.engine_info()

    assert info["algorithm"] in ("LBPH", "correlation-fallback")
    assert info["face_size"] == "200x200"
