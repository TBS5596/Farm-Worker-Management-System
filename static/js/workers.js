document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#workersTable', {
    order: [[9, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 10 }],
    language: { search: 'Search workers:' },
  });

  // Event delegation handles buttons on all DataTables pages, not just the first.
  FMSUI.onDelegatedClick('.reset-pin-btn', function (resetBtn) {
    document.getElementById('resetPinForm').action = '/workers/' + resetBtn.dataset.workerId + '/reset-pin';
    document.getElementById('resetPinWorkerName').textContent = resetBtn.dataset.workerName;
    document.getElementById('resetPinWorkerCode').textContent = resetBtn.dataset.workerCode;
  });
});
