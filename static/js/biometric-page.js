document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#devicesTable', {
    order: [[0, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 8 }],
  });
});
