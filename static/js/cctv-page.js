/**
 * cctv-page.js - the two tables on the CCTV page.
 *
 * Feeds table columns:
 *   0 ID  1 Name  2 Location  3 Source  4 Status  5 Role  6 Heartbeat  7 Actions
 *
 * Recordings table columns:
 *   0 ID  1 Camera  2 Trigger  3 Start  4 Length  5 Size  6 Attendance  7 Watch
 *
 * Both default to ID descending, so the newest feed and the most recent clip
 * are at the top. The live camera views above the tables are plain <img>
 * elements streaming MJPEG and need no JavaScript.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#feedsTable', {
    order: [[0, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 7 }],
  });

  FMSUI.initDataTable('#recordingsTable', {
    order: [[0, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 7 }],  // the "Watch" link
  });
});
