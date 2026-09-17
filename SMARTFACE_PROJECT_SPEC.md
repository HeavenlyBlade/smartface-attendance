# SmartFace — Project Specification for Kiro

**Project:** SmartFace: A Real-Time Face Recognition Web App for Automated Attendance Monitoring
**Institution:** St. Anne College Lucena, Inc. (SACLI)
**Type:** Undergraduate capstone / thesis system
**Timeline:** 5 days to a working, demonstrable build
**Role of this document:** Single source of truth. Read this fully before writing code. Chapters 1–3 of the thesis are already written and approved — the implementation must not contradict them.

---

## 1. How to work with me on this

- **Ship working vertical slices, not layers.** A rough end-to-end enrollment → recognition → attendance row beats a beautiful half-finished admin panel.
- **Do not add dependencies I did not ask for.** Every extra package is an extra install failure on demo day.
- **No Docker, no Redis, no Celery, no websockets, no React.** Server-rendered Jinja2 templates + vanilla JS. This is a 5-day capstone running on one laptop.
- **When something is ambiguous, pick the simpler option and leave a `# NOTE:` comment.** Don't stop and ask unless it's a data-loss or security decision.
- **Every file you generate must run.** No `pass  # TODO implement`. If a feature can't be finished, stub it with a working placeholder that returns real data.
- **Comment the face recognition pipeline heavily.** I have to defend this code in front of a panel and explain what every step does.

---

## 2. Hard constraints

| Constraint | Value |
|---|---|
| Python version | 3.11 (do NOT target 3.12/3.13 — dlib wheels are unreliable there) |
| OS | Windows (development + demo) |
| Backend | Python + **Flask** |
| Frontend | HTML5, CSS3, vanilla JavaScript, Jinja2 templates |
| Face engine | `face_recognition` (dlib-based), `OpenCV` for frame handling |
| Database | **MySQL** (via `mysql-connector-python`) |
| IDE | VS Code / Kiro |
| Max users (documented) | 1,000 registered users |
| Deployment | Localhost demo; architecture must be LAN-deployable |

**Locked dependency list.** Anything beyond this needs a reason:

```
Flask
mysql-connector-python
face_recognition
opencv-python
numpy
Pillow
Werkzeug          # password hashing (ships with Flask)
python-dotenv
```

---

## 3. Critical architecture decision — read this before coding

The thesis says OpenCV handles the real-time video stream. **It does — server-side, on individual frames.** Do NOT use `cv2.VideoCapture(0)` in Flask. On a web app that opens the *server's* camera, which defeats the entire premise.

**Correct pipeline:**

1. Browser page opens the client webcam with `navigator.mediaDevices.getUserMedia()`.
2. Every ~1000ms, JS draws the current video frame to a hidden `<canvas>` and calls `canvas.toDataURL('image/jpeg', 0.7)`.
3. JS POSTs that base64 string to `POST /api/recognize`.
4. Flask decodes base64 → numpy array → `cv2.imdecode()`.
5. **Downscale the frame to 0.25x before encoding** (`cv2.resize`). This is a ~4x speedup and is non-negotiable for usable framerate.
6. Convert BGR → RGB, run `face_recognition.face_locations()` then `face_recognition.face_encodings()`.
7. Compare against the in-memory known-encodings cache.
8. Return JSON: matched name, user_id, confidence, bounding box, and whether attendance was logged.
9. JS draws the bounding box + name overlay on a canvas layered over the video.

**`getUserMedia` requires `localhost` or HTTPS.** Demo on `http://localhost:5000`. Include a commented-out `ssl_context='adhoc'` line in `app.py` for LAN testing.

---

## 4. Matching logic

```python
# Known encodings are loaded ONCE at app startup into module-level lists.
# known_encodings: list[np.ndarray]  (128-dim float64 each)
# known_user_ids:  list[int]         (parallel index)

distances = face_recognition.face_distance(known_encodings, unknown_encoding)
best_index = np.argmin(distances)
best_distance = distances[best_index]

TOLERANCE = 0.45          # stricter than the 0.6 default; fewer false positives
if best_distance <= TOLERANCE:
    user_id = known_user_ids[best_index]
    confidence = round((1 - best_distance) * 100, 2)
else:
    user_id = None        # render as "Unknown"
```

