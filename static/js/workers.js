/**
 * workers.js - the Workers roster table.
 *
 * Column order, which the DataTables options below refer to by index:
 *
 *   0 Worker ID   1 Name        2 NRC        3 Phone      4 Emergency
 *   5 Department  6 Address     7 Rate/hr    8 Face       9 Status
 *  10 Enrolled   11 Registered  12 Actions
 *
 * When worker cards are switched on, a Card column appears at index 12 and
 * Actions moves to 13. Rather than hard-code either arrangement, the last
 * column is located from the table itself - so turning cards on or off in
 * Settings cannot leave this file describing a layout that no longer exists.
 */
document.addEventListener('DOMContentLoaded', function () {
  var table = document.getElementById('workersTable');
  var lastColumn = table.querySelectorAll('thead th').length - 1;

  FMSUI.initDataTable('#workersTable', {
    order: [[11, 'desc']],  // newest registration first
    pageLength: 10,
    // The last column holds buttons, not data - sorting it is meaningless.
    columnDefs: [{ orderable: false, targets: lastColumn }],
    language: { search: 'Search workers:' },
  });

  // --- Card selection --------------------------------------------------- //
  // The checkbox lives inside the Worker ID cell rather than in a column of
  // its own, so that adding it did not shift every DataTables column index.
  var countBadge = document.getElementById('selectedCardCount');
  var printSelected = document.getElementById('printSelectedCards');

  function selectedIds() {
    // Query the table element, not the visible page: DataTables detaches rows
    // for other pages from the DOM, and a supervisor who ticks four workers on
    // page one and two on page two expects all six to print.
    return Array.prototype.slice
      .call(table.querySelectorAll('.card-pick'))
      .filter(function (box) { return box.checked; })
      .map(function (box) { return box.value; });
  }

  function refreshCount() {
    if (countBadge) { countBadge.textContent = String(selectedIds().length); }
  }

  if (countBadge || printSelected) {
    table.addEventListener('change', function (event) {
      if (event.target && event.target.classList.contains('card-pick')) { refreshCount(); }
    });
    refreshCount();
  }

  if (printSelected) {
    printSelected.addEventListener('click', function (event) {
      event.preventDefault();
      var ids = selectedIds();
      if (!ids.length) {
        window.alert('Tick the workers whose cards you want to print first. '
                   + 'Workers without an active card cannot be selected.');
        return;
      }
      var query = ids.map(function (id) { return 'id=' + encodeURIComponent(id); }).join('&');
      window.open('/workers/cards?' + query, '_blank');
    });
  }

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
