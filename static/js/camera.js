/**
 * static/js/camera.js  -- SmartFace Kiosk
 * High-speed, responsive recognition loop + smooth rAF bounding box overlay
 */
(function () {
  'use strict';

  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = cfg.brightnessThreshold !== undefined ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var CAPTURE_QUALITY      = cfg.captureQuality  || 0.72;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 250;
  var TARGET_WIDTH         = 640;

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
  var processing             = false;
  var audioPlaying           = false;
  var captureTimeout         = null;
  var currentAbortController = null;
  var isStopped              = false;

  /* Audio debounce state */
  var lastSuccessAudioTime = 0;
  var lastSuccessAudioUid  = null;
  var lastFailAudioTime    = 0;

  /* Bounding box state -- updated by server, drawn every rAF frame */
  var lastBox      = null;   // {top, right, bottom, left, frameW, frameH}
  var lastBoxLabel = '';
  var lastBoxColor = '';
  var lastBoxTime  = 0;
  var BOX_TIMEOUT_MS = 2200;

  /* -----------------------------------------------------------------------
     Canvas helpers
  ----------------------------------------------------------------------- */
  function syncCanvasSize() {
    if (!overlayCanvas || !video) return;
    var rect = video.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      if (overlayCanvas.width  !== Math.round(rect.width))  overlayCanvas.width  = Math.round(rect.width);
      if (overlayCanvas.height !== Math.round(rect.height)) overlayCanvas.height = Math.round(rect.height);
    }
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

    var fw = lastBox.frameW || video.videoWidth || 640;
    var fh = lastBox.frameH || video.videoHeight || 480;
    var scaleX = overlayCanvas.width  / fw;
    var scaleY = overlayCanvas.height / fh;

    var pad = 12;
    /* Mirror x to match CSS scaleX(-1) on video */
    var rawL = lastBox.left  * scaleX;
    var rawR = lastBox.right * scaleX;
    var x    = overlayCanvas.width - rawR - pad;
    var y    = lastBox.top * scaleY - pad;
    var w    = (rawR - rawL) + pad * 2;
    var h    = (lastBox.bottom - lastBox.top) * scaleY + pad * 2;

    /* Smooth rounded box stroke */
    overlayCtx.save();
    overlayCtx.strokeStyle = lastBoxColor;
    overlayCtx.lineWidth   = 3;
    overlayCtx.shadowColor = lastBoxColor;
    overlayCtx.shadowBlur  = 8;

    if (overlayCtx.roundRect) {
      overlayCtx.beginPath();
      overlayCtx.roundRect(x, y, w, h, 8);
      overlayCtx.stroke();
    } else {
      overlayCtx.strokeRect(x, y, w, h);
    }
    overlayCtx.restore();

    /* Label -- drawn in unmirrored coords for crystal clarity */
    if (lastBoxLabel) {
      overlayCtx.save();
      overlayCtx.font         = 'bold 16px Inter, system-ui, -apple-system, sans-serif';
      overlayCtx.textBaseline = 'middle';
      overlayCtx.textAlign    = 'left';

      var lx = Math.max(x, 4);
      var ly = Math.max(y - 18, 16);
      var tm = overlayCtx.measureText(lastBoxLabel);
      var bgW = tm.width + 16;
      var bgH = 26;

      overlayCtx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      overlayCtx.strokeStyle = lastBoxColor;
      overlayCtx.lineWidth = 1.5;

      if (overlayCtx.roundRect) {
        overlayCtx.beginPath();
        overlayCtx.roundRect(lx, ly - bgH / 2, bgW, bgH, 6);
        overlayCtx.fill();
        overlayCtx.stroke();
      } else {
        overlayCtx.fillRect(lx, ly - bgH / 2, bgW, bgH);
        overlayCtx.strokeRect(lx, ly - bgH / 2, bgW, bgH);
      }

      overlayCtx.fillStyle = '#ffffff';
      overlayCtx.fillText(lastBoxLabel, lx + 8, ly);
      overlayCtx.restore();
    }
  }

  /* -----------------------------------------------------------------------
     Brightness check
  ----------------------------------------------------------------------- */
  function computeMeanBrightness(pixels) {
    var sum = 0, len = pixels.length;
    for (var i = 0; i < len; i += 4) {
      sum += (pixels[i] * 0.299 + pixels[i + 1] * 0.587 + pixels[i + 2] * 0.114);
    }
    return sum / (len / 4);
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
      var isKnown = (display.user_id !== null && display.user_id !== undefined);
      kioskLastName.textContent = display.full_name || 'Unknown';
      if (isKnown) {
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
     Audio cues with smart debouncing
  ----------------------------------------------------------------------- */
  function triggerAudioCue(faces) {
    if (!faces || !faces.length || audioPlaying) return;
    var now = Date.now();
    var matchedUser = null;
    var hasUnknown = false;

    faces.forEach(function(f) {
      if (f.user_id !== null && f.user_id !== undefined) {
        matchedUser = f;
      } else {
        hasUnknown = true;
      }
    });

    if (matchedUser) {
      // Debounce match sound per user to 4 seconds
      if (lastSuccessAudioUid === matchedUser.user_id && (now - lastSuccessAudioTime) < 4000) {
        return;
      }
      playAudio(successAudio);
      lastSuccessAudioTime = now;
      lastSuccessAudioUid  = matchedUser.user_id;
    } else if (hasUnknown) {
      // Debounce fail tone to 3.5 seconds
      if ((now - lastFailAudioTime) < 3500) {
        return;
      }
      playAudio(failAudio);
      lastFailAudioTime = now;
    }
  }

  function playAudio(target) {
    if (!target) return;
    audioPlaying = true;
    try {
      target.currentTime = 0;
      var p = target.play();
      function reset() { audioPlaying = false; }
      if (p && typeof p.then === 'function') {
        p.then(function() {
          target.addEventListener('ended', reset, { once: true });
        }).catch(reset);
      } else {
        target.addEventListener('ended', reset, { once: true });
      }
    } catch (e) {
      audioPlaying = false;
    }
  }

  /* -----------------------------------------------------------------------
     Capture loop -- fast self-scheduling with payload downscaling
  ----------------------------------------------------------------------- */
  function scheduleNextTick(delayMs) {
    if (isStopped) return;
    if (captureTimeout !== null) clearTimeout(captureTimeout);
    captureTimeout = setTimeout(captureTick, delayMs || CAPTURE_INTERVAL_MS);
  }

  function captureTick() {
    if (document.visibilityState === 'hidden' || isStopped) return;
    if (processing) return;
    if (!video || video.readyState < 2) {
      scheduleNextTick(150);
      return;
    }

    processing = true;

    if (currentAbortController) {
      try { currentAbortController.abort(); } catch (e) {}
    }
    currentAbortController = new AbortController();
    var signal = currentAbortController.signal;

    // Capture at optimal processing width (640px)
    var vw = video.videoWidth || 640;
    var vh = video.videoHeight || 480;
    var scale = Math.min(1.0, TARGET_WIDTH / vw);
    var capW = Math.round(vw * scale);
    var capH = Math.round(vh * scale);

    var cap = document.createElement('canvas');
    cap.width  = capW;
    cap.height = capH;
    var ctx = cap.getContext('2d');
    ctx.drawImage(video, 0, 0, capW, capH);

    // Fast brightness check
    var imgData = ctx.getImageData(0, 0, capW, capH);
    var mean = computeMeanBrightness(imgData.data);
    if (brightnessWarning) {
      brightnessWarning.style.display = mean < BRIGHTNESS_THRESHOLD ? 'flex' : 'none';
    }

    var b64 = cap.toDataURL('image/jpeg', CAPTURE_QUALITY).split(',')[1];
    var scannerId = window.SMARTFACE_SCANNER_ID || localStorage.getItem('smartface_scanner_id') || 'Main Kiosk';

    fetch(RECOGNIZE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ image: b64, scanner_id: scannerId }),
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
        lastBox = {
          top:     bb.top,
          right:   bb.right,
          bottom:  bb.bottom,
          left:    bb.left,
          frameW:  capW,
          frameH:  capH
        };
        lastBoxTime = Date.now();

        var isKnown = (face.user_id !== null && face.user_id !== undefined);
        var isVerifying = !isKnown && face.full_name && face.full_name.indexOf('Verifying') !== -1;

        if (isKnown) {
          lastBoxColor = '#22c55e'; // Emerald
          lastBoxLabel = face.full_name + (face.confidence != null ? ' ' + face.confidence.toFixed(1) + '%' : '');
        } else if (isVerifying) {
          lastBoxColor = '#38bdf8'; // Sky blue
          lastBoxLabel = face.full_name;
        } else {
          lastBoxColor = '#ef4444'; // Red
          lastBoxLabel = 'Unknown';
        }
      }

      updateFaceStatus(faces);
      updateStatusBar(faces);
      triggerAudioCue(faces);

      processing = false;
      scheduleNextTick(CAPTURE_INTERVAL_MS);
    })
    .catch(function(err) {
      if (err && err.name === 'AbortError') return;
      processing = false;
      updateFaceStatus([]);
      scheduleNextTick(CAPTURE_INTERVAL_MS);
    });
  }

  function startCaptureLoop() {
    isStopped = false;
    scheduleNextTick(100);
  }

  function stopCaptureLoop() {
    isStopped = true;
    if (captureTimeout !== null) {
      clearTimeout(captureTimeout);
      captureTimeout = null;
    }
    if (currentAbortController) {
      try { currentAbortController.abort(); } catch (e) {}
    }
    processing = false;
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
    navigator.mediaDevices.getUserMedia({
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: 'user'
      }
    })
      .then(function(stream) {
        video.srcObject = stream;
        video.onloadedmetadata = function() {
          video.play();
          syncCanvasSize();
          startCaptureLoop();
          drawBox();  // start rAF drawing loop
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
