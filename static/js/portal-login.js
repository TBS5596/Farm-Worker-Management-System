/* ===========================================================================
   portal-login.js - taking the worker's photo on the sign-in screen.

   Two capture paths, and which one runs is decided by the browser, not by us:

     1. FILE INPUT (always available). accept="image/*" capture="user" opens
        the phone's own camera app. Needs no permissions dialog of our own and
        no secure context, so it works on a farm LAN over plain http://.

     2. LIVE PREVIEW (only sometimes). navigator.mediaDevices.getUserMedia is
        exposed only in a secure context - HTTPS or localhost. On
        http://192.168.x.x it is undefined, and calling it throws. So we
        feature-detect, and only offer the nicer inline preview when the
        browser has actually given us the API.

   Whichever path runs, the form ends up carrying exactly one image: either a
   file in `photo`, or a JPEG data URL in the hidden `frame` field.
   =========================================================================== */
(function () {
  "use strict";

  var form = document.getElementById("signinForm");
  var takeBtn = document.getElementById("takeBtn");
  var fileInput = document.getElementById("photo");
  var frameField = document.getElementById("frame");
  var video = document.getElementById("preview");
  var canvas = document.getElementById("canvas");
  var shot = document.getElementById("shot");
  var ready = document.getElementById("captureReady");

  if (!form || !takeBtn) { return; }

  var stream = null;

  function markReady() {
    ready.hidden = false;
    takeBtn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i> Take another photo';
  }

  /* --- Path 1: the phone's camera app ------------------------------------ */

  fileInput.addEventListener("change", function () {
    if (!fileInput.files || !fileInput.files[0]) { return; }
    // Show the worker what they just took, so a photo of the ceiling is
    // obvious before they submit it rather than after it is refused.
    var reader = new FileReader();
    reader.onload = function (e) {
      shot.src = e.target.result;
      shot.hidden = false;
      if (video) { video.hidden = true; }
      markReady();
    };
    reader.readAsDataURL(fileInput.files[0]);
    // The two paths are mutually exclusive: a file wins, so clear any frame.
    frameField.value = "";
  });

  /* --- Path 2: live preview, where the browser allows it ------------------ */

  function capture() {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    frameField.value = canvas.toDataURL("image/jpeg", 0.85);
    // A captured frame replaces any chosen file.
    fileInput.value = "";
    shot.src = frameField.value;
    shot.hidden = false;
    video.hidden = true;
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    markReady();
  }

  function startPreview() {
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "user" } })
      .then(function (s) {
        stream = s;
        video.srcObject = s;
        video.hidden = false;
        shot.hidden = true;
        takeBtn.innerHTML = '<i class="bi bi-camera-fill me-1"></i> Capture';
        takeBtn.onclick = capture;
      })
      .catch(function () {
        // Permission refused, or no camera. Fall back silently - the file
        // input still works and the worker never sees an error they cannot act on.
        takeBtn.onclick = function () { fileInput.click(); };
        fileInput.click();
      });
  }

  // Feature-detect rather than assume. On plain HTTP this whole branch is
  // skipped and the file input is the only path, which is the intended
  // behaviour for a farm LAN deployment.
  var canPreview = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

  takeBtn.onclick = canPreview ? startPreview : function () { fileInput.click(); };

  /* --- Don't submit without an image ------------------------------------- */

  form.addEventListener("submit", function (e) {
    var hasFile = fileInput.files && fileInput.files.length > 0;
    var hasFrame = frameField.value && frameField.value.length > 32;
    if (!hasFile && !hasFrame) {
      e.preventDefault();
      takeBtn.focus();
      ready.hidden = false;
      ready.className = "hint";
      ready.textContent = "Take a photo first - it is how the system knows it is you.";
    }
  });
})();
