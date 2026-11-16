# SmartFace — Technical Audit & Issue Prediction

**Project:** `C:\Users\Asus\Desktop\SmartFace`
**Type:** Flask web app for real-time face-recognition attendance (capstone for St. Anne College Lucena). Python 3.11, Flask 3.0.3, face_recognition/dlib, PostgreSQL (Supabase) via psycopg2, waitress WSGI.
**Scope:** read-only audit of structure, dependencies, code quality, config, secrets, tests, build/CI, performance, docs. Nothing was modified.

---

## Summary answer (key finding first)

The single most important issue is a **database-dialect mismatch that breaks the app's core function in production**: the attendance-logging path and the seed script still emit MySQL `ON DUPLICATE KEY UPDATE … VALUES(col)` syntax, but the backend is PostgreSQL. Every successful face recognition that tries to record attendance raises a PostgreSQL syntax error, so `POST /api/recognize` returns `503` and **no attendance is ever recorded**. The migration to PostgreSQL was finished in some modules (`manual_override` correctly uses `ON CONFLICT … DO UPDATE SET … EXCLUDED.…`) but was missed in `services/attendance_service.py` and `database/seed.py`, and the test suite never catches it because it mocks the DB layer.

Beyond that: tests silently run against the **production** Supabase database (the connection helper prefers `DATABASE_URL` and ignores the `DB_NAME` test override); enrollment leaks pooled DB connections; Werkzeug 3.0.3 carries known CVEs; there is no CSRF protection; login lockout is client-side resettable; deploy configs omit required secrets and don't install `face_recognition` (so cloud recognition is disabled by design); and the docs still describe MySQL throughout. None of these are fatal to fix, but #1 and #3 should be addressed before any real use.

---

## Findings by severity

### CRITICAL

**C1. PostgreSQL rejects the attendance-logging SQL — core feature is broken in production**
- File: `services/attendance_service.py`, `log_attendance()` (the `INSERT … ON DUPLICATE KEY UPDATE time_out = VALUES(time_in), confidence = VALUES(confidence)` block).
- `ON DUPLICATE KEY UPDATE` with `VALUES(col)` is **MySQL syntax**. PostgreSQL requires `ON CONFLICT (user_id, date) DO UPDATE SET time_out = EXCLUDED.time_in, confidence = EXCLUDED.confidence`. The `attendance` table has the matching `UNIQUE (user_id, date)` constraint (`database/schema.sql`), so the PG form is valid.
- Impact: `POST /api/recognize` calls `log_attendance` for every matched face; the INSERT raises `psycopg2.errors.SyntaxError`, the route maps it to `{"error": "Database unavailable"}` → **503**. Faces are still recognized and returned, but **attendance is never written**.
- Proof the backend is PostgreSQL: `models/db.py` imports `psycopg2`/`psycopg2.pool` and builds the pool from `DATABASE_URL` (Supabase); `database/schema.sql` uses `SERIAL`, `BYTEA`, `CHECK`; `requirements.txt` pins `psycopg2-binary`. The sibling `models/attendance.py` `manual_override()` already uses the correct `ON CONFLICT (user_id, date) DO UPDATE SET status = EXCLUDED.status, marked_by = EXCLUDED.marked_by` — confirming the migration was done there but not here.
- Why tests miss it: `tests/test_attendance_service.py` patches `services.attendance_service.execute_query`, so the SQL string is never sent to PostgreSQL. The suite validates debounce/status logic only.

**C2. Seeding also uses MySQL syntax — fresh deploys can't seed demo data**
- File: `database/seed.py` (~lines 267-273): the bulk attendance insert uses `ON DUPLICATE KEY UPDATE time_in = VALUES(time_in), status = VALUES(status), confidence = VALUES(confidence)`. Runs on first boot via `database/init_db.py` `_run_seed()`. On a fresh PostgreSQL DB this throws and the seed transaction rolls back (users may or may not persist depending on transaction boundaries). Dormant only if the DB is already seeded.

### HIGH

**H1. Tests run against the production database, not a test DB**
- `tests/conftest.py` `test_app` sets `os.environ.setdefault("DB_NAME", "smartface_test_db")` and `app.config["DB_NAME"] = "smartface_test_db"`.
- But `models/db.py` `_get_pool()` reads `os.environ.get("DATABASE_URL")` **first** and only falls back to a `DB_NAME`-based DSN when `DATABASE_URL` is absent. `.env` defines `DATABASE_URL` pointing at the production Supabase instance, so the `DB_NAME` override is ignored and every test connects to the production `users`/`attendance`/`face_encodings` tables.
- Impact: stateful tests (enrollment, manual override) mutate production data; "test isolation" is illusory; CI against this repo would pollute or corrupt real records. This also means the suite depends on a live external DB — unit tests fail (or skip via exception handlers) when it is unreachable.

