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
