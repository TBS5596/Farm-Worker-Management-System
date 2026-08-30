/**
 * login.js - the public clock-in and sign-in page.
 *
 * Two small jobs:
 *
 *   1. Keep the right tab open after a POST. The page re-renders on every
 *      submission (to show the flash message), which resets the tabs to the
 *      worker view. `?tab=admin` reopens the admin pane instead.
 *
 *   2. Capture the worker's coordinates into hidden fields before submission,
 *      so the server can measure how far they are from the farm.
 *
 * On the geolocation: it is corroboration, not proof - the browser reports
 * whatever it likes. The server records the distance on every punch, and only
 * refuses a punch when geofence enforcement is switched on in Settings. If the
 * worker denies permission or the lookup times out, the fields are left empty
 * and the punch still records; the Attendance page simply shows no location.
 */
document.addEventListener('DOMContentLoaded', function () {

  // --- 1. Reopen the admin tab when the URL asks for it --------------------
  (function () {
    var url = new URL(window.location.href);
    var tab = url.searchParams.get('tab');
    if (tab === 'admin') {
      var trigger = document.getElementById('admin-tab');
      if (trigger && typeof bootstrap !== 'undefined') {
        bootstrap.Tab.getOrCreateInstance(trigger).show();
      }
    }
  })();

  // --- 2. Fill the hidden latitude and longitude fields -------------------
  (function () {
    var latEl = document.getElementById('workerLatitude');
    var lonEl = document.getElementById('workerLongitude');

    // Older browsers, or a page served over plain HTTP from another machine,
    // may not offer geolocation at all. Not an error: the punch still works.
    if (!latEl || !lonEl || !navigator.geolocation) {
      return;
    }

    navigator.geolocation.getCurrentPosition(
      function (pos) {
        // Example values on a Zambian farm: -15.4067, 28.2871
        latEl.value = String(pos.coords.latitude);
        lonEl.value = String(pos.coords.longitude);
      },
      function () {
        // Permission denied, unavailable, or timed out. Send nothing rather
        // than a stale or wrong position.
        latEl.value = '';
        lonEl.value = '';
      },
      {
        enableHighAccuracy: true, // worth the extra second: the geofence is metres, not kilometres
        timeout: 5000,            // never make a worker wait at the terminal
        maximumAge: 60000,        // a fix from the last minute is good enough
      }
    );
  })();
});
