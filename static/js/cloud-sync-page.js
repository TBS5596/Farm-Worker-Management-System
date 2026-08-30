/**
 * cloud-sync-page.js - the two tables on the Cloud Sync page.
 *
 *   #metadataTable  per-record sync state (cloud_sync_metadata): which
 *                   snapshots have reached Firebase and when.
 *   #queueTable     the offline queue (offline_sync_queue): uploads that failed
 *                   because the link was down, with their retry count and last
 *                   error. On a remote farm this table filling up and then
 *                   draining is the normal daily rhythm.
 *
 * Both newest-first, since a problem is always at the top.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#metadataTable', {
    order: [[0, 'desc']],
    pageLength: 10,
  });

  FMSUI.initDataTable('#queueTable', {
    order: [[0, 'desc']],
    pageLength: 10,
  });
});
