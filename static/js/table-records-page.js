/**
 * table-records-page.js - the Data Hub's generic table browser.
 *
 * One template and one script serve every table in the schema
 * (/tables-hub/<key>), so nothing here can assume particular columns. Column 0
 * is always the primary key, which is why that is the only sort specified:
 * descending gives newest-first for every table.
 *
 * Example: /tables-hub/biometric-transactions lists every verification
 * attempt, newest first, 20 to a page.
 */
document.addEventListener('DOMContentLoaded', function () {
  FMSUI.initDataTable('#recordsTable', {
    order: [[0, 'desc']],
    pageLength: 20,
  });
});
