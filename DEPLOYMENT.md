# SmartFace — Deployment Guide

> Two deployment modes: **Local/LAN** (full features, for live demo) and **Render** (cloud, web pages only).

---

## Architecture

```
Browser (getUserMedia)
  → POST /api/recognize  (base64 JPEG, every 500ms)
  → face_service.py      (CNN detect → dlib 128-dim → EAR liveness → Euclidean match)
  → attendance_service.py (30s debounce → INSERT ON CONFLICT)
  → Supabase PostgreSQL
```

**Stack:** Python 3.11 · Flask · Waitress · psycopg2 · face_recognition (dlib-bin) · OpenCV  
**Database:** Supabase (PostgreSQL) — shared between local and Render

---

## Local / LAN Deployment

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11.x | Do NOT use 3.12+ — dlib wheels only exist for ≤3.11 |
| MySQL | 8.0 | Not needed (migrated to Supabase) |
| pip | any | Comes with Python |

### Install dependencies

```bash
# Core dependencies (for Render / cloud — no face recognition)
py -3.11 -m pip install -r requirements.txt

# Face recognition (local only — requires dlib-bin pre-compiled wheel)
py -3.11 -m pip install dlib-bin==20.0.1
py -3.11 -m pip install face_recognition==1.3.0 --no-deps
py -3.11 -m pip install face-recognition-models
py -3.11 -m pip install psycopg2-binary==2.9.9
```

### Download shape predictor (liveness detection)

```bash
# ~95MB — only needs to be downloaded once
py -3.11 -c "
import urllib.request, bz2, os, pathlib
pathlib.Path('models').mkdir(exist_ok=True)
dat = 'models/shape_predictor_68_face_landmarks.dat'
url = 'http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2'
urllib.request.urlretrieve(url, dat+'.bz2')
with bz2.open(dat+'.bz2') as i, open(dat,'wb') as o: o.write(i.read())
os.remove(dat+'.bz2')
print('Done:', os.path.getsize(dat), 'bytes')
"
```

### Configure `.env`

Copy `.env.example` to `.env` and fill in:

```env
DATABASE_URL=postgresql://postgres.<project_id>:<password>@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres
SECRET_KEY=<generate with: py -3.11 -c "import secrets; print(secrets.token_hex(32))">
TOLERANCE=0.45
LATE_TIME=08:00:00
BRIGHTNESS_THRESHOLD=50
UPLOAD_DIR=uploads/face_samples
```

> ⚠️ **Never edit `.env` with Notepad** — it adds a UTF-8 BOM that breaks python-dotenv.  
> Use VS Code or Notepad++ (set encoding to UTF-8 without BOM).

### Run locally

```bash
# Standard (localhost only)
py -3.11 serve.py

# LAN access (all devices on same WiFi)
# getUserMedia requires HTTPS for non-localhost — use --ssl flag
py -3.11 serve.py --ssl
# Then access: https://192.168.x.x:5000  (accept the self-signed cert warning)
```

### Default credentials

| Email | Password | Role |
|---|---|---|
| `admin@sacli.edu.ph` | `Admin123` | Admin |
| `jose.reyes@sacli.edu.ph` | `Admin123` | Faculty |
| `angelica.torres@sacli.edu.ph` | `Admin123` | Student |

> All 30 seeded users share the password `Admin123`.

---

## Supabase Setup (Database)

1. Go to **supabase.com** → create a free project
2. **Settings → Database → Connection pooling → Session pooler URI** → copy it
3. Paste into `DATABASE_URL` in `.env`
4. Run schema in Supabase **SQL Editor**:

```sql
-- Paste contents of database/schema_pg.sql
```

5. Seed users:

```bash
py -3.11 database/seed.py
```

> The app also auto-initializes on first boot via `database/init_db.py` if tables don't exist.

---

## Render (Cloud) Deployment

> ⚠️ Face recognition is **disabled** on Render free tier (512MB RAM).  
> The kiosk page loads but shows "Waiting for face..." — this is expected.  
> All other pages (Dashboard, Reports, Audit, Users) work fully.

### Steps

