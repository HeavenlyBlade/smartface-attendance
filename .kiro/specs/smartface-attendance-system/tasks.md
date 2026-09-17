# Implementation Plan: SmartFace Attendance System

## Overview

Build SmartFace — a real-time face recognition attendance monitoring system for SACLI — as a Flask web application with a dlib-based recognition pipeline, MySQL persistence, and Jinja2 templates. The plan follows the 5-day build order: Foundation → Enrollment → Recognition Loop → Dashboard/Reports/Audit → Polish/Tests. Each day's output is a vertical slice that runs end-to-end. Property-based tests use **Hypothesis**; all 12 design correctness properties are covered. Tasks marked `*` are optional and can be skipped for an MVP build.

---

## Tasks

- [x] 1. Day 1 — Foundation: project skeleton, database schema, auth

  - [x] 1.1 Verify dlib installation and create `requirements.txt`
    - Attempt `pip install cmake` then `pip install dlib`; if build fails after ~15 min, switch to pre-compiled Gohlke wheel; fallback 3: `conda install -c conda-forge dlib`; fallback 4 (contingency): swap to `deepface` in `face_service.py` only — no route or model changes needed
    - Create `requirements.txt` with the locked dependency list: `Flask`, `mysql-connector-python`, `face_recognition`, `opencv-python`, `numpy`, `Pillow`, `Werkzeug`, `python-dotenv`, `hypothesis`, `pytest`
    - _Requirements: 15.2_

  - [x] 1.2 Create `database/schema.sql` with all four tables
    - Write `CREATE DATABASE IF NOT EXISTS smartface_db` with InnoDB / utf8mb4
    - Define `users`, `face_encodings`, `attendance` (with `UNIQUE KEY uniq_user_day (user_id, date)`), and `audit_logs` exactly as specified
    - _Requirements: 5.0 (schema), 6.4, 9.2_

  - [x] 1.3 Implement `config.py` and `.env.example`
    - Expose `TOLERANCE=0.45`, `LATE_TIME='08:00:00'`, `SECRET_KEY`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASS`, `DB_NAME`, `UPLOAD_DIR`, `BRIGHTNESS_THRESHOLD=50` — all loaded from `.env` via `os.getenv` with documented defaults
    - Create `.env.example` listing every key with placeholder values
    - _Requirements: 6.6_

  - [x] 1.4 Implement `models/db.py` — connection pool and query helpers
    - Create `get_connection()` using `mysql-connector-python` connection pooling
    - Implement `execute_query(sql, params=())` and `execute_many(sql, params_list)` — all queries use parameterized `%s` placeholders, never string interpolation
    - _Requirements: 1.0 (auth), 5.0 (schema)_

  - [x] 1.5 Create Flask application entry point `app.py`
    - Instantiate Flask app, load `.env`, configure `SESSION_PERMANENT`, `PERMANENT_SESSION_LIFETIME = timedelta(minutes=30)`, `SECRET_KEY`
    - Register blueprints: `auth`, `admin`, `attendance_routes`, `api`
    - Add startup hook: `with app.app_context(): face_service.load_known_faces()`
    - Include `# app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')` as a commented-out LAN HTTPS line
    - Use `app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)` — `use_reloader=False` protects the in-memory encoding cache
    - Register error handlers for 404, 403, 500
    - _Requirements: 1.0, 4.1, 15.1_

  - [x] 1.6 Implement `routes/auth.py` — login, logout, `@role_required` decorator, account lockout
    - `@role_required(*roles)` decorator: check session for `user_id` (401 if missing), check `session['role']` in allowed roles (403 if not), apply 30-min inactivity check
    - `GET/POST /login`: validate credentials with `check_password_hash`; on failure increment lockout counter; on 5 failures within 15 min lock account for 15 min and display lockout message; on success write `audit_logs` entry, redirect to role landing page
    - `GET /logout`: clear session, write `audit_logs` entry, redirect to login
    - Generic error message on failed login — never reveal which field failed
    - `GET /`: role-based redirect (admin → `/dashboard`, faculty → `/kiosk`, student → `/my-attendance`)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.7_

  - [x] 1.7 Write property test for password storage (Property 5)
    - **Property 5: No plaintext passwords stored**
    - **Validates: Requirements 1.6**
    - Use `@given(text(min_size=8, max_size=64).filter(lambda s: s.strip()))` to generate passwords; assert `generate_password_hash(pw) != pw` and `check_password_hash(hashed, pw) is True`

  - [x] 1.8 Write property tests for RBAC student and faculty blocking (Properties 3, 4)
    - **Property 3: Student role blocked from non-student routes — Validates: Requirements 2.2, 2.6**
    - **Property 4: Faculty role blocked from admin-only routes — Validates: Requirements 2.3, 2.5**
    - Use `@given(sampled_from(NON_STUDENT_ROUTES))` and `@given(sampled_from(ADMIN_ONLY_ROUTES))`; assert 403 responses via Flask test client with mocked sessions

  - [x] 1.9 Create `templates/base.html` and `templates/login.html`
    - `base.html`: SACLI color scheme (light green `#4CAF82`, white `#FFFFFF`, gold `#D4AF37`, near-black `#1A1A1A`), role-aware nav rendered via `{{ session.role }}`, toast notification container, audio elements for success/failure cues
    - `login.html` extends `base.html`: email/password form, error display block
    - _Requirements: 1.1, 1.2, 15.3_

  - [x] 1.10 Implement `models/user.py` — user data-access wrapper
    - Plain-dict returning functions: `get_user_by_email(email)`, `get_user_by_id(user_id)`, `create_user(...)`, `update_user(user_id, fields)`, `deactivate_user(user_id)`, `list_users(page, per_page=25)`
    - All queries parameterized; no ORM
    - _Requirements: 10.1, 10.2, 10.3_

  - [x] 1.11 Implement `models/audit.py` — audit log data-access wrapper
    - `write_audit(user_id, action, details, ip_address)`: INSERT into `audit_logs`; on failure log to application error log, do NOT raise to user
    - `list_audit(page, per_page=25, action_filter=None, start_date=None, end_date=None)`
    - _Requirements: 11.2, 11.3_

  - [x] 1.12 Create `database/seed.py` — 30 dummy users and 3 weeks of attendance data
    - Seed 1 admin, 5 faculty, 24 students; hash all passwords; set `consent_given=1` for all; generate realistic `attendance` rows (mix of present/late/absent) for 21 days; skip weekends
    - _Requirements: (demo support)_

  - [x] 1.13 Checkpoint — Day 1 complete
    - Ensure the Flask app starts (`python app.py`), login works with the seeded admin account, incorrect credentials show a generic error, and the DB tables are created by `schema.sql`
    - Ask the user if any Day 1 issues need resolving before proceeding.

