"""Identity verification against a real photograph.

The other face tests use deterministic synthetic patterns, which pin down the
storage and matching logic but never touch face *detection*. This test enrols a
real photograph through the actual HTTP enrolment endpoint and then checks the
decision that the whole project rests on: the same face is accepted for its own
Worker ID and refused when it claims someone else's.

It needs a real photograph, so it uses the one bundled with scikit-image and
skips when that package is not installed:

    pip install scikit-image
"""

import io

import cv2
import pytest

import face_engine

skimage_data = pytest.importorskip(
    "skimage.data", reason="scikit-image provides the sample photograph"
)


def _face_image():
    return cv2.cvtColor(skimage_data.astronaut(), cv2.COLOR_RGB2BGR)


def _variant(image, brightness=0, angle=0.0, scale=1.0):
    """Same person, slightly different capture conditions."""
    out = image.copy()
    if angle or scale != 1.0:
        height, width = out.shape[:2]
        matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, scale)
        out = cv2.warpAffine(out, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)
    if brightness:
        out = cv2.convertScaleAbs(out, alpha=1.0, beta=brightness)
    return out


def _upload(image, name):
    _ok, buffer = cv2.imencode(".jpg", image)
    return (io.BytesIO(buffer.tobytes()), name)


def _enrol_a_different_person(worker):
    """Give a second worker a template that is not the photographed face.

    Only one real photograph is available, so the "someone else" side of the
    comparison uses a deterministic synthetic pattern inserted directly.
    """
    import numpy as np

    from database import db
    from models import FaceTemplate

    rng = np.random.default_rng(11)
    pattern = rng.integers(0, 255, size=face_engine.FACE_SIZE, dtype=np.uint8)
    db.session.add(FaceTemplate(
        worker_id=worker.id,
        face_embedding=face_engine._encode(pattern),
        algorithm="LBPH",
        sample_index=1,
        quality_score=100.0,
    ))
    db.session.commit()
    face_engine.invalidate()


def test_a_real_face_is_detected_and_normalised():
    crop, quality, reason = face_engine.extract_face(_face_image())

    assert reason == ""
    assert crop.shape == (face_engine.FACE_SIZE[1], face_engine.FACE_SIZE[0])
    assert quality > 0


def test_enrolment_over_http_then_match_the_right_worker(client, signed_in, make_worker):
    signed_in("admin")
    worker = make_worker(name="Enrolled Worker", pin="1234")
    other = make_worker(name="Other Worker", pin="5678")
    _enrol_a_different_person(other)
    face = _face_image()

    response = client.post(
        f"/workers/{worker.id}/face/enroll",
        data={"photos": [
            _upload(_variant(face), "a.jpg"),
            _upload(_variant(face, brightness=18, angle=-4), "b.jpg"),
            _upload(_variant(face, brightness=-18, angle=5), "c.jpg"),
        ]},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert face_engine.sample_count_for(worker.id) == 3
    assert worker.face_enrolled_at is not None

    # A held-out capture of the same person, not one of the enrolled samples.
    probe = _variant(face, brightness=9, angle=-2, scale=1.03)

    accepted = face_engine.verify_worker(worker.id, [probe], threshold=35.0)
    assert accepted["matched"] is True, f"score {accepted['score']}"
    assert accepted["score"] >= 35.0

    # The same face claiming a different Worker ID is the buddy-punching case:
    # both workers are enrolled, but the face at the camera is not this one's.
    refused = face_engine.verify_worker(other.id, [probe], threshold=35.0)
    assert refused["matched"] is False
    assert refused["reason"] == face_engine.WRONG_WORKER
    assert refused["matched_worker_pk"] == worker.id


def test_identification_finds_the_enrolled_worker(client, signed_in, make_worker):
    signed_in("admin")
    worker = make_worker(name="Enrolled Worker", pin="1234")
    face = _face_image()

    client.post(
        f"/workers/{worker.id}/face/enroll",
        data={"photos": [_upload(_variant(face), "a.jpg"),
                         _upload(_variant(face, brightness=15), "b.jpg")]},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    outcome = face_engine.identify([_variant(face, brightness=7, angle=-1)], threshold=35.0)

    assert outcome["worker_pk"] == worker.id
    assert outcome["matched"] is True


def test_enrolment_rejects_an_image_with_no_face(client, signed_in, make_worker):
    signed_in("admin")
    worker = make_worker(name="No Face", pin="1234")
    import numpy as np
    blank = np.full((240, 320, 3), 200, dtype=np.uint8)

    client.post(
        f"/workers/{worker.id}/face/enroll",
        data={"photos": [_upload(blank, "blank.jpg")]},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert face_engine.sample_count_for(worker.id) == 0
