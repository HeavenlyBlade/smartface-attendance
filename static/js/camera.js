/**
 * static/js/camera.js  — SmartFace Kiosk
 * 600ms server recognition loop + 30fps face-api.js landmark skeleton
 */
(function () {
  'use strict';

  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = cfg.brightnessThreshold !== undefined ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var OVERLAY_FONT_SIZE    = cfg.overlayFontSize  || '2rem';
  var OVERLAY_LINE_WIDTH   = cfg.overlayLineWidth || 3;
  var CAPTURE_QUALITY      = cfg.captureQuality   || 0.7;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 600;   // 600ms

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
     Persistent bounding box state — updated by server recognition every 600ms,
     consumed by the landmark rAF loop which owns all canvas drawing
  ----------------------------------------------------------------------- */
  var lastBox      = null;   // {top, right, bottom, left} in original video coords
  var lastBoxLabel = '';     // name + confidence string
  var lastBoxColor = '';     // green for known, red for unknown
  var lastBoxTime  = 0;      // timestamp of last box update
  var BOX_TIMEOUT_MS = 2500; // clear box if no server update for 2.5 s

  /* -----------------------------------------------------------------------
     face-api.js — model loading and 30fps landmark loop
  ----------------------------------------------------------------------- */
  var faceApiReady     = false;
  var MODELS_PATH      = '/static/models';
  var latestDetections = [];   // stored results from last async face-api detection

  async function loadFaceApi() {
    try {
      await faceapi.nets.tinyFaceDetector.loadFromUri(MODELS_PATH);
      await faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODELS_PATH);
      faceApiReady = true;
      console.log('face-api.js models loaded');
      // Warm up the TF.js WebGL backend so first real detection is instant
      var warmupCanvas = document.createElement('canvas');
      warmupCanvas.width = 320; warmupCanvas.height = 240;
      await faceapi.detectAllFaces(warmupCanvas, new faceapi.TinyFaceDetectorOptions({ inputSize: 320, scoreThreshold: 0.3 }));
      console.log('face-api.js warmed up');
    } catch (e) {
      console.warn('face-api.js failed to load:', e);
    }
  }

  /* -----------------------------------------------------------------------
     Canvas helpers
  ----------------------------------------------------------------------- */
  function syncCanvasSize() {
    if (!overlayCanvas || !video) return;
    var rect = video.getBoundingClientRect();
    if (overlayCanvas.width  !== rect.width)  overlayCanvas.width  = rect.width;
    if (overlayCanvas.height !== rect.height) overlayCanvas.height = rect.height;
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
     drawServerBox — renders the server-sourced bounding box + label onto ctx.
     Called every frame by landmarkLoop after clearing the canvas.
  ----------------------------------------------------------------------- */
  function drawServerBox(ctx, scaleX, scaleY) {
    if (lastBox === null || (Date.now() - lastBoxTime) >= BOX_TIMEOUT_MS) return;

    var pad = 15;
    var x = lastBox.left   * scaleX - pad;
    var y = lastBox.top    * scaleY - pad;
    var w = (lastBox.right  - lastBox.left) * scaleX + pad * 2;
    var h = (lastBox.bottom - lastBox.top)  * scaleY + pad * 2;

    // Bounding box stroke
    ctx.save();
    ctx.strokeStyle = lastBoxColor;
    ctx.lineWidth   = 2;
    ctx.beginPath();
    ctx.strokeRect(x, y, w, h);
    ctx.restore();

    // Label — filled rectangle behind white text
    if (lastBoxLabel) {
      ctx.save();
      ctx.font         = '14px Inter, sans-serif';
      ctx.textBaseline = 'bottom';
      ctx.textAlign    = 'left';
      var lx = Math.max(x, 2);
      var ly = Math.max(y - 4, 18);
      var tm = ctx.measureText(lastBoxLabel);
      ctx.fillStyle = lastBoxColor;
      ctx.fillRect(lx - 2, ly - 16, tm.width + 8, 20);
      ctx.fillStyle = '#ffffff';
      ctx.fillText(lastBoxLabel, lx + 2, ly);
      ctx.restore();
    }
  }

  /* -----------------------------------------------------------------------
     drawLandmarkSkeleton — draws the 68-point facial landmark skeleton.
     pts must already be in canvas display space (from faceapi.resizeResults).
  ----------------------------------------------------------------------- */
  function drawLandmarkSkeleton(ctx, pts) {
    if (!pts || pts.length < 68) return;

    function pt(i) { return { x: pts[i].x, y: pts[i].y }; }

    function drawRegion(indices, close) {
      ctx.beginPath();
      var start = pt(indices[0]);
      ctx.moveTo(start.x, start.y);
      for (var i = 1; i < indices.length; i++) {
        var p = pt(indices[i]);
        ctx.lineTo(p.x, p.y);
      }
      if (close) ctx.closePath();
      ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(0, 220, 255, 0.75)';  // cyan, techy look
    ctx.lineWidth   = 1.2;

    // Jaw
    drawRegion([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16], false);
    // Right eyebrow
    drawRegion([17,18,19,20,21], false);
    // Left eyebrow
    drawRegion([22,23,24,25,26], false);
    // Nose bridge
    drawRegion([27,28,29,30], false);
    // Nose bottom
    drawRegion([30,31,32,33,34,35,30], false);
    // Right eye
    drawRegion([36,37,38,39,40,41], true);
    // Left eye
    drawRegion([42,43,44,45,46,47], true);
    // Outer lips
    drawRegion([48,49,50,51,52,53,54,55,56,57,58,59], true);
    // Inner lips
    drawRegion([60,61,62,63,64,65,66,67], true);

    // Dots on each landmark
    ctx.fillStyle = 'rgba(0, 255, 220, 0.9)';
    for (var i = 0; i < 68; i++) {
      var p = pt(i);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* -----------------------------------------------------------------------
     landmarkLoop — single rAF loop that owns ALL canvas drawing.
     Uses a stored-results pattern: async face-api.js detection only updates
     latestDetections; drawing happens synchronously every rAF frame so
     landmarks are never wiped mid-draw.
  ----------------------------------------------------------------------- */
  var landmarkCanvas = document.getElementById('overlay-canvas');
  var landmarkCtx    = landmarkCanvas ? landmarkCanvas.getContext('2d') : null;

  function landmarkLoop() {
    requestAnimationFrame(landmarkLoop);

    if (!landmarkCtx || !landmarkCanvas || !video) return;

    syncCanvasSize();
    var scaleX = video.videoWidth  ? landmarkCanvas.width  / video.videoWidth  : 1;
    var scaleY = video.videoHeight ? landmarkCanvas.height / video.videoHeight : 1;

    // Clear canvas every frame
    landmarkCtx.clearRect(0, 0, landmarkCanvas.width, landmarkCanvas.height);

    // Draw server bounding box (from last /api/recognize response)
    drawServerBox(landmarkCtx, scaleX, scaleY);

    // Draw landmarks from last face-api.js detection
    latestDetections.forEach(function(det) {
      drawLandmarkSkeleton(landmarkCtx, det.landmarks.positions);
    });

    // Fire async detection if models ready and video is live
    if (faceApiReady && video.readyState >= 2 && !document.hidden) {
      var displaySize = { width: landmarkCanvas.width, height: landmarkCanvas.height };
      if (displaySize.width > 0 && displaySize.height > 0) {
        faceapi.matchDimensions(landmarkCanvas, displaySize);
        faceapi.detectAllFaces(video, new faceapi.TinyFaceDetectorOptions({
          inputSize: 320,
          scoreThreshold: 0.3
        })).withFaceLandmarks(true).then(function(detections) {
          // Re-read canvas size at resolve time (may differ from when detection was fired)
          var resolvedSize = { width: landmarkCanvas.width, height: landmarkCanvas.height };
          if (resolvedSize.width > 0 && resolvedSize.height > 0) {
            latestDetections = faceapi.resizeResults(detections, resolvedSize);
          }
        });
      }
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

      // Update persistent bounding box state from the first detected face
      if (faces.length > 0) {
        // Pick the best face: prefer a recognized (user_id set) one
        var face = null;
        for (var i = 0; i < faces.length; i++) {
          if (faces[i].user_id !== null && faces[i].user_id !== undefined) {
            face = faces[i]; break;
          }
        }
        if (!face) face = faces[0];

        var bb = face.bounding_box;
        // bounding_box values are already in full-frame coordinates (face_service scales by 2x)
        lastBox      = { top: bb.top, right: bb.right, bottom: bb.bottom, left: bb.left };
        lastBoxTime  = Date.now();

        var isKnown = (face.user_id !== null && face.user_id !== undefined);
        lastBoxColor = isKnown ? '#22c55e' : '#ef4444';
        if (isKnown) {
          lastBoxLabel = face.full_name + (face.confidence !== null && face.confidence !== undefined
            ? ' ' + face.confidence.toFixed(1) + '%' : '');
        } else {
          lastBoxLabel = 'Unknown';
        }
      }
      // No face: do NOT clear lastBox — BOX_TIMEOUT_MS handles natural fade-out

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
          // Start landmark loop only after video dimensions are known
          landmarkLoop();
        };
      })
      .catch(function() { showCameraError(); });
  }

  // Load face-api.js models (landmark loop starts after camera is ready)
  loadFaceApi();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startCamera);
  } else {
    startCamera();
  }
})();
