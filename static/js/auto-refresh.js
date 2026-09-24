/**
 * auto-refresh.js - keep charted pages current without anyone pressing F5.
 *
 * A farm office leaves the dashboard open on a screen all day. Without this,
 * what it shows is whatever was true when somebody last loaded it, which is the
 * worst kind of wrong: confidently out of date.
 *
 * Three decisions worth knowing about.
 *
 *   A full page reload, not a partial update. Every charted page here is
 *   server-rendered, so a reload is one line and cannot drift out of step with
 *   the server the way a hand-written patch of the DOM can. The cost is a
 *   flicker every few minutes, which is cheaper than a subtle inconsistency.
 *
 *   Paused while the tab is hidden. Reloading a page nobody is looking at
 *   spends the farm host's CPU and, on a metered connection, its data. The
 *   timer resumes when the tab comes back, and reloads at once if the interval
 *   already elapsed while it was away.
 *
 *   The choice is remembered per browser, not per farm. One office screen may
 *   want thirty seconds while a manager's laptop wants nothing at all. The farm
 *   setting supplies the starting value; the selector overrides it locally.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'fms.autoRefreshSeconds';

  var OPTIONS = [
    { value: 0,    label: 'Off' },
    { value: 30,   label: '30 seconds' },
    { value: 60,   label: 'Every minute' },
    { value: 300,  label: 'Every 5 minutes' },
    { value: 900,  label: 'Every 15 minutes' },
  ];

  function readStored(fallback) {
    // Browser storage can throw in a private window or where site data is
    // blocked. A page that fails to load because of a preference would be a
    // poor trade, so every read and write is guarded.
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw === null) { return fallback; }
      var parsed = parseInt(raw, 10);
      return isNaN(parsed) ? fallback : parsed;
    } catch (err) {
      return fallback;
    }
  }

  function store(seconds) {
    try { window.localStorage.setItem(STORAGE_KEY, String(seconds)); } catch (err) { /* ignore */ }
  }

  function start() {
    var mount = document.getElementById('autoRefresh');
    if (!mount) { return; }

    var farmDefault = parseInt(mount.dataset.defaultSeconds || '0', 10);
    if (isNaN(farmDefault)) { farmDefault = 0; }

    var seconds = readStored(farmDefault);
    var timer = null;
    var dueAt = null;

    // --- the control ---------------------------------------------------
    var label = document.createElement('label');
    label.className = 'form-label visually-hidden';
    label.setAttribute('for', 'autoRefreshSelect');
    label.textContent = 'Refresh automatically';

    var select = document.createElement('select');
    select.id = 'autoRefreshSelect';
    select.className = 'form-select form-select-sm';
    select.setAttribute('aria-label', 'Refresh this page automatically');
    select.style.width = 'auto';

    OPTIONS.forEach(function (option) {
      var node = document.createElement('option');
      node.value = String(option.value);
      node.textContent = option.value === 0 ? 'Auto refresh: off'
                                            : 'Refresh: ' + option.label.toLowerCase();
      if (option.value === seconds) { node.selected = true; }
      select.appendChild(node);
    });

    var status = document.createElement('span');
    status.className = 'auto-refresh-status';
    status.setAttribute('aria-live', 'polite');

    mount.appendChild(label);
    mount.appendChild(select);
    mount.appendChild(status);

    // --- the timer -------------------------------------------------------
    function clear() {
      if (timer) { window.clearTimeout(timer); timer = null; }
      dueAt = null;
    }

    function schedule() {
      clear();
      if (!seconds) {
        status.textContent = '';
        return;
      }
      dueAt = Date.now() + seconds * 1000;
      status.textContent = 'updating every ' + describe(seconds);
      timer = window.setTimeout(function () {
        // Only reload a visible tab. A hidden one reloads when it returns.
        if (document.visibilityState === 'hidden') { return; }
        window.location.reload();
      }, seconds * 1000);
    }

    function describe(value) {
      var match = OPTIONS.filter(function (o) { return o.value === value; })[0];
      return match ? match.label.toLowerCase() : value + ' seconds';
    }

    select.addEventListener('change', function () {
      seconds = parseInt(select.value, 10) || 0;
      store(seconds);
      schedule();
    });

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState !== 'visible' || !seconds) { return; }
      // Away longer than the interval? The page is already stale; reload now
      // rather than making somebody wait a further full interval for it.
      if (dueAt !== null && Date.now() >= dueAt) {
        window.location.reload();
        return;
      }
      schedule();
    });

    schedule();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
