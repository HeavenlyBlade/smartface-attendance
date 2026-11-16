/**
 * static/js/camera.js  — SmartFace Kiosk
 * 800ms capture interval, CNN-backed recognition, no MediaPipe FaceMesh
 */
(function () {
  'use strict';

  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = cfg.brightnessThreshold !== undefined ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var OVERLAY_FONT_SIZE    = cfg.overlayFontSize  || '2rem';
  var OVERLAY_LINE_WIDTH   = cfg.overlayLineWidth || 3;
  var CAPTURE_QUALITY      = cfg.captureQuality   || 0.7;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 800;   // 800ms

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

  /* State */
  var processing   = false;
  var audioPlaying = false;
  var captureTimer = null;
  var currentAbortController = null;

  /* -----------------------------------------------------------------------
     Server overlay — bounding box + name/confidence from /api/recognize
  ----------------------------------------------------------------------- */
  function syncCanvasSize() {
    if (!overlayCanvas || !video) return;
    var rect = video.getBoundingClientRect();
    if (overlayCanvas.width  !== rect.width)  overlayCanvas.width  = rect.width;
    if (overlayCanvas.height !== rect.height) overlayCanvas.height = rect.height;
  }

  function drawServerOverlay(faces) {
    if (!overlayCtx || !overlayCanvas || !faces || !faces.length) return;

    var scaleX = video && video.videoWidth  ? overlayCanvas.width  / video.videoWidth  : 1;
    var scaleY = video && video.videoHeight ? overlayCanvas.height / video.videoHeight : 1;

    faces.forEach(function(face) {
      var bb      = face.bounding_box;
      var isKnown = face.user_id !== null && face.user_id !== undefined;
      var color   = isKnown ? '#4CAF82' : '#e57373';

      var x = bb.left  * scaleX;
      var y = bb.top   * scaleY;
      var w = (bb.right  - bb.left) * scaleX;
      var h = (bb.bottom - bb.top)  * scaleY;

      // Solid bounding box for matched face
      overlayCtx.save();
      overlayCtx.strokeStyle = color;
      overlayCtx.lineWidth   = OVERLAY_LINE_WIDTH + 1;
      overlayCtx.shadowColor = color;
      overlayCtx.shadowBlur  = 12;
      overlayCtx.beginPath();
      drawRoundedRect(overlayCtx, x, y, w, h, 10);
      overlayCtx.stroke();
      overlayCtx.restore();

      // Name label with backdrop
      var labelName = face.full_name || 'Unknown';
      overlayCtx.save();
      overlayCtx.font         = 'bold ' + OVERLAY_FONT_SIZE + ' Inter, Arial, sans-serif';
      overlayCtx.textBaseline = 'bottom';
      overlayCtx.textAlign    = 'left';
      var lx = Math.max(x, 2);
      var ly = Math.max(y - 6, 36);
      var nm = overlayCtx.measureText(labelName);
      var fp = parseInt(OVERLAY_FONT_SIZE, 10) || 32;
      overlayCtx.fillStyle = isKnown ? 'rgba(76,175,130,0.85)' : 'rgba(239,68,68,0.85)';
      _roundRect(overlayCtx, lx - 4, ly - fp - 4, nm.width + 16, fp + 10, 6);
      overlayCtx.fill();
      overlayCtx.fillStyle = '#fff';
      overlayCtx.fillText(labelName, lx + 4, ly);
      overlayCtx.restore();

      // Confidence badge
      if (face.confidence !== null && face.confidence !== undefined) {
        var confText = face.confidence.toFixed(1) + '%';
        overlayCtx.save();
        overlayCtx.font         = 'bold 0.9rem Inter, Arial, sans-serif';
        overlayCtx.fillStyle    = 'rgba(0,0,0,0.7)';
        overlayCtx.textBaseline = 'top';
        overlayCtx.textAlign    = 'right';
        var cm = overlayCtx.measureText(confText);
        _roundRect(overlayCtx, x + w - cm.width - 14, y + 6, cm.width + 10, 22, 4);
        overlayCtx.fill();
        overlayCtx.fillStyle = color;
        overlayCtx.fillText(confText, x + w - 4, y + 9);
        overlayCtx.restore();
      }
    });
  }

  function _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    if (ctx.roundRect) { ctx.roundRect(x, y, w, h, r); return; }
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y); ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r); ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h); ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r); ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  function drawRoundedRect(ctx, x, y, w, h, r) {
    _roundRect(ctx, x, y, w, h, r);
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
      if (kioskIdleText)  kioskIdleText.style.display  = '';
      if (kioskLastName)  kioskLastName.style.display  = 'none';
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
     Capture loop — 800ms, with processing lock and AbortController
  ----------------------------------------------------------------------- */
  function captureTick() {
    if (document.visibilityState === 'hidden') return;
    if (processing) return;
    processing = true;

    // Abort any previous in-flight request and create a fresh controller
    if (currentAbortController) {
      currentAbortController.abort();
    }
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64 }),
      signal: signal
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var faces = (data && Array.isArray(data.faces)) ? data.faces : [];

      syncCanvasSize();
      overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
      drawServerOverlay(faces);

      updateFaceStatus(faces);
      updateStatusBar(faces);
      triggerAudioCue(faces);
      processing = false;
    })
    .catch(function(err) {
      // Ignore AbortError — it's intentional
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
    if (captureTimer !== null) {
      clearInterval(captureTimer);
      captureTimer = null;
    }
  }

  /* Pause when tab is hidden, resume when visible */
  document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'hidden') {
      stopCaptureLoop();
    } else {
      startCaptureLoop();
    }
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
