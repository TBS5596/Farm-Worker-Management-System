/**
 * payroll-page.js - the Payroll records table.
 *
 * Column order:
 *   0 ID     1 Worker  2 Week Ending  3 Hours  4 OT     5 Rate
 *   6 Gross  7 NAPSA   8 NHIMA        9 Net   10 Source 11 Status
 *  12 Paid On  13 Actions
 *
 * Sorted by week ending descending: the week you are about to pay is at the
 * top. "Source" distinguishes rows generated from recorded attendance from
 * hand-entered corrections.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#payrollTable', {
    order: [[2, 'desc']],
    pageLength: 10,
    columnDefs: [{ orderable: false, targets: 13 }],
    language: { search: 'Search payroll:' },
  });
});
