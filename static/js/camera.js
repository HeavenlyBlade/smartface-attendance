/**
 * static/js/camera.js  -- SmartFace Kiosk
 * 600ms server recognition loop + rAF bounding box overlay
 */
(function () {
  'use strict';

  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = cfg.brightnessThreshold !== undefined ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var CAPTURE_QUALITY      = cfg.captureQuality  || 0.7;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 600;

  /* DOM */
  var video             = document.getElementById('kiosk-video');
  var overlayCanvas     = document.getElementById('overlay-canvas');
  var cameraErrorPanel  = document.getElementById('camera-error-panel');
  var brightnessWarning = document.getElementById('brightness-warning');
  var faceStatus        = document.getElementById('face-status');
  var kioskLastName     = document.getElementById('kiosk-last-name');
  var kioskIdleText     = document.getElementById('kiosk-idle-text');
  var successAudio      = document.getElementById('success-audio');
  var failAudio         = document.getElementById('fail-audio');
  var overlayCtx        = overlayCanvas ? overlayCanvas.getContext('2d') : null;

  /* Capture state */
  var processing            = false;
  var audioPlaying          = false;
  var captureTimer          = null;
  var currentAbortController = null;

  /* Bounding box state -- updated by server every 600ms, drawn every rAF frame */
  var lastBox      = null;   // {top, right, bottom, left} in original video coords
  var lastBoxLabel = '';
  var lastBoxColor = '';
  var lastBoxTime  = 0;
  var BOX_TIMEOUT_MS = 2500;

  /* -----------------------------------------------------------------------
     Canvas helpers
  ----------------------------------------------------------------------- */
  function syncCanvasSize() {
    if (!overlayCanvas || !video) return;
    var rect = video.getBoundingClientRect();
    if (overlayCanvas.width  !== rect.width)  overlayCanvas.width  = rect.width;
    if (overlayCanvas.height !== rect.height) overlayCanvas.height = rect.height;
  }

  /* -----------------------------------------------------------------------
     drawBox -- clear canvas and redraw bounding box + label every rAF frame
  ----------------------------------------------------------------------- */
  function drawBox() {
    requestAnimationFrame(drawBox);
    if (!overlayCtx || !overlayCanvas || !video) return;

    syncCanvasSize();
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    if (lastBox === null || (Date.now() - lastBoxTime) >= BOX_TIMEOUT_MS) return;

    var scaleX = video.videoWidth  ? overlayCanvas.width  / video.videoWidth  : 1;
    var scaleY = video.videoHeight ? overlayCanvas.height / video.videoHeight : 1;

    var pad = 15;
    /* Mirror x to match CSS scaleX(-1) on video */
    var rawL = lastBox.left  * scaleX;
    var rawR = lastBox.right * scaleX;
    var x    = overlayCanvas.width - rawR - pad;
    var y    = lastBox.top * scaleY - pad;
    var w    = (rawR - rawL) + pad * 2;
    var h    = (lastBox.bottom - lastBox.top) * scaleY + pad * 2;

    /* Box stroke */
    overlayCtx.save();
    overlayCtx.strokeStyle = lastBoxColor;
    overlayCtx.lineWidth   = 2.5;
    overlayCtx.strokeRect(x, y, w, h);
    overlayCtx.restore();

    /* Label -- drawn in normal coords so text is not mirrored */
    if (lastBoxLabel) {
      overlayCtx.save();
      overlayCtx.font         = '14px Inter, sans-serif';
      overlayCtx.textBaseline = 'bottom';
      overlayCtx.textAlign    = 'left';
      var lx = Math.max(x, 2);
      var ly = Math.max(y - 2, 18);
      var tm = overlayCtx.measureText(lastBoxLabel);
      overlayCtx.fillStyle = lastBoxColor;
      overlayCtx.fillRect(lx - 2, ly - 16, tm.width + 8, 20);
      overlayCtx.fillStyle = '#ffffff';
      overlayCtx.fillText(lastBoxLabel, lx + 2, ly);
      overlayCtx.restore();
    }
  }

  /* -----------------------------------------------------------------------
     Brightness check
  ----------------------------------------------------------------------- */
  function computeMeanBrightness(pixels) {
    var sum = 0, len = pixels.length;
    for (var i = 0; i < len; i++) { if (i % 4 !== 3) sum += pixels[i]; }
    return sum / (len * 0.75);
  }

  /* -----------------------------------------------------------------------
     Status bar
  ----------------------------------------------------------------------- */
  function updateStatusBar(faces) {
    if (!faces || !faces.length) {
      if (kioskIdleText) kioskIdleText.style.display = '';
      if (kioskLastName) kioskLastName.style.display = 'none';
      return;
    }
    var display = null;
    for (var i = 0; i < faces.length; i++) {
      if (faces[i].user_id !== null && faces[i].user_id !== undefined) {
        display = faces[i]; break;
      }
    }
    if (!display) display = faces[0];
    if (kioskLastName) {
      kioskLastName.textContent = display.full_name || 'Unknown';
      if (display.user_id !== null && display.user_id !== undefined) {
        kioskLastName.classList.remove('unknown');
      } else {
        kioskLastName.classList.add('unknown');
      }
      kioskLastName.style.display = '';
    }
    if (kioskIdleText) kioskIdleText.style.display = 'none';
  }

  function updateFaceStatus(faces) {
    if (!faceStatus) return;
    faceStatus.style.display = (!faces || !faces.length) ? '' : 'none';
  }

  /* -----------------------------------------------------------------------
     Audio
  ----------------------------------------------------------------------- */
  function triggerAudioCue(faces) {
    if (!faces || !faces.length || audioPlaying) return;
    var hasMatch = false, hasUnknown = false;
    faces.forEach(function(f) {
      if (f.user_id !== null && f.user_id !== undefined) hasMatch = true;
      else hasUnknown = true;
    });
    var target = hasMatch ? successAudio : (hasUnknown ? failAudio : null);
    if (!target) return;
    audioPlaying = true;
    target.currentTime = 0;
    var p = target.play();
    function reset() { audioPlaying = false; }
    if (p) p.then(function() { target.addEventListener('ended', reset, { once: true }); }).catch(reset);
    else target.addEventListener('ended', reset, { once: true });
  }

  /* -----------------------------------------------------------------------
     Capture loop -- 600ms, processing lock, AbortController
  ----------------------------------------------------------------------- */
  function captureTick() {
    if (document.visibilityState === 'hidden') return;
    if (processing) return;
    processing = true;

    if (currentAbortController) currentAbortController.abort();
    currentAbortController = new AbortController();
    var signal = currentAbortController.signal;

    var cap = document.createElement('canvas');
    cap.width  = video.videoWidth  || 640;
    cap.height = video.videoHeight || 480;
    var ctx = cap.getContext('2d');
    ctx.drawImage(video, 0, 0, cap.width, cap.height);

    var imgData = ctx.getImageData(0, 0, cap.width, cap.height);
    var mean = computeMeanBrightness(imgData.data);
    if (brightnessWarning) {
      brightnessWarning.style.display = mean < BRIGHTNESS_THRESHOLD ? 'flex' : 'none';
    }

    var b64 = cap.toDataURL('image/jpeg', CAPTURE_QUALITY).split(',')[1];

    fetch(RECOGNIZE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ image: b64 }),
      signal:  signal
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var faces = (data && Array.isArray(data.faces)) ? data.faces : [];

      if (faces.length > 0) {
        var face = null;
        for (var i = 0; i < faces.length; i++) {
          if (faces[i].user_id !== null && faces[i].user_id !== undefined) {
            face = faces[i]; break;
          }
        }
        if (!face) face = faces[0];

        var bb = face.bounding_box;
        lastBox      = { top: bb.top, right: bb.right, bottom: bb.bottom, left: bb.left };
        lastBoxTime  = Date.now();

        var isKnown  = (face.user_id !== null && face.user_id !== undefined);
        lastBoxColor = isKnown ? '#22c55e' : '#ef4444';
        lastBoxLabel = isKnown
          ? face.full_name + (face.confidence != null ? ' ' + face.confidence.toFixed(1) + '%' : '')
          : 'Unknown';
      }

      updateFaceStatus(faces);
      updateStatusBar(faces);
      triggerAudioCue(faces);
      processing = false;
    })
    .catch(function(err) {
      if (err && err.name === 'AbortError') return;
      processing = false;
      updateFaceStatus([]);
    });
  }

  function startCaptureLoop() {
    if (captureTimer !== null) return;
    captureTimer = setInterval(captureTick, CAPTURE_INTERVAL_MS);
  }

  function stopCaptureLoop() {
    if (captureTimer !== null) { clearInterval(captureTimer); captureTimer = null; }
  }

  document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'hidden') stopCaptureLoop();
    else startCaptureLoop();
  });

  /* -----------------------------------------------------------------------
     Camera init
  ----------------------------------------------------------------------- */
  function showCameraError() {
    if (cameraErrorPanel) cameraErrorPanel.style.display = 'flex';
    if (video) video.style.display = 'none';
    if (overlayCanvas) overlayCanvas.style.display = 'none';
  }

  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showCameraError(); return;
    }
    navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 } })
      .then(function(stream) {
        video.srcObject = stream;
        video.onloadedmetadata = function() {
          video.play();
          syncCanvasSize();
          startCaptureLoop();
          drawBox();  // start the rAF drawing loop
        };
      })
      .catch(function() { showCameraError(); });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startCamera);
  } else {
    startCamera();
  }
})();