**H2. Enrollment leaks pooled DB connections**
- File: `routes/api.py`, `enroll()`. It calls `get_connection()` (pulls a connection from the `ThreadedConnectionPool(1, 5)` in `models/db.py`), but the `finally` block calls `conn.close()` instead of returning the connection to the pool via `release_connection(conn)` (which calls `putconn`).
- Closed connections are never returned, so the pool (max 5) is exhausted after ~5 enrollments; subsequent DB operations block or fail. The project already has `release_connection()`/`execute_query()` helpers that handle this correctly — `enroll()` bypasses them.
- Secondary: the `finally` also calls `cursor.close()` even though `cursor` may be undefined if an exception occurs before `cursor = conn.cursor(...)`, which can raise `NameError` during cleanup.

**H3. Outdated Werkzeug 3.0.3 with known CVEs**
- `requirements.txt` pins `Werkzeug==3.0.3` and `Flask==3.0.3`.
- Werkzeug < 3.0.6 is vulnerable to **CVE-2024-49767** (multipart/form-data parser resource-exhaustion DoS; fixed in 3.0.6) and **CVE-2024-49766** (`safe_join` path traversal — advisory notes Python ≥ 3.11 or non-Windows are not vulnerable; this project runs 3.11, so 49766 is largely mitigated, but the pin should still move).
- The app runs `debug=False` (`app.py`, `serve.py`), which mitigates the older Werkzeug debug-console RCE class, but the DoS (49766/49767) still applies to any multipart parsing. Recommend upgrading Werkzeug to ≥ 3.0.6 (current 3.1.x) and Flask to a current 3.0.x/3.1.x.

### MEDIUM

**M1. No CSRF protection**
- A grep across all `.py`/`.html` found no `CSRFProtect`, `Flask-WTF`, `hidden_tag`, or SameSite configuration. Every state-changing POST (`/login`, `/api/enroll`, `/users/<id>/deactivate|edit|delete|delete-biometric`, `/attendance/manual`) authenticates solely via the session cookie.
- An attacker-hosted page can submit cross-site POSTs that ride the victim's session (e.g., delete a user, enroll a fake admin, force a manual override). Combined with `app.py` only setting `SESSION_PERMANENT`/`PERMANENT_SESSION_LIFETIME` (no `SESSION_COOKIE_SECURE`, no explicit `SESSION_COOKIE_SAMESITE`), the exposure is real on any non-localhost deployment.

**M2. Login lockout is client-side resettable**
- `routes/auth.py` stores `login_attempts` and `lockout_until` in the Flask **session**. Discarding the session cookie (or never sending one) resets the counter, so the progressive lockout provides no real brute-force protection. Track attempts server-side (per-account and per-IP in the DB or a cache).

**M3. Deploy configs omit required secrets and fall back to an insecure default**
- `render.yaml` sets only `TOLERANCE`, `LATE_TIME`, `BRIGHTNESS_THRESHOLD`, `UPLOAD_DIR` — not `SECRET_KEY` or `DATABASE_URL`. `railway.toml`/`nixpacks.toml` likewise inject no secrets.
- `config.py` falls back to `SECRET_KEY = "change-me-in-production"` when unset. If `SECRET_KEY` isn't configured in the host dashboard, the app signs sessions with a publicly known key. Recommend failing fast at startup when `SECRET_KEY` is the default, and making `DATABASE_URL` mandatory in deploy templates.

**M4. Cloud build installs dlib but not face_recognition — recognition is disabled by design**
- `requirements.txt` omits `dlib` and `face_recognition` entirely. `render.yaml` buildCommand installs `dlib-bin` but not `face_recognition`; `nixpacks.toml` builds `dlib` from source (wasting build time) but also omits `face_recognition`.
- At runtime `services/face_service.py` sets `FACE_RECOGNITION_AVAILABLE = False` on `ImportError`, so every recognized face returns "Unknown" and no attendance is recorded. Git history confirms this was deliberate ("remove dlib/face_recognition from Render build (use locally for demo)") due to Render free-tier OOM. Net effect: the deployed app's headline feature is offline. Either restore `face_recognition` on a sized-up plan or document explicitly that cloud deploys run degraded and recognition must run on a local/on-prem kiosk.

### LOW / housekeeping

