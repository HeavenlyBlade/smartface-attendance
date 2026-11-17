/**
 * static/js/enroll.js
 *
 * Webcam capture and form submission handler for the enrollment page.
 *
 * Reads configuration from window.ENROLL_CONFIG (injected by enroll.html):
 *   minSamples     {number}  Minimum face samples required (default 3)
 *   maxSamples     {number}  Maximum face samples allowed  (default 5)
 *   captureQuality {number}  JPEG quality 0-1             (default 0.85)
 *   apiUrl         {string}  Enrollment POST endpoint      (default '/api/enroll')
 *
 * Requirement coverage: 3.1, 3.2, 3.3, 3.9
 */

(function () {
  'use strict';

  /* -----------------------------------------------------------------------
     Configuration (with safe defaults if ENROLL_CONFIG is absent)
  ----------------------------------------------------------------------- */
  var cfg = window.ENROLL_CONFIG || {};
  var MIN_SAMPLES     = cfg.minSamples     || 3;
  var MAX_SAMPLES     = cfg.maxSamples     || 5;
  var JPEG_QUALITY    = cfg.captureQuality || 0.85;
  var API_URL         = cfg.apiUrl         || '/api/enroll';
  var MAX_FRAME_BYTES = 5 * 1024 * 1024;   // 5 MB cap per sample (Req 3.2)

  /* -----------------------------------------------------------------------
     DOM references
  ----------------------------------------------------------------------- */
  var video          = document.getElementById('webcam-video');
  var initLabel      = document.getElementById('webcam-initialising');
  var errorPanel     = document.getElementById('camera-error-panel');
  var retryCamBtn    = document.getElementById('retry-camera-btn');
  var captureBtn     = document.getElementById('capture-btn');
  var clearBtn       = document.getElementById('clear-samples-btn');
  var submitBtn      = document.getElementById('submit-btn');
  var nextStepBtn    = document.getElementById('next-step-btn');
  var backStepBtn    = document.getElementById('back-step-btn');
  var step1          = document.getElementById('enroll-step-1');
  var step2          = document.getElementById('enroll-step-2');
  var step2Preview   = document.getElementById('step2-preview');
  var thumbStrip     = document.getElementById('thumbnail-strip');
  var capturedData   = document.getElementById('captured-data');
  var sampleCounter  = document.getElementById('sample-counter');
  var consentBox     = document.getElementById('consent-checkbox');
  var reqConsent     = document.getElementById('req-consent');
  var reqSamples     = document.getElementById('req-samples');
  var enrollForm     = document.getElementById('enroll-form');

  /* -----------------------------------------------------------------------
     State
  ----------------------------------------------------------------------- */
  /** @type {string[]} Array of base64 JPEG data-URLs (one per captured sample) */
  var capturedSamples = [];

  /** @type {MediaStream|null} Active webcam stream */
  var activeStream = null;

  /* -----------------------------------------------------------------------
     Camera initialisation
  ----------------------------------------------------------------------- */

  /**
   * Request camera access and wire up the video element.
   * Called on page load and again when the user clicks "Retry Camera".
   */
  function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      showCameraError();
      return;
    }

    // Show the "requesting..." label while the permission prompt is open
    if (initLabel) initLabel.style.display = '';
    if (errorPanel) errorPanel.style.display = 'none';
    if (video) video.style.display = '';

    navigator.mediaDevices
      .getUserMedia({ video: true })
      .then(function (stream) {
        activeStream = stream;
        video.srcObject = stream;
        video.onloadedmetadata = function () {
          video.play();
          // Start landmark loop once video is live
          loadEnrollFaceApi().then(function() { enrollLandmarkLoop(); });
          // Hide initialising label once stream is live
          if (initLabel) initLabel.style.display = 'none';
          // Enable capture controls unless the sample cap is already reached
          // (Req 3.9 ?Eonly enabled when camera is available)
          var alreadyAtMax = capturedSamples.length >= MAX_SAMPLES;
          captureBtn.disabled = alreadyAtMax;
          captureBtn.setAttribute('aria-disabled', alreadyAtMax ? 'true' : 'false');
        };
      })
      .catch(function () {
        showCameraError();
      });
  }

  /**
   * Display the camera error panel and disable capture controls.
   * Requirements 3.9: camera unavailable - error panel shown, capture disabled.
   */
  function showCameraError() {
    if (initLabel) initLabel.style.display = 'none';
    if (video)     video.style.display = 'none';
    if (errorPanel) errorPanel.style.display = '';
    captureBtn.disabled = true;
    captureBtn.setAttribute('aria-disabled', 'true');
  }

  /* -----------------------------------------------------------------------
     Sample capture
  ----------------------------------------------------------------------- */

  /**
   * Capture one JPEG frame from the live video stream.
   *
   * Steps:
   *  1. Draw current video frame onto a hidden canvas.
   *  2. Export as JPEG blob (quality = JPEG_QUALITY).
   *  3. Guard: reject if blob exceeds 5 MB (Req 3.2).
   *  4. Convert to data-URL, store in capturedSamples[], add thumbnail.
   *  5. Update UI state.
   */
  function captureFrame() {
    if (capturedSamples.length >= MAX_SAMPLES) return;

    // Create an off-screen canvas at the video's natural resolution
    var canvas = document.createElement('canvas');
    canvas.width  = video.videoWidth  || 640;
    canvas.height = video.videoHeight || 480;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    // Export as JPEG data-URL
    var dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);

    // Estimate byte size: base64 encodes ~4/3 bytes, subtract the header
    var base64Data = dataUrl.split(',')[1] || '';
    var approxBytes = Math.ceil(base64Data.length * 0.75);
    if (approxBytes > MAX_FRAME_BYTES) {
      showToast('Captured frame exceeds 5 MB. Please try again.', 'error');
      return;
    }

    // Store and display
    capturedSamples.push(dataUrl);
    addThumbnail(dataUrl, capturedSamples.length);
    updateUI();
  }

  /* -----------------------------------------------------------------------
     Thumbnail management
  ----------------------------------------------------------------------- */

  /**
   * Inject a thumbnail card for the newly captured sample.
   * @param {string} dataUrl  JPEG data-URL
   * @param {number} index    1-based sample number
   */
  function addThumbnail(dataUrl, index) {
    // Remove one placeholder slot if any remain
    var placeholder = thumbStrip.querySelector('.thumb-placeholder');
    if (placeholder) thumbStrip.removeChild(placeholder);

    var wrapper = document.createElement('div');
    wrapper.className = 'thumb-wrapper';
    wrapper.setAttribute('role', 'listitem');
    // Store index as a data attribute so the remove handler can find the sample
    wrapper.dataset.sampleIndex = String(index - 1); // 0-based array index

    var img = document.createElement('img');
    img.src = dataUrl;
    img.alt = 'Face sample ' + index;

    var badge = document.createElement('span');
    badge.className = 'thumb-badge';
    badge.textContent = index;

    var removeBtn = document.createElement('button');
    removeBtn.className = 'thumb-remove';
    removeBtn.type = 'button';
    removeBtn.setAttribute('aria-label', 'Remove sample ' + index);
    removeBtn.textContent = 'x';
    removeBtn.addEventListener('click', function () {
      removeSample(wrapper);
    });

    wrapper.appendChild(img);
    wrapper.appendChild(badge);
    wrapper.appendChild(removeBtn);
    thumbStrip.appendChild(wrapper);
  }

  /**
   * Remove a sample from the array and its thumbnail from the strip.
   * Re-numbers all remaining badges to stay sequential.
   * @param {HTMLElement} wrapper  The .thumb-wrapper element to remove
   */
  function removeSample(wrapper) {
    var arrayIndex = parseInt(wrapper.dataset.sampleIndex, 10);
    capturedSamples.splice(arrayIndex, 1);
    thumbStrip.removeChild(wrapper);

    // Re-index remaining thumbnails
    var remaining = thumbStrip.querySelectorAll('.thumb-wrapper');
    remaining.forEach(function (el, i) {
      el.dataset.sampleIndex = String(i);
      var badge = el.querySelector('.thumb-badge');
      if (badge) badge.textContent = String(i + 1);
      var btn = el.querySelector('.thumb-remove');
      if (btn) btn.setAttribute('aria-label', 'Remove sample ' + (i + 1));
    });

    // Restore a placeholder if we now have fewer than MAX_SAMPLES
    if (capturedSamples.length < MAX_SAMPLES) {
      var ph = document.createElement('div');
      ph.className = 'thumb-placeholder';
      ph.setAttribute('aria-hidden', 'true');
      ph.textContent = '+';
      // Insert before the first real thumb so placeholders stay on the right
      var firstThumb = thumbStrip.querySelector('.thumb-wrapper');
      if (firstThumb) {
        thumbStrip.insertBefore(ph, firstThumb);
      } else {
        thumbStrip.appendChild(ph);
      }
    }

    updateUI();
  }

  /**
   * Remove every sample and reset the thumbnail strip to its initial state.
   */
  function clearAllSamples() {
    capturedSamples = [];

    // Clear the strip entirely
    while (thumbStrip.firstChild) {
      thumbStrip.removeChild(thumbStrip.firstChild);
    }

    // Restore the three initial placeholder slots
    for (var i = 0; i < MIN_SAMPLES; i++) {
      var ph = document.createElement('div');
      ph.className = 'thumb-placeholder';
      ph.setAttribute('aria-hidden', 'true');
      ph.textContent = '+';
      thumbStrip.appendChild(ph);
    }

    updateUI();
  }

  /* -----------------------------------------------------------------------
     UI state management
  ----------------------------------------------------------------------- */

  /**
   * Synchronise all dynamic UI elements with the current capturedSamples[]
   * length and consent checkbox state.
   *
   * Controls updated:
   *  - #sample-counter text
   *  - #capture-btn disabled state (cap at MAX_SAMPLES)
   *  - #clear-samples-btn visibility
   *  - #req-consent badge class / text
   *  - #req-samples badge class / text
   *  - #submit-btn disabled state (enabled only when consent + MIN_SAMPLES met)
   */
  function updateUI() {
    var count       = capturedSamples.length;
    var hasConsent  = consentBox && consentBox.checked;
    var hasEnough   = count >= MIN_SAMPLES;
    var atMax       = count >= MAX_SAMPLES;
    var canSubmit   = hasConsent && hasEnough;

    // Sample counter badge
    if (sampleCounter) {
      sampleCounter.textContent = count + ' / ' + MAX_SAMPLES + ' samples';
      sampleCounter.className = atMax ? 'ready' : '';
    }

    // Capture button:
    //   - If camera hasn't started (button is currently disabled due to camera
    //     unavailability), leave it alone ?Edon't enable it here.
    //   - If camera IS running, control it purely by the sample cap.
    var cameraRunning = (activeStream !== null);
    if (cameraRunning) {
      captureBtn.disabled = atMax;
      captureBtn.setAttribute('aria-disabled', atMax ? 'true' : 'false');
    }

    // "Clear All" button ?Eshow only when there is at least one sample
    if (clearBtn) {
      clearBtn.style.display = count > 0 ? '' : 'none';
    }

    // Consent badge
    if (reqConsent) {
      if (hasConsent) {
        reqConsent.className = 'requirement requirement-ok';
        reqConsent.textContent = 'Consent OK';
      } else {
        reqConsent.className = 'requirement requirement-pending';
        reqConsent.textContent = 'Consent OK';
      }
    }

    // Samples badge
    if (reqSamples) {
      if (hasEnough) {
        reqSamples.className = 'requirement requirement-ok';
        reqSamples.textContent = count + ' / ' + MIN_SAMPLES + ' samples OK';
      } else {
        reqSamples.className = 'requirement requirement-pending';
        reqSamples.textContent = count + ' / ' + MIN_SAMPLES + ' samples OK';
      }
    }

    // Submit button
    submitBtn.disabled = !canSubmit;
    submitBtn.setAttribute('aria-disabled', canSubmit ? 'false' : 'true');

    // Next step button ?Eenabled once MIN_SAMPLES captured
    if (nextStepBtn) {
      nextStepBtn.disabled = !hasEnough;
      nextStepBtn.setAttribute('aria-disabled', hasEnough ? 'false' : 'true');
    }
  }

  /* -----------------------------------------------------------------------
     Form submission
  ----------------------------------------------------------------------- */

  /**
   * Intercept the enrollment form submit event.
   *
   * Validates:
   *  - Consent given (Req 3.3)
   *  - At least MIN_SAMPLES captured
   *  - All required text fields are non-empty (HTML5 validation)
   *
   * Serialises as JSON:
   *  {full_name, email, id_number, department, role, consent_given: 1,
   *   samples: [base64DataUrl, ...]}
   *
   * Posts to API_URL (POST /api/enroll).
   */
  function handleSubmit(evt) {
    evt.preventDefault();

    // ---- Client-side guards ----
    if (!consentBox || !consentBox.checked) {
      showFieldError('consent-checkbox',
        'You must provide consent under RA 10173 before enrolling.');
      return;
    }

    if (capturedSamples.length < MIN_SAMPLES) {
      showToast(
        'Please capture at least ' + MIN_SAMPLES + ' face samples before submitting.',
        'error'
      );
      return;
    }

    // HTML5 validation (covers required / minlength / maxlength / type="email")
    if (!enrollForm.checkValidity()) {
      enrollForm.reportValidity();
      return;
    }

    // ---- Build payload ----
    var fullName   = document.getElementById('full-name').value.trim();
    var email      = document.getElementById('email').value.trim();
    var idNumber   = document.getElementById('id-number').value.trim();
    var department = document.getElementById('department').value.trim();
    var role       = document.getElementById('role').value;

    // Strip the data-URL prefix ?Esend only the raw base64 content
    var samplesBase64 = capturedSamples.map(function (url) {
      return url.split(',')[1] || url;
    });

    var payload = {
      full_name:     fullName,
      email:         email,
      id_number:     idNumber,
      department:    department,
      role:          role,
      consent_given: 1,
      samples:       samplesBase64
    };

    // ---- Submit ----
    submitBtn.disabled = true;
    submitBtn.textContent = 'Enrolling...';

    fetch(API_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload)
    })
      .then(function (response) {
        return response.json().then(function (data) {
          return { ok: response.ok, status: response.status, data: data };
        });
      })
      .then(function (result) {
        if (result.ok) {
          handleEnrollSuccess(result.data);
        } else {
          handleEnrollError(result.data, result.status);
        }
      })
      .catch(function (err) {
        // Network / parse error
        showToast('Network error: ' + (err.message || 'Could not reach server.'), 'error');
        resetSubmitButton();
      });
  }

  /**
   * Handle a successful enrollment response (HTTP 200/201).
   * @param {Object} data  Parsed JSON response body
   */
  function handleEnrollSuccess(data) {
    var name = data.full_name || 'User';
    showToast(name + ' enrolled successfully!', 'success');

    // Reset the form and capture state for the next enrollment
    enrollForm.reset();
    clearAllSamples();
    resetSubmitButton();
    updateUI();
  }

  /**
   * Handle an enrollment error response (HTTP 4xx/5xx).
   * Surfaces specific field errors from the API where possible.
   * @param {Object} data    Parsed JSON error body
   * @param {number} status  HTTP status code
   */
  function handleEnrollError(data, status) {
    var message = (data && data.error) ? data.error : 'Enrollment failed (HTTP ' + status + ').';

    // Surface field-level errors if the API provides them
    if (data && data.field) {
      showFieldError(data.field, message);
    } else {
      showToast(message, 'error');
    }

    resetSubmitButton();
  }

  /**
   * Restore the submit button to its pre-submit label and correct disabled state.
   */
  function resetSubmitButton() {
    submitBtn.textContent = 'Enroll User';
    updateUI();  // let updateUI decide the disabled state
  }

  /* -----------------------------------------------------------------------
     Validation helpers
  ----------------------------------------------------------------------- */

  /**
   * Mark a specific form field as invalid and display an error message.
   * @param {string} fieldId    ID of the input element
   * @param {string} message    Error text
   */
  function showFieldError(fieldId, message) {
    var field = document.getElementById(fieldId);
    var errorEl = document.getElementById(fieldId + '-error');
    if (field) {
      field.classList.add('is-invalid');
      field.addEventListener('input', function clearErr() {
        field.classList.remove('is-invalid');
        if (errorEl) errorEl.textContent = '';
        field.removeEventListener('input', clearErr);
      }, { once: true });
    }
    if (errorEl) {
      errorEl.textContent = message;
    } else {
      // Fallback: show a toast if no dedicated error element exists
      showToast(message, 'error');
    }
  }

  /* -----------------------------------------------------------------------
     Toast helper
     Uses the global showToast() defined in base.html when available;
     falls back to a simple alert so enroll.js works standalone in tests.
  ----------------------------------------------------------------------- */
  function showToast(message, type) {
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      // Minimal fallback ?Eshould never reach this in production
      alert('[' + (type || 'info').toUpperCase() + '] ' + message);
    }
  }

  /* -----------------------------------------------------------------------
     Event wiring
  ----------------------------------------------------------------------- */

  // Capture button
  captureBtn.addEventListener('click', function () {
    if (!captureBtn.disabled) captureFrame();
  });

  // Clear-all button
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      clearAllSamples();
    });
  }

  // Retry camera button
  if (retryCamBtn) {
    retryCamBtn.addEventListener('click', function () {
      // Stop any existing stream before retrying
      if (activeStream) {
        activeStream.getTracks().forEach(function (t) { t.stop(); });
        activeStream = null;
      }
      startCamera();
    });
  }

  // Consent checkbox ?Ere-evaluate submit eligibility on every change
  if (consentBox) {
    consentBox.addEventListener('change', updateUI);
  }

  // Form submit handler
  if (enrollForm) {
    enrollForm.addEventListener('submit', handleSubmit);
  }

  /* -----------------------------------------------------------------------
     Wizard step navigation
  ----------------------------------------------------------------------- */

  // Step indicators
  var stepInd1 = document.getElementById('step-ind-1');
  var stepInd2 = document.getElementById('step-ind-2');

  function goToStep1() {
    if (step1) step1.style.display = '';
    if (step2) step2.style.display = 'none';
    if (stepInd1) stepInd1.classList.add('active');
    if (stepInd2) stepInd2.classList.remove('active');
  }

  function goToStep2() {
    if (step1) step1.style.display = 'none';
    if (step2) step2.style.display = '';
    if (stepInd1) stepInd1.classList.remove('active');
    if (stepInd2) stepInd2.classList.add('active');
    if (step2Preview) {
      while (step2Preview.firstChild) {
        step2Preview.removeChild(step2Preview.firstChild);
      }
      capturedSamples.forEach(function (dataUrl, i) {
        var img = document.createElement('img');
        img.src = dataUrl;
        img.alt = 'Face sample ' + (i + 1);
        step2Preview.appendChild(img);
      });
    }
  }

  if (nextStepBtn) {
    nextStepBtn.addEventListener('click', function () {
      if (capturedSamples.length >= MIN_SAMPLES) goToStep2();
    });
  }

  if (backStepBtn) {
    backStepBtn.addEventListener('click', function () {
      goToStep1();
    });
  }

  /* -----------------------------------------------------------------------
     Bootstrap
  ----------------------------------------------------------------------- */

  // Initialise UI badges (all pending, no samples, no consent)
  updateUI();

  // Start the webcam stream
  startCamera();


  /* -----------------------------------------------------------------------
     face-api.js landmark skeleton on enroll webcam
  ----------------------------------------------------------------------- */
  var enrollFaceApiReady  = false;
  var enrollLatest        = [];
  var MODELS_PATH         = '/static/models';
  var enrollLandmarkCanvas = document.getElementById('face-detect-canvas');
  var enrollLandmarkCtx   = enrollLandmarkCanvas ? enrollLandmarkCanvas.getContext('2d') : null;

  async function loadEnrollFaceApi() {
    try {
      if (typeof faceapi === 'undefined') return;
      await faceapi.nets.tinyFaceDetector.loadFromUri(MODELS_PATH);
      await faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODELS_PATH);
      enrollFaceApiReady = true;
    } catch(e) {
      console.warn('enroll face-api load failed:', e);
    }
  }

  function drawEnrollSkeleton(ctx, pts, canvasWidth) {
    if (!pts || pts.length < 68) return;
    function pt(i) { return { x: canvasWidth - pts[i].x, y: pts[i].y }; }
    function drawRegion(indices, close) {
      ctx.beginPath();
      ctx.moveTo(pt(indices[0]).x, pt(indices[0]).y);
      for (var i = 1; i < indices.length; i++) ctx.lineTo(pt(indices[i]).x, pt(indices[i]).y);
      if (close) ctx.closePath();
      ctx.stroke();
    }
    ctx.strokeStyle = 'rgba(0, 220, 255, 0.75)';
    ctx.lineWidth = 1.2;
    drawRegion([0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16], false);
    drawRegion([17,18,19,20,21], false);
    drawRegion([22,23,24,25,26], false);
    drawRegion([27,28,29,30], false);
    drawRegion([30,31,32,33,34,35,30], false);
    drawRegion([36,37,38,39,40,41], true);
    drawRegion([42,43,44,45,46,47], true);
    drawRegion([48,49,50,51,52,53,54,55,56,57,58,59], true);
    drawRegion([60,61,62,63,64,65,66,67], true);
    ctx.fillStyle = 'rgba(0, 255, 220, 0.9)';
    for (var i = 0; i < 68; i++) {
      var p = pt(i);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 1.8, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function enrollLandmarkLoop() {
    requestAnimationFrame(enrollLandmarkLoop);
    if (!enrollLandmarkCtx || !enrollLandmarkCanvas || !video) return;

    // Sync canvas to video display size
    var rect = video.getBoundingClientRect();
    if (rect.width > 0 && enrollLandmarkCanvas.width !== rect.width) enrollLandmarkCanvas.width = rect.width;
    if (rect.height > 0 && enrollLandmarkCanvas.height !== rect.height) enrollLandmarkCanvas.height = rect.height;

    // Clear canvas
    enrollLandmarkCtx.clearRect(0, 0, enrollLandmarkCanvas.width, enrollLandmarkCanvas.height);

    // Draw stored landmarks
    enrollLatest.forEach(function(det) {
      drawEnrollSkeleton(enrollLandmarkCtx, det.landmarks.positions, enrollLandmarkCanvas.width);
    });

    // Fire async detection
    if (enrollFaceApiReady && video.readyState >= 2) {
      var dSize = { width: enrollLandmarkCanvas.width, height: enrollLandmarkCanvas.height };
      if (dSize.width > 0 && dSize.height > 0) {
        faceapi.matchDimensions(enrollLandmarkCanvas, dSize);
        faceapi.detectAllFaces(video, new faceapi.TinyFaceDetectorOptions({
          inputSize: 320, scoreThreshold: 0.3
        })).withFaceLandmarks(true).then(function(detections) {
          var resolvedSize = { width: enrollLandmarkCanvas.width, height: enrollLandmarkCanvas.height };
          if (resolvedSize.width > 0 && resolvedSize.height > 0) {
            enrollLatest = faceapi.resizeResults(detections, resolvedSize);
          }
        });
      }
    }
  }
})();
