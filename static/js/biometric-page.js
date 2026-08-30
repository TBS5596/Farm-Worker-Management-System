/**
 * biometric-page.js - the enrolment centre.
 *
 * Two things here:
 *
 *   1. DataTables on the registered-devices table at the bottom of the page.
 *      Columns: 0 ID, 1 Name, 2 Serial, 3 Type, 4 IP, 5 USB Port, 6 Status,
 *      7 Location, 8 Actions.
 *
 *   2. The photo-upload modal. The worker list above uses live camera capture
 *      by default (the green button posts straight to the enrolment route with
 *      no JavaScript involved), but a supervisor without a camera to hand can
 *      enrol from photographs instead. This points the shared upload form at
 *      the right worker.
 *
 * The worker-enrolment table itself is deliberately not a DataTable: it scrolls
 * inside its card so the live camera preview stays beside it, and paging would
 * hide exactly the person standing in front of the camera.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#devicesTable', {
    order: [[0, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 8 }],
  });

  // Example: clicking upload on Natasha Sikapula's row (worker pk 2) points the
  // form at /workers/2/face/enroll and names her in the modal title.
  FMSUI.onDelegatedClick('.upload-face-btn', function (btn) {
    document.getElementById('uploadFaceForm').action =
      '/workers/' + btn.dataset.workerPk + '/face/enroll';
    document.getElementById('uploadFaceWorkerName').textContent =
      btn.dataset.workerName || '-';
  });
});