---

- [x] 2. Day 2 — Enrollment: face service, enrollment UI, user management

  - [x] 2.1 Implement `services/face_service.py` — encoding cache, serialization, and startup load
    - Module-level state: `known_encodings: list[np.ndarray] = []`, `known_user_ids: list[int] = []`, `_cache_lock = threading.Lock()`
    - `load_known_faces()`: load all non-null BLOB rows from `face_encodings`, deserialize with `np.frombuffer(blob, dtype=np.float64)`, skip undeserializable rows; if DB unreachable log error and return with empty cache
    - `reload_known_faces()`: atomically rebuild both lists inside `_cache_lock`; called after every successful enrollment
    - `serialize_encoding(enc)`: `enc.tobytes()` — `np.ndarray(128, float64)` → `bytes` (length 1024)
    - `deserialize_encoding(blob)`: `np.frombuffer(blob, dtype=np.float64)` → shape `(128,)`
    - `encode_samples(image_list)`: returns one 128-dim encoding per image
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 2.2 Write property test for encoding round-trip (Property 1)
    - **Property 1: Facial encoding serialization round-trip**
    - **Validates: Requirements 3.7, 4.2**
    - `@given(arrays(dtype=np.float64, shape=128))`: assert `np.array_equal(enc, np.frombuffer(enc.tobytes(), dtype=np.float64))`

  - [x] 2.3 Write property test for cache–database alignment after reload (Property 2)
    - **Property 2: Cache–database alignment after reload**
    - **Validates: Requirements 4.2, 4.4**
    - `@given(lists(arrays(dtype=np.float64, shape=128), min_size=0, max_size=50))`: insert generated encodings into test DB, call `reload_known_faces()`, assert `len(known_encodings) == len(known_user_ids) == inserted_count`

  - [x] 2.4 Implement enrollment route `GET /enroll` and `templates/enroll.html`
    - Form fields: full name (1–100 chars), email (valid format, max 254), ID number (1–50), department (1–100), role selector, consent checkbox referencing RA 10173
    - Webcam preview area (min 320×240); thumbnail strip for captured samples
    - Disable submit until consent is checked and ≥ 3 samples captured
    - If webcam unavailable: display camera error panel, disable capture controls
    - Protect with `@role_required('admin')`
    - _Requirements: 3.1, 3.2, 3.3, 3.9_

  - [x] 2.5 Implement `static/js/enroll.js` — webcam capture for enrollment
    - Use `getUserMedia` to open webcam; capture 3–5 still frames on button click; display JPEG thumbnail preview per shot; enforce max 5 MB per frame; POST all samples + form fields to `POST /api/enroll`
    - _Requirements: 3.2_

  - [x] 2.6 Implement `POST /api/enroll` in `routes/api.py`
    - Validate consent (`consent_given == 1`); reject with 400 if not — RA 10173 compliance
    - Detect face in each sample via `encode_samples()`; if any sample has no face return JSON error identifying the sample index (1–5), no DB writes
    - Check for duplicate email / ID number; return JSON error naming the conflicting field if found
    - In a transaction: INSERT `users` row with `consent_given=1`; INSERT `face_encodings` BLOBs; save raw JPEGs to `uploads/face_samples/`; write `audit_logs` entry; call `reload_known_faces()`
    - On any failure after `users` row is created: roll back all DB records, return JSON error identifying the failed step
    - Full operation must complete within 30 seconds
    - Protect with `@role_required('admin')`
    - _Requirements: 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 2.7 Implement `GET /users` and `templates/users.html` — user management page
    - Paginated list (25/page): `full_name`, `id_number`, `role`, `department`, `is_active`
    - Deactivate user: set `is_active=0`, write `audit_logs` entry; block admin self-deactivation with error "You cannot deactivate your own account."
    - Edit profile fields: full name, department, role, id_number
    - Delete biometric data: remove all `face_encodings` rows + raw JPEGs + call `reload_known_faces()`
    - Protect with `@role_required('admin')`
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

  - [x] 2.8 Checkpoint — Day 2 complete
    - Verify: enroll a new user via the UI, confirm encoding rows in DB, confirm `reload_known_faces()` updated the cache count, confirm duplicate email is rejected, confirm no-face image is rejected.
    - Ask the user if any Day 2 issues need resolving before proceeding.