- Expose `TOLERANCE` in `config.py` so I can tune it live during testing.
- A user has multiple encodings (3–5 capture shots). Keep them all in the flat list, mapped to the same `user_id`. More samples = better accuracy across lighting.
- Provide `reload_known_faces()` and call it after every successful enrollment so new users are recognizable immediately without a restart.

**Debouncing (important).** At 1 frame/sec the same person generates 30+ hits per session. Rules:
- First recognition of the day → INSERT with `time_in`.
- Any recognition after that → UPDATE `time_out` only, and only if 60+ seconds have passed since the last update.
- Keep an in-memory `{user_id: last_seen_timestamp}` dict as the first guard so you don't hit MySQL on every frame.

---

## 5. Database schema

Database name: `smartface_db`. Engine InnoDB, charset `utf8mb4`.

```sql
CREATE TABLE users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    full_name       VARCHAR(150) NOT NULL,
    email           VARCHAR(150) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            ENUM('admin','faculty','student') NOT NULL DEFAULT 'student',
    id_number       VARCHAR(50) UNIQUE,
    department      VARCHAR(100),
    consent_given   TINYINT(1) NOT NULL DEFAULT 0,   -- RA 10173 compliance
    is_active       TINYINT(1) NOT NULL DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE face_encodings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    encoding    BLOB NOT NULL,          -- np.ndarray(128, float64).tobytes()
    sample_no   TINYINT NOT NULL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE attendance (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    date        DATE NOT NULL,
    time_in     TIME,
    time_out    TIME,
    status      ENUM('present','late','absent','manual') NOT NULL DEFAULT 'present',
    confidence  FLOAT,
    marked_by   INT NULL,               -- NULL = automatic; set = admin override
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_day (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE audit_logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NULL,
    action      VARCHAR(255) NOT NULL,
    details     TEXT,
    ip_address  VARCHAR(45),
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Encoding round-trip:**
```python
blob = encoding.tobytes()                              # store
encoding = np.frombuffer(blob, dtype=np.float64)       # load  → shape (128,)
```

`UNIQUE KEY uniq_user_day` is the database-level guarantee against duplicate daily rows. Use `INSERT ... ON DUPLICATE KEY UPDATE`.

**Late threshold:** configurable in `config.py`, default `08:00:00`. `time_in` after that → `status = 'late'`.

---

## 6. Project structure

```
smartface/
├── app.py                      # Flask entry point, blueprint registration
├── config.py                   # TOLERANCE, LATE_TIME, DB creds from .env
├── .env.example
├── requirements.txt
├── database/
│   ├── schema.sql              # full CREATE TABLE script
│   └── seed.py                 # 30 dummy users + 3 weeks attendance
├── models/
│   ├── db.py                   # connection pool + query helpers
│   ├── user.py
│   ├── attendance.py
│   └── audit.py
├── services/
│   ├── face_service.py         # encode, match, cache, reload_known_faces()
│   └── attendance_service.py   # debounce + insert/update rules
├── routes/
│   ├── auth.py                 # login, logout
│   ├── admin.py                # users, enrollment, reports, audit logs
│   ├── attendance.py           # kiosk page, dashboard
│   └── api.py                  # /api/recognize, /api/enroll, /api/live-feed
├── static/
│   ├── css/style.css
│   ├── js/camera.js            # getUserMedia + frame capture loop
│   ├── js/enroll.js
│   └── js/dashboard.js
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── kiosk.html              # the recognition screen
│   ├── dashboard.html
│   ├── enroll.html
│   ├── users.html
│   ├── reports.html
│   └── audit.html
└── uploads/face_samples/       # raw enrollment images (for the thesis appendix)
```

---

## 7. Routes

| Method | Route | Role | Purpose |
|---|---|---|---|
| GET/POST | `/login` | public | Session login |
| GET | `/logout` | any | End session |
| GET | `/` | any | Redirect by role |
| GET | `/kiosk` | admin, faculty | Live recognition screen |
| POST | `/api/recognize` | admin, faculty | Frame in → match + attendance out |
| GET | `/enroll` | admin | Enrollment form + capture UI |
| POST | `/api/enroll` | admin | Save user + 3–5 encodings |
| GET | `/dashboard` | admin, faculty | Today's attendance, live counts |
| GET | `/api/live-feed` | admin, faculty | JSON of today's records (polled every 3s) |
| GET | `/users` | admin | List/edit/deactivate users |
| GET | `/reports` | admin, faculty | Filter by date range, role, department |
| GET | `/reports/export?format=csv` | admin, faculty | CSV download |
| POST | `/attendance/manual` | admin | Override — mark present manually |
| GET | `/audit` | admin | Audit log viewer |
| GET | `/my-attendance` | student | Own records only |

**RBAC:** implement a `@role_required('admin')` decorator in `routes/auth.py`. Apply it to every route above. Students must never reach another user's data — this is explicitly promised in Chapter I.

---

## 8. Build order (5 days)

**Day 1 — Foundation**
- Verify `dlib` installs. If `pip install dlib` fails after ~15 min of trying (`pip install cmake` first), STOP and tell me — we swap the engine, we do not debug build tools all day.
- `schema.sql`, `models/db.py`, connection test
- Flask skeleton, `base.html`, login, session, `@role_required`, password hashing with `werkzeug.security`
- Seeded admin account

**Day 2 — Enrollment**
- `/enroll` page: form + webcam capture of 3–5 shots with on-screen guidance
- `POST /api/enroll`: create user, encode each sample, store BLOBs, save raw JPEGs to `uploads/face_samples/`
- Consent checkbox (RA 10173), required before submit
- `services/face_service.py` with startup cache + `reload_known_faces()`
- `/users` list view

**Day 3 — The core loop**
- `/kiosk` page: video element, overlay canvas, capture loop in `camera.js`
- `POST /api/recognize` with the full pipeline from §3
- `attendance_service.py` debounce + insert/update
- Bounding box, name, and confidence rendered live
- Success/failure sound cue and a toast — panels love visible feedback

**Day 4 — Dashboard, reports, audit**
- `/dashboard`: present today / late / total registered cards + live table polling `/api/live-feed`
- `/reports`: date range, role, department filters; CSV export
- `/attendance/manual` admin override (the fallback mechanism promised in Chapter II)
- `audit_logs` writes on login, enrollment, manual override, user deactivation
- `/audit` viewer
- `/my-attendance` for students

**Day 5 — Polish and defense**
- `database/seed.py`: 30 users, 3 weeks of realistic attendance so nothing looks empty
- Error handling: no face detected, multiple faces, camera denied, DB down
- UI pass: SACLI colors, readable on a projector, large kiosk text
- README with setup steps for the panel

**Cut list if behind schedule** (drop in this order): audit log viewer UI (keep the writes), student self-service page, department filters, PDF export. **Never cut:** enrollment, recognition, attendance logging, dashboard, CSV export.

---

## 9. Known risks to handle explicitly

1. **Photo spoofing.** Someone holds up a phone picture and gets marked present. Implement the cheap mitigation: require a detected blink or head movement before the first accept of a session, OR document it as a stated limitation. Do not attempt a real anti-spoofing model this week. Leave a clearly commented hook where liveness would plug in.
2. **Multiple faces in frame.** Process all detected faces; log attendance for each matched one; label unmatched as "Unknown."
3. **No face detected.** Return a clean `{"faces": []}` — never a 500.
4. **Poor lighting.** Add a client-side brightness warning when the frame's mean pixel value is too low.
5. **Camera permission denied.** Show an instruction panel, not a blank screen.
6. **Data privacy (RA 10173).** Password hashing, consent flag, and the ability to delete a user's biometric data on request. Chapter II cites this act — it will be asked about.

---

## 10. Evaluation requirement (don't remove)

The system is evaluated against **ISO/IEC 25010** on: functional suitability, performance efficiency, compatibility, usability, reliability, and portability. Responses use a 4-point Likert scale (4 = Strongly Agree / Very Good, down to 1 = Strongly Disagree / Poor), scored by weighted mean.

Practically this means: the app must run on Chrome, Edge, and Firefox; pages must load in under 3 seconds; recognition should respond in under 2 seconds per frame; and nothing may crash during a live demo. Build for those numbers.

---

## 11. Terminology to use in code and comments

Match the thesis so my documentation and my codebase agree:

- The three actors are **Administrator**, **Faculty/Staff**, and **Student**.
- The system is always **SmartFace**, the institution is **SACLI**.
- Say "facial encoding" and "face matching," not "embeddings" and "vector search."
- The methodology is **Agile with an Iterative Framework** (Planning → Analysis and Design → Implementation → Testing → Evaluation).
