"""Camera source resolution and the offline upload queue."""

import cctv_engine
import sync_engine
from database import db
from models import CCTVFeed, OfflineSyncQueue


def test_registered_feeds_become_watchable_sources(app_context):
    db.session.add(CCTVFeed(camera_name="North Gate", camera_location="Gate 1",
                            rtsp_url="rtsp://10.0.0.5:554/stream1", status="online"))
    db.session.commit()

    sources = cctv_engine.get_camera_sources()
    names = [s["name"] for s in sources]

    assert "North Gate" in names
    entry = next(s for s in sources if s["name"] == "North Gate")
    assert entry["type"] == "rtsp"
    assert entry["source"] == "rtsp://10.0.0.5:554/stream1"


def test_inactive_feeds_are_left_out_of_the_live_views(app_context):
    db.session.add(CCTVFeed(camera_name="Broken Camera", rtsp_url="rtsp://10.0.0.9/stream",
                            status="inactive"))
    db.session.commit()

    names = [s["name"] for s in cctv_engine.get_camera_sources()]

    assert "Broken Camera" not in names


def test_the_primary_feed_is_used_for_attendance(app_context):
    CCTVFeed.query.update({CCTVFeed.is_primary: False})
    db.session.add(CCTVFeed(camera_name="Clock-In Terminal", rtsp_url="rtsp://10.0.0.7/stream",
                            status="online", is_primary=True))
    db.session.commit()

    assert cctv_engine.primary_source()["name"] == "Clock-In Terminal"


def test_source_coercion_handles_indexes_urls_and_builtin(app_context):
    assert cctv_engine.coerce_source("0") == 0
    assert cctv_engine.coerce_source("builtin://1") == 1
    assert cctv_engine.coerce_source("rtsp://host/stream") == "rtsp://host/stream"


def test_a_camera_list_is_never_empty(app_context):
    CCTVFeed.query.delete()
    db.session.commit()

    sources = cctv_engine.get_camera_sources()

    assert len(sources) >= 1
    assert sources[0]["type"] == "builtin"


def test_failed_uploads_are_queued_rather_than_lost(app_context):
    stored, note = sync_engine.upload_or_queue("/tmp/does-not-exist.jpg",
                                              "captures/does-not-exist.jpg",
                                              snapshot_id=None, worker_id=None)

    assert stored == "captures/does-not-exist.jpg"     # the local path is kept
    assert note == "not_configured"
    queued = OfflineSyncQueue.query.one()
    assert queued.operation_type == "snapshot_upload"
    assert queued.sync_status == "pending"


def test_draining_without_configuration_reports_it_and_keeps_the_queue(app_context):
    sync_engine.enqueue("snapshot_upload", {"local_path": "captures/x.jpg"})

    outcome = sync_engine.drain("/tmp")

    assert outcome["reason"] == "not_configured"
    assert outcome["skipped"] == 1
    assert OfflineSyncQueue.query.filter_by(sync_status="pending").count() == 1


def test_queue_stats_summarise_the_pipeline(app_context):
    sync_engine.enqueue("snapshot_upload", {"local_path": "captures/a.jpg"})
    sync_engine.track("event_snapshots", 1, "pending")

    stats = sync_engine.queue_stats()

    assert stats["pending"] == 1
    assert stats["tracked"] == 1
    assert stats["configured"] is False


def test_tracking_the_same_record_twice_updates_it(app_context):
    sync_engine.track("event_snapshots", 5, "pending")
    sync_engine.track("event_snapshots", 5, "synced", cloud_record_id="https://example/x.jpg")

    from models import CloudSyncMetadata
    row = CloudSyncMetadata.query.filter_by(table_name="event_snapshots", record_id=5).one()
    assert row.cloud_status == "synced"
    assert row.synced_at is not None


# ---------------------------------------------------------------------------
# Sweeping a machine for cameras
#
# probe_source() is what tools/list_cameras.py uses to find a phone attached as
# a system camera. It is called in a loop over indices that mostly do not
# exist, so the contract that matters is that it always answers and never
# raises - a probe that throws is useless to a caller that is guessing.
# ---------------------------------------------------------------------------

def test_probing_a_source_that_does_not_exist_answers_rather_than_raises(app_context):
    result = cctv_engine.probe_source(99)

    assert result["opened"] is False
    assert result["read_ok"] is False
    assert result["error"]


def test_probing_an_unreachable_url_answers_rather_than_raises(app_context):
    """A wrong RTSP address is a normal typo, not an exceptional condition."""
    result = cctv_engine.probe_source("rtsp://192.0.2.1:554/does-not-exist")

    assert result["read_ok"] is False
    assert result["source"] == "rtsp://192.0.2.1:554/does-not-exist"


def test_a_probe_always_returns_the_full_shape(app_context):
    """The reporting tool formats every field, so every field must be present."""
    result = cctv_engine.probe_source(99)

    for key in ("source", "opened", "read_ok", "width", "height",
                "fps", "elapsed_ms", "error"):
        assert key in result, f"probe_source() dropped {key}"


def test_a_probe_survives_a_camera_that_explodes(app_context, monkeypatch):
    """A backend that raises on read must not stop the sweep.

    Exactly this happens on a machine where an index exists but the device
    behind it has been unplugged: the open succeeds and the read throws.
    """
    class Exploding:
        def isOpened(self): return True
        def read(self): raise RuntimeError("device disappeared")
        def get(self, _prop): return 0.0
        def release(self): pass

    monkeypatch.setattr(cctv_engine, "open_camera", lambda _source: Exploding())
    result = cctv_engine.probe_source(0)

    assert result["read_ok"] is False
    assert "device disappeared" in result["error"]


def test_the_probe_does_not_touch_the_database(app_context):
    """Unlike probe_feed(), this one is for machines with nothing registered."""
    from models import HardwareHealthLog

    before = HardwareHealthLog.query.count()
    cctv_engine.probe_source(99)

    assert HardwareHealthLog.query.count() == before


def test_a_phone_sized_frame_is_called_out_as_such(app_context):
    """Resolution is how an operator tells a phone from a laptop webcam."""
    import importlib.util
    import os as _os

    spec = importlib.util.spec_from_file_location(
        "list_cameras", _os.path.join(_os.path.dirname(_os.path.dirname(__file__)),
                                      "tools", "list_cameras.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "phone" in module._guess(1920, 1080)
    assert "laptop" in module._guess(1280, 720)
    assert module._guess(0, 0) == ""