**L1. Documentation and config still say "MySQL" everywhere, but the system is PostgreSQL**
- `README.md` ("MySQL Server 8.0", `mysql -u root -p < database/schema.sql`), `.env.example` ("# Database (MySQL)"), `SMARTFACE_PROJECT_SPEC.md` (`AUTO_INCREMENT`, `BLOB`, `UNIQUE KEY uniq_user_day`), and the `.kiro/specs/*` design docs all describe MySQL, while `models/db.py`, `requirements.txt`, and `database/schema.sql` are PostgreSQL. Docstrings across `models/user.py`, `models/attendance.py`, `models/audit.py` still `Raises: mysql.connector.Error`, and `services/attendance_service.py`/`models/user.py` alias `MySQLError = Exception` ("psycopg2 migration"). This drift is the root cause of C1/C2 and will keep generating MySQL-only SQL if not fixed.

**L2. Debounce window mismatch (code vs. comments vs. docs)**
- `services/attendance_service.py` sets `_DEBOUNCE_SECONDS = 30`, but its module/helper docstrings repeatedly say "60 seconds", and `README.md` says "at most one DB write per user per 60 seconds". Tests use `max_value=29`, so 30s is the intended current value; the prose is stale.

**L3. Stale "0.25x" downscale comment**
- `services/face_service.py` `recognize_frame` comment says "Downscale 0.25x" but the code runs `cv2.resize(frame, (0,0), fx=0.5, fy=0.5)` (0.5x), and the bbox rescale comment correctly says "multiply by 2". The 0.25x/×4 figure is stale.

**L4. Runtime uses the Hog model, not the CNN advertised in commits**
- Commits ("Full local upgrade: CNN+jitters3", "CNN enrollment + num_jitters=5") imply CNN, but `recognize_frame` and `encode_samples` call `face_recognition.face_locations(...)`/`face_encodings(...)` with no `model="cnn"` or `num_jitters` argument → default **Hog** model, 1 jitter. Faster but less accurate than advertised; re-validate accuracy expectations.

**L5. Hard-delete audit event isn't filterable**
- `routes/admin.py` `delete_user_route` writes `action="user_deleted"` (raw string), but the `/audit` dropdown lists only the six `ACTION_*` constants and there is no `ACTION_USER_DELETED` constant. Hard deletes won't appear when filtering by action.

**L6. Scaffolding/dead scripts committed at repo root**
- `_write_files.py` is a one-off code generator with a hardcoded `BASE = r"c:\Users\Asus\Desktop\SmartFace"` absolute path; `_verify_app.py` is labelled "Temporary verification script — safe to delete after task 1.5 is confirmed." Both add noise and a machine-specific path. Neither is needed at runtime.

**L7. Broad exception handling masks root causes**
- `MySQLError = Exception` (L1) means the SQL syntax bug (C1) is caught and reported as a generic "db_error"/503 rather than surfacing the real `SyntaxError`. `write_audit` intentionally swallows all exceptions (acceptable for audit fire-and-forget), but the service-layer broad catches make debugging harder.

**L8. Biometric raw images stored unencrypted on disk**
- Enrollment writes raw JPEGs to `uploads/face_samples/<user_id>/` (gitignored, not web-served since it sits outside `static/`). Good: `face_encodings` stores 128-d vectors (not raw images) and biometric-delete removes JPEGs + DB rows. But raw biometric JPEGs have no encryption at rest, and on cloud deploys the uploads dir is ephemeral (lost on redeploy). Acceptable for a capstone; for production/RA 10173 (Philippine Data Privacy Act) harden with encryption and persistent storage and document retention/consent-withdrawal.

---

## Predicted future issues

- **Silent no-op attendance (C1):** if deployed as-is, the system will recognize faces but never persist attendance — likely already happening in production and masked by the generic 503.
- **Pool exhaustion (H2):** intermittent 500s as enrollment volume grows past ~5 calls per worker lifecycle.
- **Test-induced data corruption (H1):** any automated/CI test run mutates the production Supabase DB.
- **Drift recurrence (L1):** contributors reading MySQL docs will keep introducing MySQL-only SQL.
- **Unbounded `/api/recognize` load:** the client polls at 1 s, but the server enforces no rate limit on this CPU-heavy (Hog detection per request) endpoint. A malicious or buggy client can degrade the kiosk host; the >2s warning (`routes/api.py`) only logs, it doesn't throttle.
- **Credential hygiene:** `.env` is correctly gitignored and was never committed (verified via `git log`/`git ls-files`), but it currently contains a live Supabase URL + password and a real `SECRET_KEY` on disk — rotate if this machine/repo is shared, and never copy `.env` into images or deploy artifacts.

---

## Dependencies

