/**
 * components.js - the two helpers every admin page shares.
 *
 * Loaded before any page-specific script, and exposed as the global `FMSUI`.
 *
 * Why these two in particular:
 *
 *   initDataTable  Every table page needs the same DataTables setup, and each
 *                  needs to survive the table simply not being there (an empty
 *                  Workers list still renders the page, and the Data Hub
 *                  reuses one template for eleven different tables).
 *
 *   onDelegatedClick
 *                  DataTables removes rows from the DOM when you page through
 *                  a table, so a listener attached directly to a button on
 *                  page 1 is gone by page 2. Listening on `document` and
 *                  matching with closest() keeps the buttons working on every
 *                  page. This was a real bug: "Reset PIN" worked only for the
 *                  first ten workers.
 */
(function (window) {
  /**
   * Create a DataTable if both the library and the table are present.
   *
   * Example:
   *   FMSUI.initDataTable('#workersTable', {
   *     order: [[11, 'desc']],                        // newest registration first
   *     columnDefs: [{ orderable: false, targets: 12 }], // the actions column
   *   });
   *
   * @param {string} selector  CSS selector for the <table> element.
   * @param {object} [options] DataTables options.
   * @returns {object|null} the DataTable instance, or null if it was skipped.
   */
  function initDataTable(selector, options) {
    // The CDN can be blocked or offline - the page must still work, just
    // without search and paging.
    if (typeof DataTable === 'undefined') {
      return null;
    }
    var tableEl = document.querySelector(selector);
    if (!tableEl) {
      return null;
    }
    return new DataTable(selector, options || {});
  }

  /**
   * Run a handler when a click lands on `selector` or anything inside it.
   *
   * Example - filling the reset-PIN modal from the clicked row's data
   * attributes, whichever page of the table that row is on:
   *   FMSUI.onDelegatedClick('.reset-pin-btn', function (btn) {
   *     document.getElementById('resetPinForm').action =
   *       '/workers/' + btn.dataset.workerId + '/reset-pin';
   *   });
   *
   * @param {string} selector CSS selector for the element of interest.
   * @param {function(Element, Event)} handler receives the matched element.
   */
  function onDelegatedClick(selector, handler) {
    document.addEventListener('click', function (e) {
      // closest() matches the element itself or an ancestor, so a click on the
      // <i> icon inside a button still resolves to the button.
      var target = e.target.closest(selector);
      if (target) {
        handler(target, e);
      }
    });
  }

  window.FMSUI = Object.assign(window.FMSUI || {}, {
    initDataTable: initDataTable,
    onDelegatedClick: onDelegatedClick,
  });
})(window);
