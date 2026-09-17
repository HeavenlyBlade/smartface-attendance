/**
 * static/js/camera.js
 *
 * Real-time frame capture loop for the SmartFace kiosk page.
 *
 * Reads configuration from window.KIOSK_CONFIG (injected by kiosk.html):
 *   brightnessThreshold {number}  Mean pixel value (0–255) below which the
 *                                 brightness warning is shown  (default 50)
 *   recognizeUrl        {string}  POST endpoint for frame submission
 *                                 (default '/api/recognize')
 *   overlayFontSize     {string}  CSS font-size string for canvas labels
 *                                 (default '2rem')
 *   overlayLineWidth    {number}  Bounding-box stroke width in px (default 3)
 *   captureQuality      {number}  JPEG quality 0–1 for toDataURL (default 0.7)
 *   captureIntervalMs   {number}  Tick interval in ms (default 1000)
 *
 * Requirement coverage:
 *   5.3  — Frame captured every 1000 ms; JPEG quality 0.7
 *   5.9  — Overlay redrawn within 200 ms of each API response
 *   13.1 — Camera instruction panel shown when getUserMedia is denied
 *   13.2 — Brightness warning banner shown / hidden per mean pixel value
 *   13.3 — "No face detected" pill shown when faces array is empty
 *   13.4 — "Unknown" label + bounding box for unrecognized faces
 */

