/**
 * static/js/camera.js  — SmartFace Kiosk
 * 500ms capture interval, face mesh overlay, CNN-backed recognition
 */
(function () {
  'use strict';

  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = cfg.brightnessThreshold !== undefined ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var OVERLAY_FONT_SIZE    = cfg.overlayFontSize  || '2rem';
  var OVERLAY_LINE_WIDTH   = cfg.overlayLineWidth || 3;
  var CAPTURE_QUALITY      = cfg.captureQuality   || 0.7;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 500;   // 500ms

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
  var pending      = false;
  var audioPlaying = false;
  var lastFaces    = [];

  /* -----------------------------------------------------------------------
     MediaPipe FaceMesh — facial landmark scanner overlay
  ----------------------------------------------------------------------- */
  var faceMesh     = null;
  var meshCanvas   = document.createElement('canvas');
  var meshCtx      = meshCanvas.getContext('2d');
  var meshAnimFrame = null;
  var meshRunning  = false;

  function initFaceMesh() {
    if (typeof FaceMesh === 'undefined') return;
    faceMesh = new FaceMesh({
      locateFile: function(file) {
        return 'https://cdn.jsdelivr.net/npm/@mediapipe/face_mesh/' + file;
      }
    });
    faceMesh.setOptions({
      maxNumFaces: 4,
      refineLandmarks: true,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5
    });
    faceMesh.onResults(onMeshResults);
    startMeshLoop();
  }

  function startMeshLoop() {
    meshRunning = true;
    function loop() {
      if (!meshRunning || !video || video.readyState < 2) {
        meshAnimFrame = requestAnimationFrame(loop);
        return;
      }
      if (faceMesh) {
        faceMesh.send({ image: video }).catch(function() {});
      }
      meshAnimFrame = requestAnimationFrame(loop);
    }
    loop();
  }

  var _scanPhase = 0;  // for scanning animation

  function onMeshResults(results) {
    if (!overlayCanvas || !overlayCtx) return;

    syncCanvasSize();
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    var faces = results.multiFaceLandmarks || [];

    if (faces.length > 0) {
      _scanPhase = (_scanPhase + 3) % 360;
      faces.forEach(function(landmarks) {
        drawFaceMesh(landmarks);
      });
    }

    // Draw server-side bounding boxes + name labels on top
    if (lastFaces && lastFaces.length > 0) {
      drawServerOverlay(lastFaces);
    }
  }

  var FACE_OVAL = [10,338,297,332,284,251,389,356,454,323,361,288,
                   397,365,379,378,400,377,152,148,176,149,150,136,
                   172,58,132,93,234,127,162,21,54,103,67,109];

  var FACE_CONTOURS = [
    [33,7,163,144,145,153,154,155,133],   // left eye
    [362,382,381,380,374,373,390,249,263], // right eye
    [61,185,40,39,37,0,267,269,270,409,291,308,415,310,311,312,13,82,81,80,191,78], // lips outline
  ];

  function drawFaceMesh(landmarks) {
    var W = overlayCanvas.width;
    var H = overlayCanvas.height;

    // Calculate face bounding box for corner brackets
    var xs = landmarks.map(function(l) { return l.x * W; });
    var ys = landmarks.map(function(l) { return l.y * H; });
    var x1 = Math.min.apply(null, xs), x2 = Math.max.apply(null, xs);
    var y1 = Math.min.apply(null, ys), y2 = Math.max.apply(null, ys);
    var pad = 18;
    x1 -= pad; y1 -= pad; x2 += pad; y2 += pad;
    var fw = x2 - x1, fh = y2 - y1;

    // --- Scan line animation ---
    var scanY = y1 + (fh * ((_scanPhase % 180) / 180));
    overlayCtx.save();
    var scanGrad = overlayCtx.createLinearGradient(x1, scanY - 4, x1, scanY + 4);
    scanGrad.addColorStop(0, 'rgba(76,175,130,0)');
    scanGrad.addColorStop(0.5, 'rgba(76,175,130,0.7)');
    scanGrad.addColorStop(1, 'rgba(76,175,130,0)');
    overlayCtx.fillStyle = scanGrad;
    overlayCtx.fillRect(x1, scanY - 4, fw, 8);
    overlayCtx.restore();

    // --- Face oval (dotted mesh) ---
    overlayCtx.save();
    overlayCtx.strokeStyle = 'rgba(76,175,130,0.5)';
    overlayCtx.lineWidth   = 1;
    overlayCtx.setLineDash([2, 3]);
    overlayCtx.beginPath();
    FACE_OVAL.forEach(function(idx, i) {
      var lm = landmarks[idx];
      var x = lm.x * W, y = lm.y * H;
      if (i === 0) overlayCtx.moveTo(x, y);
      else overlayCtx.lineTo(x, y);
    });
    overlayCtx.closePath();
    overlayCtx.stroke();
    overlayCtx.restore();

    // --- Feature contours (eyes, lips) ---
    FACE_CONTOURS.forEach(function(contour) {
      overlayCtx.save();
      overlayCtx.strokeStyle = 'rgba(212,175,55,0.65)';
      overlayCtx.lineWidth = 1;
      overlayCtx.setLineDash([]);
      overlayCtx.beginPath();
      contour.forEach(function(idx, i) {
        var lm = landmarks[idx];
        var x = lm.x * W, y = lm.y * H;
        if (i === 0) overlayCtx.moveTo(x, y);
        else overlayCtx.lineTo(x, y);
      });
      overlayCtx.closePath();
      overlayCtx.stroke();
      overlayCtx.restore();
    });

    // --- Key landmark dots (eyes, nose tip, mouth corners) ---
    var keyPoints = [33, 263, 1, 61, 291, 199];
    keyPoints.forEach(function(idx) {
      var lm = landmarks[idx];
      overlayCtx.save();
      overlayCtx.beginPath();
      overlayCtx.arc(lm.x * W, lm.y * H, 2.5, 0, Math.PI * 2);
      overlayCtx.fillStyle = '#4CAF82';
      overlayCtx.fill();
      overlayCtx.restore();
    });

    // --- Corner brackets ---
    var cLen = Math.min(fw, fh) * 0.2;
    var cW   = 3;
    var corners = [
      [x1,    y1,    cLen, 0,    0,    cLen],   // top-left
      [x2,    y1,    -cLen,0,    0,    cLen],   // top-right
      [x1,    y2,    cLen, 0,    0,    -cLen],  // bottom-left
      [x2,    y2,    -cLen,0,    0,    -cLen],  // bottom-right
    ];
    overlayCtx.save();
    overlayCtx.strokeStyle = '#4CAF82';
    overlayCtx.lineWidth   = cW;
    overlayCtx.setLineDash([]);
    corners.forEach(function(c) {
      overlayCtx.beginPath();
      overlayCtx.moveTo(c[0] + c[2], c[1] + c[3]);
      overlayCtx.lineTo(c[0], c[1]);
      overlayCtx.lineTo(c[0] + c[4], c[1] + c[5]);
      overlayCtx.stroke();
    });
    overlayCtx.restore();

    // --- Scanning label ---
    overlayCtx.save();
    overlayCtx.font      = 'bold 11px Inter, Arial, sans-serif';
    overlayCtx.fillStyle = '#4CAF82';
    overlayCtx.textAlign = 'center';
    overlayCtx.fillText('SCANNING...', (x1 + x2) / 2, y1 - 8);
    overlayCtx.restore();
  }

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
     Capture loop — 500ms
  ----------------------------------------------------------------------- */
  function captureTick() {
    if (pending) return;
    pending = true;

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
      body: JSON.stringify({ image: b64 })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var faces = (data && Array.isArray(data.faces)) ? data.faces : [];
      lastFaces = faces;  // store for mesh overlay to draw on top

      // If FaceMesh isn't running, draw server overlay directly
      if (!faceMesh) {
        syncCanvasSize();
        overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
        drawServerOverlay(faces);
      }

      updateFaceStatus(faces);
      updateStatusBar(faces);
      triggerAudioCue(faces);
      pending = false;
    })
    .catch(function() {
      lastFaces = [];
      updateFaceStatus([]);
      pending = false;
    });
  }

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
          setInterval(captureTick, CAPTURE_INTERVAL_MS);

          // Init FaceMesh after camera is live
          setTimeout(function() { initFaceMesh(); }, 500);
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