# SmartFace — Real-Time Face Recognition Attendance System
**St. Anne College Lucena, Inc. (SACLI)**

SmartFace is a Flask web application that identifies registered users via a live webcam feed and automatically records attendance. Administrators enroll users, Faculty/Staff operate the kiosk, and Students view their own history.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.11** | 3.12+ is not supported — `face_recognition` requires 3.11 |
| **MySQL Server 8.0** | Must be running before starting the app |
| **pip** | Comes with Python 3.11 |

---

## dlib / face_recognition Installation

`face_recognition` depends on `dlib`, which requires a compiled C++ extension. Use one of these methods in order of preference:

**Option 1 (recommended) — Pre-compiled wheel via `dlib-bin`:**
```bash
py -3.11 -m pip install dlib-bin==20.0.1
py -3.11 -m pip install face_recognition
```

**Option 2 — Build from source (requires Visual C++ Build Tools):**
```bash
py -3.11 -m pip install cmake
py -3.11 -m pip install dlib
py -3.11 -m pip install face_recognition
```
Install Visual C++ Build Tools from: https://visualstudio.microsoft.com/visual-cpp-build-tools/

**Option 3 — Conda:**
```bash
conda install -c conda-forge dlib
pip install face_recognition
```

**Option 4 (contingency) — Replace with DeepFace:**
If none of the above work, swap `face_recognition` with `deepface` in `services/face_service.py` only. No route or model changes are needed.

---

## Setup

### 1. Clone / copy the project
```
SmartFace/
├── app.py
├── config.py
├── requirements.txt
├── .env.example
├── database/
│   ├── schema.sql
│   └── seed.py
├── models/
├── routes/
├── services/
├── templates/
├── static/
└── tests/
```

### 2. Install dependencies
```bash
py -3.11 -m pip install -r requirements.txt
```

### 3. Configure environment
```bash
copy .env.example .env
```
Edit `.env` and set at minimum:
```
SECRET_KEY=your-random-secret-here
DB_PASS=your-mysql-root-password
DB_NAME=smartface_db
```
Generate a secret key:
```bash
py -3.11 -c "import secrets; print(secrets.token_hex(32))"
```

### 4. Initialise the database
```bash
# Create the database and tables
mysql -u root -p < database/schema.sql
```

### 5. Seed demo data
```bash
py -3.11 database/seed.py
```
This creates 1 admin, 5 faculty, and 24 students with 3 weeks of realistic attendance data.

**Default admin credentials:**
- Email: `admin@sacli.edu.ph`
- Password: `SmartFace2024!`

---

## Running the Application

```bash
py -3.11 app.py
```
Open your browser at: **http://localhost:5000**

> **Note:** `use_reloader=False` is set intentionally — Flask's auto-reloader spawns a child process that loses the in-memory face-encoding cache, causing all faces to return "Unknown".

### LAN / HTTPS access (for kiosk on another device)
`getUserMedia` requires `localhost` or HTTPS. To enable LAN access:
```bash
py -3.11 -m pip install pyopenssl
```
Then uncomment this line in `app.py`:
```python
# app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')
```

---

## Running Tests

```bash
py -3.11 -m pytest tests/ --tb=short -q
```
All 12 correctness properties (Hypothesis) + unit tests should pass.

---

## Role Overview

| Role | Landing page | Can access |
|---|---|---|
| Admin | `/dashboard` | Everything |
| Faculty | `/dashboard` | Kiosk, Dashboard, Reports |
| Student | `/my-attendance` | Own attendance only |

---

## Architecture Notes

- **Recognition pipeline:** Browser captures JPEG frames via `getUserMedia` every 1 s, POSTs base64 to `/api/recognize`. Server decodes → downscales 0.25× → detects faces → compares against in-memory encoding cache → logs attendance.
- **Debounce:** At most one DB write per user per 60 seconds to prevent duplicate `time_out` spam.
- **Liveness hook:** A comment in `services/face_service.py` marks the exact line where a liveness check (blink / head-movement detection) would be inserted — currently deferred as a future enhancement.
- **RA 10173 compliance:** `consent_given=1` must be set before any face encoding is stored. Validated server-side regardless of front-end state.
- **TOLERANCE:** Default `0.45` (stricter than `face_recognition`'s `0.6` default). Adjustable in `.env`.
- **LATE_TIME:** Default `08:00:00`. Time-in after this is recorded as `late`. Adjustable in `.env`.

---

## Key Configuration Values (`.env`)

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key |
| `DB_HOST` | `localhost` | MySQL host |
| `DB_PORT` | `3306` | MySQL port |
| `DB_USER` | `root` | MySQL user |
| `DB_PASS` | *(required)* | MySQL password |
| `DB_NAME` | `smartface_db` | Database name |
| `TOLERANCE` | `0.45` | Face match distance threshold |
| `LATE_TIME` | `08:00:00` | Cutoff time for "present" vs "late" |
| `BRIGHTNESS_THRESHOLD` | `50` | Low-light warning threshold (0–255) |
| `UPLOAD_DIR` | `uploads/face_samples` | Enrollment JPEG storage path |

---

*Built as a capstone project — Python 3.11, Flask, dlib/face_recognition, MySQL*