1. Push to GitHub: `git push origin main`
2. Go to **render.com** → New Project → Deploy from GitHub
3. Select `smartface-attendance` repository
4. Settings:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python serve.py`
   - **Instance Type:** Free
5. **Environment** tab → add all variables from your `.env` (except `DB_*` — use `DATABASE_URL` instead)
6. Deploy

### Environment variables for Render

| Key | Value |
|---|---|
| `DATABASE_URL` | Supabase session pooler URI |
| `SECRET_KEY` | Same as local `.env` |
| `PYTHON_VERSION` | `3.11.9` |
| `TOLERANCE` | `0.45` |
| `LATE_TIME` | `08:00:00` |
| `BRIGHTNESS_THRESHOLD` | `50` |
| `UPLOAD_DIR` | `uploads/face_samples` |

### Render limitations

| Feature | Local | Render |
|---|---|---|
| Login / Dashboard / Reports | ✅ | ✅ |
| User Management / Audit | ✅ | ✅ |
| Face enrollment | ✅ | ❌ (no dlib) |
| Kiosk recognition | ✅ | ❌ (no RAM) |
| PDF/CSV export | ✅ | ✅ |
| Cold start after idle | instant | ~30s |
| Uploaded face JPEGs | persistent | ephemeral (wiped on redeploy) |

---

## File Structure

```
SmartFace/
├── app.py                    Flask application factory
├── serve.py                  Waitress production server launcher
├── config.py                 Environment variable loader
├── requirements.txt          Cloud dependencies (no dlib)
├── requirements-local.txt    Local dependencies (includes dlib instructions)
├── runtime.txt               Python version pin for Render
├── render.yaml               Render deployment config
├── .env                      Local secrets (NOT committed to git)
├── .env.example              Template for .env
│
├── models/
│   ├── db.py                 PostgreSQL connection pool (psycopg2)
│   ├── user.py               User data access
│   ├── attendance.py         Attendance data access
│   └── audit.py              Audit log data access
│
├── routes/
│   ├── auth.py               Login, logout, role_required decorator
│   ├── admin.py              Enrollment, user management, audit log
│   ├── attendance.py         Kiosk, dashboard, reports, PDF/CSV export
│   └── api.py                JSON endpoints (recognize, enroll, live-feed)
│
├── services/
│   ├── face_service.py       Encoding cache, CNN recognition, EAR liveness
│   └── attendance_service.py Debounce logic, status assignment
│
├── database/
│   ├── schema.sql            PostgreSQL table definitions
│   ├── schema_pg.sql         PostgreSQL schema (same, explicit PG syntax)
│   ├── seed.py               30 demo users + 3 weeks attendance data
│   └── init_db.py            Auto-init on first boot
│
├── static/
│   ├── css/style.css         SACLI design system
│   ├── js/camera.js          Kiosk capture loop + face mesh overlay
│   ├── js/enroll.js          Enrollment webcam + MediaPipe face detection
│   ├── js/dashboard.js       Live feed polling
│   ├── audio/                success.wav + fail.wav audio cues
│   └── img/                  sacli_logo.png + favicon.ico
│
└── templates/
    ├── base.html             Navbar, flash messages, toast system
    ├── login.html            Login page
    ├── dashboard.html        Cards + charts + live table
    ├── kiosk.html            Full-screen recognition UI
    ├── enroll.html           Enrollment form + webcam
    ├── users.html            User management table
    ├── reports.html          Filtered attendance report + export
    ├── audit.html            Audit log viewer
    └── my_attendance.html    Student self-service
```

---

## Key Configuration Values

| Variable | Default | Description |
|---|---|---|
| `TOLERANCE` | `0.45` | Face match Euclidean distance threshold (lower = stricter) |
| `LATE_TIME` | `08:00:00` | Time-in cutoff for "present" vs "late" |
| `BRIGHTNESS_THRESHOLD` | `50` | Mean pixel value (0–255) for low-light warning |
| `UPLOAD_DIR` | `uploads/face_samples` | Where enrollment JPEGs are saved |

---

## Troubleshooting

| Problem | Likely Cause | Fix |
|---|---|---|
| `DATABASE_URL: NOT SET` | `.env` has BOM | Resave `.env` as UTF-8 without BOM in VS Code |
| `Invalid credentials` | Password mismatch or wrong DB | Run `py -3.11 database/seed.py` to re-seed |
| Kiosk not recognizing | Empty cache or wrong encodings | Re-enroll via `/users` → Re-enroll → `/enroll` |
| Liveness not working | Shape predictor missing | Download `shape_predictor_68_face_landmarks.dat` (see above) |
| `face_recognition` not found | `--no-deps` install missing models | `py -3.11 -m pip install face-recognition-models` |
| Render 502 on first request | Cold start + model load | Wait 60s after deploy, then access |
| Camera blocked on LAN | HTTP not HTTPS | Use `py -3.11 serve.py --ssl` |