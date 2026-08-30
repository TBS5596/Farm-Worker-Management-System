/**
 * attendance.js - the Attendance table and its photo viewer.
 *
 * Column order:
 *   0 Worker ID  1 Name      2 Date      3 Clock In  4 In Photo   5 Clock Out
 *   6 Out Photo  7 Hours     8 Identity  9 Location 10 Clip      11 Status
 *
 * Sorting defaults to date descending so today's sessions are at the top,
 * which is what a supervisor opens the page to see.
 */
document.addEventListener('DOMContentLoaded', function () {
  new DataTable('#attendanceTable', {
    order: [[2, 'desc']],
    pageLength: 15,
    // Photos (4, 6) and the clip link (10) are images and buttons, not sortable
    // values. Date, time and hours columns carry data-order attributes in the
    // template so they sort chronologically rather than alphabetically -
    // otherwise "9.50" would sort after "10.00" and 07:00 after 15:00.
    columnDefs: [{ orderable: false, targets: [4, 6, 10] }],
    language: { search: 'Search records:' },
  });

  // Clicking a thumbnail opens the full-size snapshot. Delegated because
  // DataTables replaces the rows on every page change and every search.
  document.addEventListener('click', function (e) {
    const thumb = e.target.closest('[data-bs-target="#photoModal"]');
    if (!thumb) return;
    // The template puts the full-size URL and a caption on the thumbnail, e.g.
    // data-label="Musonda Banda - Clock In 27 Aug 2026".
    document.getElementById('photoModalImg').src = thumb.dataset.src || '';
    document.getElementById('photoModalLabel').textContent =
      thumb.dataset.label || 'Captured Photo';
  });

  // Clear the src on close: otherwise the previous worker's face flashes up for
  // a moment the next time the modal opens.
  document.getElementById('photoModal')?.addEventListener('hidden.bs.modal', function () {
    document.getElementById('photoModalImg').src = '';
  });
});