---

- [x] 3. Day 3 — Core recognition loop: kiosk, recognition API, attendance logging

  - [x] 3.1 Create `templates/kiosk.html` and `GET /kiosk` route
    - Video element (live stream) + overlay canvas (bounding boxes + labels) layered on top
    - Name label font ≥ 2rem; body text ≥ 1.5rem for projector visibility
    - Toast notification area + audio elements (success cue on match, failure cue on Unknown)
    - Brightness warning banner (hidden by default, shown by JS)
    - Camera permission error panel (displayed if `getUserMedia` is denied)
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 5.1, 5.2, 5.9, 13.1, 13.3, 13.4, 15.1_

  - [x] 3.2 Implement `static/js/camera.js` — frame capture loop
    - `getUserMedia({video: true})`; on denial show camera instruction panel and stop
    - `setInterval` every 1000ms (±50ms): if `pending == true` skip the tick; else set `pending=true`, draw frame to hidden canvas at full resolution
    - Compute mean pixel brightness (exclude alpha channel); if mean < `BRIGHTNESS_THRESHOLD` show warning banner; hide when ≥ threshold
    - `canvas.toDataURL('image/jpeg', 0.7)` → strip prefix → POST base64 to `POST /api/recognize`
    - On response: call `drawOverlay(data.faces)` — clear overlay canvas, draw bounding box + name/confidence label per face; set `pending=false`
    - On fetch error: set `pending=false`, continue loop
    - _Requirements: 5.3, 5.9, 13.1, 13.2, 13.3, 13.4_

  - [x] 3.3 Implement `services/face_service.py` — `recognize_frame(image_b64)` pipeline
    - Step 1: base64 decode → `np.frombuffer` → `cv2.imdecode(np_arr, cv2.IMREAD_COLOR)` → return 400 if result is `None`
    - Step 2: downscale 0.25× with `cv2.resize` — non-negotiable for usable framerate; add heavy comment explaining the ~4× speedup
    - Step 3: BGR → RGB with `cv2.cvtColor(small, cv2.COLOR_BGR2RGB)` — comment explaining face_recognition expects RGB
    - Step 4: `face_recognition.face_locations(rgb)` — detect bounding boxes in downscaled frame
    - Step 5: `face_recognition.face_encodings(rgb, locs)` — compute 128-dim encodings
    - Step 6: `face_recognition.face_distance(known_encodings, enc)` — Euclidean distances against cache
    - Step 7: `best_dist <= TOLERANCE` check (0.45); include `# LIVENESS HOOK: a liveness check (blink / head-movement) would be inserted here` comment at the exact match-acceptance line
    - Step 8: scale bounding box back to original dimensions (multiply by 4); return `[{user_id, full_name, confidence, bounding_box}]`
    - If `known_encodings` is empty: return all faces as Unknown, no exception
    - _Requirements: 5.4, 5.5, 5.6, 5.7, 5.8, 5.10, 14.1_

  - [x] 3.4 Write property test for confidence formula correctness (Property 6)
    - **Property 6: Confidence formula correctness**
    - **Validates: Requirements 5.6**
    - `@given(floats(min_value=0.0, max_value=0.45))`: assert `compute_confidence(d) == round((1 - d) * 100, 2)` and `55.0 <= result <= 100.0`

  - [x] 3.5 Write property test for unknown face classification (Property 7)
    - **Property 7: Unknown face classification above tolerance**
    - **Validates: Requirements 5.7, 6.1**
    - `@given(floats(min_value=0.451, max_value=2.0))`: assert result has `user_id=None` and `full_name="Unknown"`

  - [x] 3.6 Write property test for multi-face response completeness (Property 11)
    - **Property 11: N faces in frame → N entries in response**
    - **Validates: Requirements 5.10**
    - `@given(integers(min_value=0, max_value=5))`: mock `face_recognition` to return N locations/encodings; assert `len(recognize_frame(mock_b64)) == N`

  - [x] 3.7 Implement `POST /api/recognize` in `routes/api.py`
    - Decode JSON body `{image: base64_string}`; return 400 `{"error": "Invalid image payload"}` on bad base64
    - Call `face_service.recognize_frame(image_b64)`; return 400 `{"error": "Could not decode image"}` if image is None
    - For each result with `user_id != None`: call `attendance_service.log_attendance(user_id, confidence)`
    - Return 200 `{"faces": [...]}` always — never 500 on no-face result
    - Return 503 `{"error": "Database unavailable"}` on DB error during attendance log
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 5.4, 5.5, 5.6, 5.7, 5.8, 5.10_

  - [x] 3.8 Implement `services/attendance_service.py` and `models/attendance.py`
    - Module-level: `last_seen_dict: dict[int, datetime] = {}`
    - `_is_debounce_elapsed(user_id)`: return True if no entry or elapsed ≥ 60 seconds
    - `_determine_status(time_in)`: compare against `config.LATE_TIME`; return `'present'` or `'late'`
    - `log_attendance(user_id, confidence)`:
      - Guard 1: `_is_debounce_elapsed` — return `{"logged": False, "reason": "debounce"}` if not elapsed
      - Guard 2: `INSERT INTO attendance ... ON DUPLICATE KEY UPDATE time_out = VALUES(time_in), confidence = VALUES(confidence)` — never raw INSERT
      - On DB success: update `last_seen_dict[user_id] = now`
      - On DB failure: leave `last_seen_dict` unchanged; return error response
    - `models/attendance.py`: `get_today_records()`, `get_records(filters)`, `manual_override(user_id, date, admin_id)`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x] 3.9 Write property test for attendance status assignment (Property 8)
    - **Property 8: Attendance status assignment by time_in vs LATE_TIME**
    - **Validates: Requirements 6.1**
    - `@given(times())`: assert `determine_status(t) == 'present'` when `t <= LATE_TIME`, `'late'` when `t > LATE_TIME`

  - [x] 3.10 Write property test for debounce uniqueness invariant (Property 9)
    - **Property 9: At most one attendance row per user per day**
    - **Validates: Requirements 6.2, 6.3, 6.4**
    - `@given(integers(min_value=1, max_value=1000), lists(integers(min_value=0, max_value=3600), min_size=1, max_size=20))`: simulate N recognitions at various second offsets against a test DB; assert row count == 1

  - [x] 3.11 Write property test for debounce skip under 60 seconds (Property 10)
    - **Property 10: DB unchanged when elapsed < 60 seconds**
    - **Validates: Requirements 6.3**
    - `@given(integers(min_value=0, max_value=59))`: seed `last_seen_dict` with `now - elapsed`; call `log_attendance`; assert no DB writes occurred

  - [x] 3.12 Checkpoint — Day 3 complete
    - Verify: open `/kiosk`, webcam loads, a face is detected and the overlay draws a bounding box with name/confidence, attendance row appears in DB, second recognition within 60 s does not create a duplicate row.
    - Ask the user if any Day 3 issues need resolving before proceeding.

