document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#auditTable', {
    order: [[0, 'desc']],
    pageLength: 25,
    columnDefs: [{ orderable: false, targets: 3 }],
    language: { search: 'Search log:' },
  });
});
