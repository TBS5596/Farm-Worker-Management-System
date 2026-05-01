document.addEventListener('DOMContentLoaded', function () {
  // Re-activate the correct tab when flash messages are shown after a POST.
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

  // Capture current GPS coordinates (if available) and submit as hidden inputs.
  (function () {
    var latEl = document.getElementById('workerLatitude');
    var lonEl = document.getElementById('workerLongitude');
    if (!latEl || !lonEl || !navigator.geolocation) {
      return;
    }

    navigator.geolocation.getCurrentPosition(
      function (pos) {
        latEl.value = String(pos.coords.latitude);
        lonEl.value = String(pos.coords.longitude);
      },
      function () {
        latEl.value = '';
        lonEl.value = '';
      },
      {
        enableHighAccuracy: true,
        timeout: 5000,
        maximumAge: 60000,
      }
    );
  })();
});