---

- [x] 4. Day 4 — Dashboard, reports, audit, and student self-service

  - [x] 4.1 Implement `GET /dashboard`, `templates/dashboard.html`, and `static/js/dashboard.js`
    - Summary cards: count present today, count late today, total registered active users — all non-negative integers
    - `dashboard.js`: `setInterval` every 3 s, fetch `GET /api/live-feed`, update attendance table in-place (no full page reload); on error or timeout > 5 s retain last table, show "Live feed temporarily unavailable" indicator
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 7.6_

  - [x] 4.2 Implement `GET /api/live-feed` in `routes/api.py`
    - Return JSON list of today's records (matched by server date): `full_name`, `id_number`, `time_in` (HH:MM:SS), `time_out` (HH:MM:SS), `status`, `confidence`
    - Only records whose `date` matches today's date in server timezone
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 7.3, 7.4_

  - [x] 4.3 Implement `GET /reports`, `templates/reports.html`
    - Filter controls: start date (YYYY-MM-DD), end date (YYYY-MM-DD), role selector, department text field (max 100 chars)
    - Client-side validation: if start date > end date, show error and do not submit
    - Paginated results table: 50 records/page, load within 3 s
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 8.1, 8.2, 8.3_

  - [x] 4.4 Implement `GET /reports/export?format=csv` — CSV download
    - Return CSV with columns `full_name`, `id_number`, `department`, `role`, `date`, `time_in`, `time_out`, `status`, `confidence` in that order with a header row
    - If no matching records: return CSV with header row only, no error
    - If invalid filter params (start > end, unrecognized role/department): return error, no CSV
    - Protect with `@role_required('admin', 'faculty')`
    - _Requirements: 8.4, 8.5, 8.6_

  - [x] 4.5 Implement `POST /attendance/manual` — admin override route
    - Validate `user_id` exists (404 if not), validate `date` is a valid calendar date and ≤ 365 days in the past (error if not)
    - INSERT or UPDATE `attendance` row with `status='manual'`, `marked_by=admin_user_id`
    - Write `audit_logs` entry within 2 s; if audit write fails: roll back attendance change, return error
    - Protect with `@role_required('admin')`
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [x] 4.6 Implement `GET /audit` and `templates/audit.html` — audit log viewer (CUT LIST PRIORITY 1)
    - Paginated reverse-chronological list (25/page): timestamp, acting user, action type, details, IP address
    - Filter controls: action type selector, date range
    - Protect with `@role_required('admin')`
    - _Requirements: 11.1_

  - [x] 4.7 Implement `GET /my-attendance` and `templates/my_attendance.html` — student self-service (CUT LIST PRIORITY 2)
    - Display only attendance records for `session['user_id']`; sorted descending by date
    - Columns: `date`, `time_in`, `time_out`, `status` (Present / Late / Absent)
    - If no records: show "No attendance records found."
    - Never expose any other user's records
    - Protect with `@role_required('student')`
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 4.8 Write property test for student data isolation (Property 12)
    - **Property 12: Student only sees own attendance records**
    - **Validates: Requirements 12.1, 12.3**
    - `@given(integers(min_value=1, max_value=100))`: authenticate as `student_id`, GET `/my-attendance`, assert all returned records have `user_id == student_id`

  - [x] 4.9 Checkpoint — Day 4 complete
    - Verify: dashboard shows live counts, live-feed table updates every 3 s, reports filter works, manual override sets status to `'manual'`, audit log entry is written for override.
    - Ask the user if any Day 4 issues need resolving before proceeding.

