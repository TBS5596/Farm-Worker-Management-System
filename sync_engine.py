"""Offline-tolerant cloud sync.

A remote farm loses its link regularly, so an upload that fails must not lose
the record. Snapshots and clips that cannot reach Firebase are queued in
`offline_sync_queue` and retried later, and every attempt is tracked per record
in `cloud_sync_metadata`.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from database import db
from models import CloudSyncMetadata, EventSnapshot, OfflineSyncQueue, Setting

MAX_RETRIES = 5


def _setting(key: str, default: str = "") -> str:
    row = Setting.query.filter_by(key=key).first()
    return row.value if row and row.value else default


def is_configured() -> bool:
    """Firebase is usable only with a bucket and a real service-account JSON."""
    return bool(_setting("firebase_bucket") and _setting("firebase_credentials_json"))


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

def enqueue(operation_type: str, payload: dict, worker_id: int | None = None) -> OfflineSyncQueue:
    row = OfflineSyncQueue(
        worker_id=worker_id,
        operation_type=operation_type,
        payload=json.dumps(payload),
        sync_status="pending",
    )
    db.session.add(row)
    db.session.commit()
    return row


def track(table_name: str, record_id: int, status: str, cloud_record_id: str | None = None) -> None:
    row = CloudSyncMetadata.query.filter_by(table_name=table_name, record_id=record_id).first()
    if not row:
        row = CloudSyncMetadata(table_name=table_name, record_id=record_id)
        db.session.add(row)
    row.cloud_status = status
    row.last_sync_attempt = datetime.utcnow()
    if cloud_record_id:
        row.cloud_record_id = cloud_record_id
    if status == "synced":
        row.synced_at = datetime.utcnow()
    db.session.commit()


def queue_stats() -> dict:
    return {
        "pending": OfflineSyncQueue.query.filter_by(sync_status="pending").count(),
        "failed": OfflineSyncQueue.query.filter_by(sync_status="failed").count(),
        "synced": OfflineSyncQueue.query.filter_by(sync_status="synced").count(),
        "tracked": CloudSyncMetadata.query.count(),
        "configured": is_configured(),
    }


# ---------------------------------------------------------------------------
# Firebase upload
# ---------------------------------------------------------------------------

def upload_file(local_path: str) -> tuple[str | None, str]:
    """Upload one file to Firebase Storage.

    Returns (public_url, error). A missing configuration is not an error the
    user needs to see - it just means everything stays local.
    """
    bucket = _setting("firebase_bucket")
    credentials_json = _setting("firebase_credentials_json")
    if not bucket or not credentials_json:
        return None, "not_configured"
    if not os.path.exists(local_path):
        return None, "file_missing"

    try:
        import firebase_admin
        from firebase_admin import credentials as fb_credentials
        from firebase_admin import storage as fb_storage
    except ImportError:
        return None, "firebase_admin_not_installed"

    try:
        service_account = json.loads(credentials_json)
    except json.JSONDecodeError:
        return None, "credentials_not_valid_json"

    try:
        if not firebase_admin._apps:
            cred = fb_credentials.Certificate(service_account)
            firebase_admin.initialize_app(cred, {"storageBucket": bucket})
        bucket_obj = fb_storage.bucket()
        blob = bucket_obj.blob(f"captures/{os.path.basename(local_path)}")
        blob.upload_from_filename(local_path)
        blob.make_public()
        return blob.public_url, ""
    except Exception as exc:
        return None, str(exc)[:250]


def upload_or_queue(local_path: str, relative_path: str, snapshot_id: int | None = None,
                    worker_id: int | None = None) -> tuple[str, str]:
    """Try to upload; queue the work if it fails.

    Returns (path_to_store, note). On success the path is the public cloud URL;
    on failure it stays the local relative path, so the UI can always show the
    photograph and nothing is lost. `note` carries the reason, e.g.
    "not_configured" on a farm with no Firebase set up at all.
    """
    url, error = upload_file(local_path)
    if url:
        if snapshot_id:
            track("event_snapshots", snapshot_id, "synced", cloud_record_id=url)
        return url, ""

    enqueue("snapshot_upload", {
        "local_path": relative_path,
        "snapshot_id": snapshot_id,
        "reason": error,
    }, worker_id=worker_id)
    if snapshot_id:
        track("event_snapshots", snapshot_id, "pending")
    return relative_path, error


def drain(base_dir: str, limit: int = 25) -> dict:
    """Retry queued uploads. Safe to call from the UI or a scheduled job.

    Batched (25 by default) so a farm reconnecting after a week offline does not
    block the request for minutes. Each attempt increments retry_count and items
    past MAX_RETRIES are left alone, so one permanently broken file cannot stall
    the queue behind it.

    Returns {"attempted": 6, "synced": 5, "failed": 1, "skipped": 0,
             "reason": ""} - and with no configuration at all, reason
    "not_configured" and everything counted as skipped.
    """
    result = {"attempted": 0, "synced": 0, "failed": 0, "skipped": 0, "reason": ""}
    if not is_configured():
        result["reason"] = "not_configured"
        result["skipped"] = OfflineSyncQueue.query.filter_by(sync_status="pending").count()
        return result

    rows = (OfflineSyncQueue.query
            .filter(OfflineSyncQueue.sync_status.in_(["pending", "failed"]))
            .filter(OfflineSyncQueue.retry_count < MAX_RETRIES)
            .order_by(OfflineSyncQueue.sync_id.asc())
            .limit(limit).all())

    for row in rows:
        result["attempted"] += 1
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            row.sync_status = "failed"
            row.last_error = "payload_not_valid_json"
            result["failed"] += 1
            continue

        relative_path = payload.get("local_path", "")
        url, error = upload_file(os.path.join(base_dir, relative_path))
        row.retry_count = (row.retry_count or 0) + 1

        if url:
            row.sync_status = "synced"
            row.synced_at = datetime.utcnow()
            row.last_error = None
            result["synced"] += 1
            snapshot_id = payload.get("snapshot_id")
            if snapshot_id:
                snapshot = EventSnapshot.query.get(snapshot_id)
                if snapshot:
                    snapshot.cloud_url = url
                track("event_snapshots", snapshot_id, "synced", cloud_record_id=url)
        else:
            row.sync_status = "failed"
            row.last_error = error
            result["failed"] += 1

    db.session.commit()
    return result
