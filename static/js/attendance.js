document.addEventListener('DOMContentLoaded', function () {
  new DataTable('#attendanceTable', {
    order: [[2, 'desc']],
    pageLength: 15,
    columnDefs: [{ orderable: false, targets: [4, 6] }],
    language: { search: 'Search records:' },
  });

  document.addEventListener('click', function (e) {
    const thumb = e.target.closest('[data-bs-target="#photoModal"]');
    if (!thumb) return;
    document.getElementById('photoModalImg').src = thumb.dataset.src || '';
    document.getElementById('photoModalLabel').textContent = thumb.dataset.label || 'Captured Photo';
  });

  document.getElementById('photoModal')?.addEventListener('hidden.bs.modal', function () {
    document.getElementById('photoModalImg').src = '';
  });
});