---

- [x] 5. Day 5 — Polish, error handling, tests, README

  - [x] 5.1 Implement comprehensive error handling across all layers
    - `POST /api/recognize`: invalid base64 → 400; `cv2.imdecode` returns `None` → 400; no face → 200 `{"faces": []}`; DB down → 503
    - `POST /api/enroll`: camera unavailable panel; no-face in sample → JSON error with sample index; duplicate field → JSON error naming field; partial failure → rollback
    - Auth: 5 failures → 15-min lockout message; session timeout → redirect with expiry message; unauthenticated request → 302 to login
    - DB errors: unreachable at startup → empty cache + log error; audit write fail → log to app error log, do not propagate as unhandled exception
    - _Requirements: 1.2, 1.3, 1.5, 1.7, 4.6, 5.5, 5.8, 6.7, 11.3, 13.1_

  - [x] 5.2 UI polish pass — projector-ready kiosk, consistent SACLI branding
    - `kiosk.html`: body font ≥ 1.5rem, name label ≥ 2rem, high-contrast bounding box colors
    - All pages: SACLI color scheme, readable on projector, role-aware nav hides/shows links based on `{{ session.role }}`
    - Audio cues wired: success sound on matched face, failure sound on Unknown
    - _Requirements: 13.1, 13.2, 13.3, 15.3_

  - [x] 5.3 Create `tests/conftest.py` and test infrastructure
    - `test_app` fixture: `TESTING=True`, `DB_NAME='smartface_test_db'`, `test_client()`
    - Helper to seed test DB with a small user set and face encodings
    - Hypothesis `settings(max_examples=100, deadline=5000)` applied globally
    - _Requirements: (test infra)_

  - [x] 5.4 Write remaining unit tests in `tests/test_auth.py`, `tests/test_enrollment.py`, `tests/test_reports.py`, `tests/test_override.py`, `tests/test_dashboard.py`
    - Auth: correct credentials → session created; wrong email/password → generic error; session timeout after 30 min; logout → session cleared + audit log
    - Enrollment: valid 3-image submission → user row + 3 encoding rows + audit log + cache reload; no consent → 400; no-face image → JSON error; duplicate email → JSON error
    - Reports: valid filter → paginated rows; no results → empty result set (not error); start > end → error response
    - Override: valid override → `status='manual'`, `marked_by` set; missing user → 404; date > 365 days ago → error; audit fail → rollback
    - Dashboard: live-feed endpoint error retained table + indicator shown
    - _Requirements: 1.1–1.7, 3.1–3.9, 8.1–8.6, 9.1–9.5, 7.5_

  - [x] 5.5 Write `tests/test_face_service.py` and `tests/test_attendance_service.py` wrapping all property tests
    - Collate property stubs from tasks 2.2, 2.3, 3.4–3.6, 3.9–3.11 into final test files
    - Add `tests/test_student_isolation.py` containing Property 12 test from task 4.8
    - Add `tests/test_auth.py` section for Properties 3, 4, 5 from task 1.7–1.8
    - _Requirements: (all correctness properties 1–12)_

  - [x] 5.6 Write `README.md` with setup steps for the panel
    - Sections: Prerequisites (Python 3.11, MySQL, Visual C++ Build Tools for dlib); dlib install options (cmake path, Gohlke wheel path, conda path, deepface contingency); `.env` setup with reference to `.env.example`; DB init (`mysql < database/schema.sql`); seed (`python database/seed.py`); run (`python app.py`); default admin credentials; port / LAN HTTPS notes
    - _Requirements: 15.0 (defense readiness)_

  - [x] 5.7 Final checkpoint — full system walkthrough
    - Confirm: app starts, seeded admin logs in, enrollment works, kiosk recognizes a known face, attendance row created, dashboard updates live, reports filter and (if not cut) CSV export work, manual override writes audit log, README instructions are accurate.
    - Ensure all non-optional tests pass (`pytest tests/ --tb=short -q`).
    - Ask the user if anything needs adjustment before the defense.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP. Cut in this order: 4.6 (audit viewer UI), 4.7 (student self-service), 4.3 with department sub-filter (reduce to date/role only), 4.4 (CSV export). Audit log _writes_ (task 1.11) are **never** optional.