(function () {
  'use strict';

  /* -----------------------------------------------------------------------
     Configuration (with safe defaults when KIOSK_CONFIG is absent)
  ----------------------------------------------------------------------- */
  var cfg = window.KIOSK_CONFIG || {};
  var BRIGHTNESS_THRESHOLD = (cfg.brightnessThreshold !== undefined)
    ? cfg.brightnessThreshold : 50;
  var RECOGNIZE_URL        = cfg.recognizeUrl    || '/api/recognize';
  var OVERLAY_FONT_SIZE    = cfg.overlayFontSize  || '2rem';
  var OVERLAY_LINE_WIDTH   = cfg.overlayLineWidth || 3;
  var CAPTURE_QUALITY      = cfg.captureQuality   || 0.7;
  var CAPTURE_INTERVAL_MS  = cfg.captureIntervalMs || 1000;

  /* -----------------------------------------------------------------------
     DOM references
  ----------------------------------------------------------------------- */
  var video             = document.getElementById('kiosk-video');
  var overlayCanvas     = document.getElementById('overlay-canvas');
  var cameraErrorPanel  = document.getElementById('camera-error-panel');
  var brightnessWarning = document.getElementById('brightness-warning');
  var faceStatus        = document.getElementById('face-status');
  var kioskLastName     = document.getElementById('kiosk-last-name');
  var kioskIdleText     = document.getElementById('kiosk-idle-text');
  var successAudio      = document.getElementById('success-audio');
  var failAudio         = document.getElementById('fail-audio');

  /* -----------------------------------------------------------------------
     Canvas context for overlay drawing
  ----------------------------------------------------------------------- */
  var overlayCtx = overlayCanvas ? overlayCanvas.getContext('2d') : null;

  /* -----------------------------------------------------------------------
     State
  ----------------------------------------------------------------------- */
  /**
   * Guards the capture loop: true while a POST /api/recognize request is
   * in-flight.  If the timer fires while pending is true the tick is skipped
   * so frames are never stacked up behind a slow server response.
   * @type {boolean}
   */
  var pending = false;

  /**
   * Tracks whether an audio cue is already playing to prevent overlapping.
   * @type {boolean}
   */
  var audioPlaying = false;

  /* -----------------------------------------------------------------------
     Utility helpers
  ----------------------------------------------------------------------- */

  /**
   * Sync the overlay canvas resolution to the video element's current
   * display dimensions.  Called immediately before each draw pass so the
   * canvas never drifts from the video size after a window resize.
   */
  function syncCanvasSize() {
    if (!overlayCanvas || !video) return;
    var rect = video.getBoundingClientRect();
    // Set the canvas *buffer* size to match the display size.
    // Bounding-box coordinates from the server are in original-frame
    // pixel space and are scaled separately inside drawOverlay().
    if (overlayCanvas.width  !== rect.width)  overlayCanvas.width  = rect.width;
    if (overlayCanvas.height !== rect.height) overlayCanvas.height = rect.height;
  }

  /**
   * Attempt to play an audio element.  Resets and replays from the start on
   * every call; swallows the NotAllowedError that browsers throw when autoplay
   * policy blocks un-interacted playback.
   * @param {HTMLAudioElement} audioEl
   */
  function playAudio(audioEl) {
    if (!audioEl) return;
    try {
      audioEl.currentTime = 0;
      var playPromise = audioEl.play();
      if (playPromise !== undefined) {
        playPromise.catch(function () {
          // Autoplay blocked by browser policy — silent no-op (Req 5.9)
        });
      }
    } catch (e) {
      // Guard against environments where HTMLAudioElement.play is unavailable
    }
  }

  /* -----------------------------------------------------------------------
     Brightness check  (Req 13.2)
  ----------------------------------------------------------------------- */

  /**
   * Compute the mean pixel brightness of a captured frame.
   *
   * ImageData stores pixels as a flat Uint8ClampedArray in [R, G, B, A, …]
   * order.  The alpha channel (index % 4 === 3) is excluded so transparent
   * regions (possible on some browser/OS combos) do not drag the mean down.
   * The divisor is (pixels.length * 0.75) — three channels out of four.
   *
   * @param {Uint8ClampedArray} pixels  Raw pixel data from getImageData
   * @returns {number}  Mean brightness, 0–255
   */
  function computeMeanBrightness(pixels) {
    var sum = 0;
    var len = pixels.length;
    for (var i = 0; i < len; i++) {
      // Skip every fourth byte (alpha channel)
      if (i % 4 !== 3) sum += pixels[i];
    }
    return sum / (len * 0.75);
  }

  /**
   * Show or hide the brightness warning banner based on the computed mean.
   * @param {number} mean  Result of computeMeanBrightness
   */
  function updateBrightnessWarning(mean) {
    if (!brightnessWarning) return;
    brightnessWarning.style.display = (mean < BRIGHTNESS_THRESHOLD) ? 'flex' : 'none';
  }

  /* -----------------------------------------------------------------------
     Overlay drawing  (Req 5.9, 13.3, 13.4)
  ----------------------------------------------------------------------- */

  /**
   * Draw rounded-rectangle bounding boxes and name/confidence labels for
   * every face returned by the server.
   *
   * Coordinate system:
   *   The server returns pixel coordinates relative to the *original*
   *   captured frame (video.videoWidth × video.videoHeight).  The overlay
   *   canvas is CSS-scaled to fit the display area, so bounding-box coords
   *   must be multiplied by the CSS-to-natural scale factors:
   *
   *     scaleX = canvas.width  / video.videoWidth
   *     scaleY = canvas.height / video.videoHeight
   *
   * @param {Array<{
   *   user_id:     number|null,
   *   full_name:   string,
   *   confidence:  number|null,
   *   bounding_box: {top: number, right: number, bottom: number, left: number}
   * }>} faces  Array of face objects from the server JSON response
   */
  function drawOverlay(faces) {
    if (!overlayCtx || !overlayCanvas) return;

    // Sync canvas buffer size to current video display size
    syncCanvasSize();

    // Step 1: Clear the previous frame's overlay
    overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);

    if (!faces || faces.length === 0) return;

    // Scale factors: original-frame pixels → canvas display pixels
    var scaleX = (video && video.videoWidth)  ? overlayCanvas.width  / video.videoWidth  : 1;
    var scaleY = (video && video.videoHeight) ? overlayCanvas.height / video.videoHeight : 1;

    for (var i = 0; i < faces.length; i++) {
      var face = faces[i];
      var bb   = face.bounding_box;

      // Determine colour: green for known faces, red for Unknown (Req 13.4)
      var isKnown = (face.user_id !== null && face.user_id !== undefined);
      var color   = isKnown ? '#4CAF82' : '#e57373';

      // Scale bounding box coordinates to canvas display space
      var x      = bb.left   * scaleX;
      var y      = bb.top    * scaleY;
      var width  = (bb.right  - bb.left) * scaleX;
      var height = (bb.bottom - bb.top)  * scaleY;

      // Step 2: Draw rounded-rectangle bounding box
      overlayCtx.save();
      overlayCtx.strokeStyle = color;
      overlayCtx.lineWidth   = OVERLAY_LINE_WIDTH;
      overlayCtx.beginPath();
      drawRoundedRect(overlayCtx, x, y, width, height, 8);
      overlayCtx.stroke();
      overlayCtx.restore();

      // Step 3: Draw name label above the box (Req 13.4)
      //   Font size: overlayFontSize (≥ 2rem per spec — typically 36 px for
      //   projector clarity, but we honour the configured string directly so
      //   the CSS rem unit scales with the page's root font size).
      var labelName = face.full_name || 'Unknown';

      overlayCtx.save();
      overlayCtx.font         = 'bold ' + OVERLAY_FONT_SIZE + ' Arial, sans-serif';
      overlayCtx.fillStyle    = color;
      overlayCtx.textBaseline = 'bottom';
      overlayCtx.textAlign    = 'left';

      // Clamp label X so it never goes off-canvas on the left edge
      var labelX = Math.max(x, 2);
      // Place label just above the top of the bounding box; fall back to 4 px
      // from the top if the box is near the top edge
      var labelY = Math.max(y - 4, parseInt(OVERLAY_FONT_SIZE, 10) + 4);

      // Draw a semi-transparent backdrop so the label is legible over any
      // background colour (important for projector use — Req 15.1)
      var nameMetrics = overlayCtx.measureText(labelName);
      var nameFontPx  = parseInt(OVERLAY_FONT_SIZE, 10) || 32;
      overlayCtx.fillStyle = 'rgba(0,0,0,0.55)';
      overlayCtx.fillRect(labelX - 2, labelY - nameFontPx - 2,
                          nameMetrics.width + 8, nameFontPx + 6);

      overlayCtx.fillStyle = color;
      overlayCtx.fillText(labelName, labelX, labelY);
      overlayCtx.restore();

      // Step 4: Draw confidence percentage below the name, if available
      if (face.confidence !== null && face.confidence !== undefined) {
        var confText = face.confidence.toFixed(1) + '%';
        overlayCtx.save();
        overlayCtx.font         = 'normal 1.2rem Arial, sans-serif';
        overlayCtx.fillStyle    = color;
        overlayCtx.textBaseline = 'top';
        overlayCtx.textAlign    = 'left';

        // Position just inside the top-left of the bounding box
        var confX = labelX;
        var confY = y + 6;

        var confMetrics  = overlayCtx.measureText(confText);
        var confFontPx   = 19; // approximate height for 1.2rem at 16 px/rem
        overlayCtx.fillStyle = 'rgba(0,0,0,0.45)';
        overlayCtx.fillRect(confX - 2, confY - 2,
                            confMetrics.width + 8, confFontPx + 4);

        overlayCtx.fillStyle = color;
        overlayCtx.fillText(confText, confX, confY);
        overlayCtx.restore();
      }
    }
  }

  /**
   * Draw a rounded rectangle path onto a canvas context.
   * Does NOT call stroke() or fill() — the caller is responsible.
   *
   * @param {CanvasRenderingContext2D} ctx
   * @param {number} x       Left edge
   * @param {number} y       Top edge
   * @param {number} w       Width
   * @param {number} h       Height
   * @param {number} radius  Corner radius in px
   */
  function drawRoundedRect(ctx, x, y, w, h, radius) {
    var r = Math.min(radius, Math.abs(w) / 2, Math.abs(h) / 2);
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y,     x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x,     y + h, x,     y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x,     y,     x + r, y);
    ctx.closePath();
  }

  /* -----------------------------------------------------------------------
     Status bar helpers  (Req 5.9, 13.3, 13.4)
  ----------------------------------------------------------------------- */

  /**
   * Update the bottom status bar to reflect the latest recognition results.
   *
   * Logic:
   *  - If no faces: show idle text, hide last-name span.
   *  - If faces present: hide idle text, show the name of the first matched
   *    face (or "Unknown" if none matched).  Apply the .unknown CSS class
   *    when the face is unrecognised.
   *
   * @param {Array} faces  Same faces array from the server response
   */
  function updateStatusBar(faces) {
    if (!faces || faces.length === 0) {
      if (kioskIdleText)  kioskIdleText.style.display  = '';
      if (kioskLastName)  kioskLastName.style.display  = 'none';
      return;
    }

    // Prefer the first matched (known) face; fall back to the first face
    var displayFace = null;
    for (var i = 0; i < faces.length; i++) {
      if (faces[i].user_id !== null && faces[i].user_id !== undefined) {
        displayFace = faces[i];
        break;
      }
    }
    if (!displayFace) displayFace = faces[0];

    if (kioskLastName) {
      kioskLastName.textContent = displayFace.full_name || 'Unknown';
      // Req 13.4 — apply .unknown class for unrecognised faces (red colour)
      if (displayFace.user_id !== null && displayFace.user_id !== undefined) {
        kioskLastName.classList.remove('unknown');
      } else {
        kioskLastName.classList.add('unknown');
      }
      kioskLastName.style.display = '';
    }

    if (kioskIdleText) kioskIdleText.style.display = 'none';
  }

  /**
   * Show or hide the "No face detected" pill based on whether the faces
   * array is empty.  (Req 13.3)
   *
   * @param {Array} faces  Faces array from the server response
   */
  function updateFaceStatus(faces) {
    if (!faceStatus) return;
    faceStatus.style.display = (!faces || faces.length === 0) ? '' : 'none';
  }

  /* -----------------------------------------------------------------------
     Audio cues  (Req 5.9)
  ----------------------------------------------------------------------- */

  /**
   * Play the appropriate audio cue for the returned faces.
   *
   * Rules:
   *  - If any face has user_id != null → success cue (match found).
   *  - Else if any face is Unknown (user_id == null) → fail cue.
   *  - If faces array is empty → no audio.
   *  - Cues are debounced: a new cue is not triggered while audioPlaying is
   *    true, preventing rapid overlapping sounds when the same face persists
   *    across multiple frames.
   *
   * @param {Array} faces  Faces array from the server response
   */
  function triggerAudioCue(faces) {
    if (!faces || faces.length === 0) return;
    if (audioPlaying) return;

    var hasMatch   = false;
    var hasUnknown = false;

    for (var i = 0; i < faces.length; i++) {
      if (faces[i].user_id !== null && faces[i].user_id !== undefined) {
        hasMatch = true;
      } else {
        hasUnknown = true;
      }
    }

    var target = null;
    if (hasMatch) {
      target = successAudio;
    } else if (hasUnknown) {
      target = failAudio;
    }

    if (!target) return;

    audioPlaying = true;
    target.currentTime = 0;

    var playPromise;
    try {
      playPromise = target.play();
    } catch (e) {
      audioPlaying = false;
      return;
    }

    // Reset the debounce flag when playback ends or errors out
    function resetAudioFlag() { audioPlaying = false; }
    if (playPromise !== undefined) {
      playPromise
        .then(function () {
          target.addEventListener('ended', resetAudioFlag, { once: true });
        })
        .catch(function () {
          audioPlaying = false;
        });
    } else {
      // Older browsers return undefined from play()
      target.addEventListener('ended', resetAudioFlag, { once: true });
    }
  }

  /* -----------------------------------------------------------------------
     Frame capture loop  (Req 5.3, 5.9)
  ----------------------------------------------------------------------- */

  /**
   * Perform one capture-and-recognize tick.
   *
   * Steps:
   *  1. Draw the current video frame onto a hidden canvas at full resolution.
   *  2. Compute mean pixel brightness; update warning banner (Req 13.2).
   *  3. Encode the canvas as JPEG (quality = CAPTURE_QUALITY).
   *  4. POST the base64 payload to RECOGNIZE_URL.
   *  5. On success: redraw overlay, update status bar, update face pill,
   *     trigger audio cue; set pending = false.
   *  6. On fetch error: log silently; set pending = false; continue loop.
   */
  function captureTick() {
    if (pending) return;  // skip this tick — previous request still in-flight
    pending = true;

    // ---- Create an off-screen canvas at the video's natural resolution ----
    var captureCanvas = document.createElement('canvas');
    captureCanvas.width  = video.videoWidth  || 640;
    captureCanvas.height = video.videoHeight || 480;
    var captureCtx = captureCanvas.getContext('2d');
    captureCtx.drawImage(video, 0, 0, captureCanvas.width, captureCanvas.height);

    // ---- Brightness check (Req 13.2) ----
    var imageData = captureCtx.getImageData(0, 0, captureCanvas.width, captureCanvas.height);
    var mean = computeMeanBrightness(imageData.data);
    updateBrightnessWarning(mean);

    // ---- Encode frame as base64 JPEG (Req 5.3) ----
    var dataUrl = captureCanvas.toDataURL('image/jpeg', CAPTURE_QUALITY);
    var b64 = dataUrl.split(',')[1];   // strip 'data:image/jpeg;base64,' prefix

    // ---- POST to recognition API ----
    fetch(RECOGNIZE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ image: b64 })
    })
      .then(function (response) {
        // Parse JSON regardless of HTTP status; the server always returns JSON
        return response.json();
      })
      .then(function (data) {
        var faces = (data && Array.isArray(data.faces)) ? data.faces : [];

        // ---- Redraw overlay within the current microtask (Req 5.9) ----
        drawOverlay(faces);

        // ---- Update ancillary UI ----
        updateFaceStatus(faces);
        updateStatusBar(faces);
        triggerAudioCue(faces);

        pending = false;
      })
      .catch(function (/* err */) {
        // Network error or JSON parse failure — clear overlay and continue
        if (overlayCtx) {
          overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
        }
        updateFaceStatus([]);
        pending = false;
      });
  }

  /* -----------------------------------------------------------------------
     Camera initialisation  (Req 5.1, 5.2, 13.1)
  ----------------------------------------------------------------------- */

  /**
   * Show the camera permission error panel and stop the capture loop.
   * Called when getUserMedia() is denied or unavailable (Req 5.2, 13.1).
   */
  function showCameraError() {
    if (cameraErrorPanel) cameraErrorPanel.style.display = 'flex';
    if (video) video.style.display = 'none';
    if (overlayCanvas) overlayCanvas.style.display = 'none';
    // brightness-warning and face-status remain hidden (nothing to show)
  }

  /**
   * Request webcam access, wire up the video element, then start the
   * capture interval.
   *
   * On permission grant (Req 5.1):
   *  - Assign stream to video.srcObject
   *  - Start setInterval once video metadata is available
   *
   * On denial (Req 5.2, 13.1):
   *  - Show #camera-error-panel
   *  - Do not start the interval
   */
  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      // API unavailable (non-HTTPS context or very old browser) — treat as denial
      showCameraError();
      return;
    }

    navigator.mediaDevices
      .getUserMedia({ video: true })
      .then(function (stream) {
        video.srcObject = stream;
        video.onloadedmetadata = function () {
          video.play();
          // Sync the overlay canvas to the initial video dimensions
          syncCanvasSize();
          // ---- Start the capture loop (Req 5.3) ----
          // setInterval fires every CAPTURE_INTERVAL_MS (1000 ms ± browser jitter).
          // The pending flag inside captureTick ensures only one request is
          // in-flight at a time regardless of jitter or slow server responses.
          setInterval(captureTick, CAPTURE_INTERVAL_MS);
        };
      })
      .catch(function () {
        // getUserMedia denied or the camera is already in use (Req 5.2, 13.1)
        showCameraError();
      });
  }

  /* -----------------------------------------------------------------------
     Bootstrap — start everything when the DOM is fully loaded
  ----------------------------------------------------------------------- */

  // kiosk.html places this <script> at the bottom of <body>, so the DOM is
  // already available.  A defensive DOMContentLoaded guard is added in case
  // the script is ever moved to <head> with defer.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startCamera);
  } else {
    startCamera();
  }

})();
