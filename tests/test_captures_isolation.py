"""A test run must never write into the project's own captures directory.

This is a privacy test, not a tidiness one. test_real_face.py enrols a real
photograph through the actual HTTP endpoint; if that write lands in the
project's captures/faces/, it overwrites a demo worker's enrolment crops and
the face of a real person is then printed on that worker's identity card and
published in the report.
"""
import os
import paths
import app as app_module
import face_engine


def test_no_module_still_points_at_the_project_captures_directory():
    project = os.path.abspath(os.path.join(os.path.dirname(paths.__file__), "captures"))
    for module in (paths, app_module, face_engine):
        for name in ("CAPTURES_DIR", "FACES_DIR", "CLIPS_DIR"):
            value = getattr(module, name, None)
            if value is None:
                continue
            assert not os.path.abspath(value).startswith(project), (
                f"{module.__name__}.{name} still points inside the project's "
                f"captures directory ({value}); a test that enrols a face "
                f"would write a real photograph there")


def test_enrolling_through_the_route_writes_only_to_the_temporary_tree(
        client, signed_in, make_worker, tmp_path):
    before = set()
    project_faces = os.path.abspath(os.path.join(
        os.path.dirname(paths.__file__), "captures", "faces"))
    if os.path.isdir(project_faces):
        before = set(os.listdir(project_faces))

    worker = make_worker(name="Enrolment Target", pin="1234")
    import numpy as np, cv2
    frame = np.full((480, 640, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    client.post(f"/workers/{worker.id}/face/enroll",
                data={"image_data": "data:image/jpeg;base64," +
                      __import__("base64").b64encode(buf.tobytes()).decode()},
                follow_redirects=True)

    after = set(os.listdir(project_faces)) if os.path.isdir(project_faces) else set()
    assert after == before, f"the enrolment route wrote into {project_faces}: {after - before}"