- Property-based tests reference design document properties by number. Run with `pytest tests/ --tb=short -q` (single pass, no watch mode).
- `use_reloader=False` is required in `app.run()` — Flask's reloader spawns a child process which loses the in-memory encoding cache.
- `getUserMedia` requires `localhost` or HTTPS. Demo runs on `http://localhost:5000`. The commented-out `ssl_context='adhoc'` line in `app.py` enables LAN HTTPS without a certificate.
- All SQL queries must use `%s` parameterized placeholders — no f-strings or string concatenation in SQL.
- The liveness detection hook comment (Requirements 14.1) must be present at the exact match-acceptance line in `face_service.py` — the thesis panel will ask about it.
- RA 10173 compliance: `consent_given=1` must be set before any `face_encodings` row is created. The server validates this regardless of front-end state.
- Each task references the minimal set of requirements it directly satisfies; the full design document is assumed available during implementation.

---

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4"] },
    { "id": 2, "tasks": ["1.5", "1.10", "1.11", "1.12"] },
    { "id": 3, "tasks": ["1.6", "1.9"] },
    { "id": 4, "tasks": ["1.7", "1.8"] },
    { "id": 5, "tasks": ["2.1"] },
    { "id": 6, "tasks": ["2.2", "2.3", "2.4", "2.7"] },
    { "id": 7, "tasks": ["2.5"] },
    { "id": 8, "tasks": ["2.6"] },
    { "id": 9, "tasks": ["3.1", "3.3", "3.8"] },
    { "id": 10, "tasks": ["3.2", "3.7"] },
    { "id": 11, "tasks": ["3.4", "3.5", "3.6", "3.9", "3.10", "3.11"] },
    { "id": 12, "tasks": ["4.1", "4.3", "4.5"] },
    { "id": 13, "tasks": ["4.2"] },
    { "id": 14, "tasks": ["4.4", "4.6", "4.7"] },
    { "id": 15, "tasks": ["4.8"] },
    { "id": 16, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 17, "tasks": ["5.4", "5.5"] },
    { "id": 18, "tasks": ["5.6"] }
  ]
}
```
