document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#feedsTable', {
    order: [[0, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 6 }],
  });

  FMSUI.initDataTable('#recordingsTable', {
    order: [[0, 'desc']],
    pageLength: 10,
  });
});
