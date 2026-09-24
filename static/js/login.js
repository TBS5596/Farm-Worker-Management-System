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

/* --- Card scanning at the capture point ---------------------------------
 *
 * Two ways in, because a farm may have either or neither:
 *
 *   A USB scanner needs no code at all. It presents itself to the operating
 *   system as a keyboard, types the card value into whichever field has focus
 *   and presses Enter. The card field is autofocused for exactly that reason,
 *   and the Enter keypress is caught below so a scan moves to the PIN instead
 *   of submitting a form that has no PIN in it yet.
 *
 *   The camera path uses the browser's built-in BarcodeDetector. No library is
 *   vendored and nothing is fetched from a CDN, which matters because this
 *   terminal is expected to work with the internet unplugged. BarcodeDetector
 *   is absent in some browsers; where it is, the button is hidden rather than
 *   left to fail, and the operator uses the scanner or types the code.
 */
document.addEventListener('DOMContentLoaded', function () {
  var cardField = document.getElementById('cardCode');
  if (!cardField) { return; }

  var who = document.getElementById('cardWho');
  var pinField = document.getElementById('workerPin');
  var workerField = document.getElementById('workerCode');

  function acknowledge(value) {
    // The name is deliberately NOT looked up here. Resolving a card to a name
    // before any other factor has been checked would turn this page into a way
    // to discover who holds a card by trying values against it. The worker is
    // named on the confirmation, after the face has matched.
    if (who) {
      who.textContent = value
        ? 'Card read. Enter the PIN and press the button to verify your face.'
        : 'No card? Leave this blank and use your worker number below.';
    }
    if (value && workerField) {
      // The card decides who this is; the server ignores anything typed here
      // when a card was scanned. Clearing it avoids showing a stale worker
      // number from the previous person in the queue.
      workerField.value = '';
      workerField.removeAttribute('required');
    } else if (workerField) {
      workerField.setAttribute('required', 'required');
    }
  }

  cardField.addEventListener('input', function () { acknowledge(cardField.value.trim()); });

  cardField.addEventListener('keydown', function (event) {
    // A scanner's trailing Enter would otherwise submit the form with an empty
    // PIN, producing a refusal the worker would read as "the card did not
    // work". Move focus on instead.
    if (event.key === 'Enter') {
      event.preventDefault();
      acknowledge(cardField.value.trim());
      if (pinField) { pinField.focus(); }
    }
  });

  // --- Camera fallback ---------------------------------------------------
  var scanButton = document.getElementById('scanWithCamera');
  if (!scanButton) { return; }

  if (!('BarcodeDetector' in window)) {
    scanButton.remove();
    return;
  }

  var box = document.getElementById('cardScanBox');
  var video = document.getElementById('cardScanVideo');
  var stopButton = document.getElementById('cardScanStop');
  var stream = null;
  var timer = null;

  function stop() {
    if (timer) { window.clearInterval(timer); timer = null; }
    if (stream) {
      stream.getTracks().forEach(function (track) { track.stop(); });
      stream = null;
    }
    if (box) { box.classList.add('d-none'); }
  }

  scanButton.addEventListener('click', function () {
    var detector = new window.BarcodeDetector({ formats: ['code_128', 'qr_code'] });

    // facingMode 'environment' asks for the rear camera on a phone: a
    // supervisor holds the card in front of them, not beside their own face.
    navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
      .then(function (media) {
        stream = media;
        video.srcObject = media;
        video.play();
        box.classList.remove('d-none');

        timer = window.setInterval(function () {
          detector.detect(video)
            .then(function (codes) {
              if (!codes.length) { return; }
              cardField.value = codes[0].rawValue;
              acknowledge(cardField.value);
              stop();
              if (pinField) { pinField.focus(); }
            })
            .catch(function () { /* a frame that will not decode is normal */ });
        }, 350);
      })
      .catch(function () {
        if (who) {
          who.textContent = 'The camera could not be opened. Use the scanner, '
                          + 'or type the code printed under the bars on the card.';
        }
      });
  });

  if (stopButton) { stopButton.addEventListener('click', stop); }
});
