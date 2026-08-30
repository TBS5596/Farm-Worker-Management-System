/**
 * audit-log-page.js - the audit trail table.
 *
 * Columns: 0 Timestamp, 1 Username, 2 Action, 3 Details, 4 IP address.
 *
 * Newest first, 25 to a page because this is the table people scan rather than
 * read. Details is free text of varying length, so it is not sortable.
 *
 * Searching is the main use: typing "attendance.rejected" shows every refused
 * clock-in, and "payroll.generate" shows who ran payroll and when.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#auditTable', {
    order: [[0, 'desc']],
    pageLength: 25,
    columnDefs: [{ orderable: false, targets: 3 }],
    language: { search: 'Search log:' },
  });
});
