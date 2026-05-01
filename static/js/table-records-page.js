document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#recordsTable', {
    order: [[0, 'desc']],
    pageLength: 20,
  });
});
