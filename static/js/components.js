(function (window) {
  function initDataTable(selector, options) {
    if (typeof DataTable === 'undefined') {
      return null;
    }
    var tableEl = document.querySelector(selector);
    if (!tableEl) {
      return null;
    }
    return new DataTable(selector, options || {});
  }

  function onDelegatedClick(selector, handler) {
    document.addEventListener('click', function (e) {
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
