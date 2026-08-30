/**
 * workers.js - the Workers roster table.
 *
 * Column order, which the DataTables options below refer to by index:
 *
 *   0 Worker ID   1 Name        2 NRC        3 Phone      4 Emergency
 *   5 Department  6 Address     7 Rate/hr    8 Face       9 Status
 *  10 Enrolled   11 Registered  12 Actions
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#workersTable', {
    order: [[11, 'desc']],  // newest registration first
    pageLength: 10,
    // Column 12 holds buttons, not data - sorting it is meaningless.
    columnDefs: [{ orderable: false, targets: 12 }],
    language: { search: 'Search workers:' },
  });

  // Delegated so the button keeps working on pages 2, 3, ... of the table.
  // Example: clicking reset on worker 0007 points the form at
  // /workers/7/reset-pin and names the worker in the modal.
  FMSUI.onDelegatedClick('.reset-pin-btn', function (resetBtn) {
    document.getElementById('resetPinForm').action =
      '/workers/' + resetBtn.dataset.workerId + '/reset-pin';
    document.getElementById('resetPinWorkerName').textContent = resetBtn.dataset.workerName;
    document.getElementById('resetPinWorkerCode').textContent = resetBtn.dataset.workerCode;
  });
});
