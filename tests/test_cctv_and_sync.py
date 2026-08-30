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