`requirements.txt`: Flask 3.0.3, Werkzeug 3.0.3 (see H3), psycopg2-binary 2.9.9, opencv-python-headless 4.10.0.84, numpy 1.26.4, Pillow 10.4.0, python-dotenv 1.0.1, hypothesis 6.112.1, pytest 8.3.2, waitress 3.0.1. `requirements-local.txt` adds `dlib-bin==20.0.1` and non-headless opencv. Notable: `dlib`/`face_recognition` are **not** in either requirements file (installed manually per README; see M4). Pins are exact (good). Werkzeug/Flask are behind and should be bumped. Pillow 10.4 and numpy 1.26.4 are reasonable; no deprecated packages detected. Python is constrained to 3.11 (`runtime.txt`, README) because `face_recognition`/dlib need it.

---

## Configuration & build/CI

- Build/run: `py -3.11 app.py` (dev) or `python serve.py` (waitress prod). Deploy templates: `render.yaml`, `railway.toml`+`nixpacks.toml`, `Procfile`. Tests: `py -3.11 -m pytest tests/ --tb=short -q`.
- `database/init_db.py` auto-creates the schema (`CREATE TABLE IF NOT EXISTS` from `database/schema.sql`) and seeds on first boot — runs against PostgreSQL but reads `database/schema.sql` (correctly the PG schema; `schema_pg.sql` is an identical duplicate).
- No CI workflow file is present (no `.github/`, no `Makefile` target). Tests run only manually. Adding CI is recommended given H1/H3.
- `use_reloader=False` is correctly enforced (`app.py`) to preserve the in-memory encoding cache across reloads.

---

## Recommendations (prioritized)

1. **Fix C1/C2:** rewrite `attendance_service.log_attendance` and `database/seed.py` to PostgreSQL `ON CONFLICT (user_id, date) DO UPDATE SET time_out = EXCLUDED.time_in, confidence = EXCLUDED.confidence` (seed: `… = EXCLUDED.…`). Add an integration test that runs the real SQL against a throwaway PostgreSQL (testcontainers or a dedicated test Supabase project) so dialect regressions are caught — the mocked unit tests cannot.
2. **Fix H2:** in `enroll()`, return the connection with `release_connection(conn)` (or use the existing `execute_query`/`_managed_connection` helpers) instead of `conn.close()`; guard the `cursor` reference in `finally`.
3. **Fix H1:** make the test fixture isolated — unset `DATABASE_URL` for tests and build the DSN from a `TEST_DATABASE_URL`/`DB_NAME` pointing at a real test DB, or point `DATABASE_URL` at a dedicated test database. Never test against the production `DATABASE_URL`.
4. **Fix H3:** bump Werkzeug to ≥ 3.0.6 and Flask to a current 3.0.x; repin and rerun the suite.
5. **Fix M1:** add Flask-WTF `CSRFProtect` + form tokens; set `SESSION_COOKIE_SECURE=True` and `SESSION_COOKIE_SAMESITE='Lax'` in production config.
6. **Fix M2:** move login lockout to server-side (per-account + per-IP in DB/cache).
7. **Fix M3:** require `SECRET_KEY` and `DATABASE_URL` in deploy configs; fail fast at startup if `SECRET_KEY` is the default.
8. **Resolve M4:** either restore `face_recognition` in the cloud build on a sized-up plan, or explicitly document that cloud deploys run in a degraded "Unknown" mode and recognition must run on a local/on-prem kiosk.
9. **Fix L1–L5:** reconcile docs to PostgreSQL (README, `.env.example`, spec, docstrings); correct debounce 60s→30s, downscale 0.25x→0.5x, and model=CNN→Hog claims; add `ACTION_USER_DELETED` + dropdown entry.
10. **Fix L6:** remove `_write_files.py` and `_verify_app.py`.
11. Add server-side rate limiting / a request-size cap on `/api/recognize` (also mitigates H3 DoS).
12. **L8:** for production/RA 10173, encrypt biometric data at rest, use persistent storage on cloud, and document retention/consent-withdrawal.

---

## Notes on verification

- Findings C1, C2, H1, H2, L1–L8 are grounded in code actually read (`models/db.py`, `models/attendance.py`, `models/user.py`, `models/audit.py`, `services/face_service.py`, `services/attendance_service.py`, `routes/api.py`, `routes/auth.py`, `routes/admin.py`, `routes/attendance.py`, `database/init_db.py`, `database/schema.sql`, `database/seed.py`, `tests/conftest.py`, `tests/test_attendance_service.py`, `tests/test_face_service.py`, `static/js/dashboard.js`, `static/js/camera.js`, deploy configs).
- `.env` and `uploads/` are gitignored and confirmed never committed (`git ls-files` / `git log -- .env` empty). The credentials are local-only on disk.
- The C1 claim (PostgreSQL rejecting `ON DUPLICATE KEY UPDATE`) is a known dialect fact and is corroborated by the codebase's own correct `ON CONFLICT` usage in `manual_override`; it was not validated by running the statement against a live DB in this read-only audit. Running `pytest` would not catch it because the DB layer is mocked.
