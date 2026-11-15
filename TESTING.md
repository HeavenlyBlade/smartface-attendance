# SmartFace — Testing Guide

> Run through every section before the thesis defense.  
> Mark **[ ]** → **[x]** when passed, **[F]** if failed (add notes below).

---

## 0. Pre-Flight Checks

```bash
# 0.1 Verify .env has no BOM and DATABASE_URL is set
py -3.11 -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.environ.get('DATABASE_URL','NOT SET')[:60])"
# Expected: postgresql://postgres.httvteodlkgzuzmqhcdl:...

# 0.2 Database reachable + users exist
py -3.11 -c "from dotenv import load_dotenv; load_dotenv(); from models.db import execute_query; r=execute_query('SELECT COUNT(*) AS c FROM users',fetchone=True); print('Users:',r['c'])"
# Expected: Users: <number>

# 0.3 face_recognition available
py -3.11 -c "import face_recognition; print('OK')"

# 0.4 Shape predictor present (liveness)
py -3.11 -c "import os; print(round(os.path.getsize('models/shape_predictor_68_face_landmarks.dat')/1e6),'MB')"
# Expected: ~95 MB

# 0.5 reportlab available (PDF export)
py -3.11 -c "import reportlab; print('reportlab', reportlab.Version)"
# Expected: reportlab 4.2.2
```

|  #  | Check                             | Pass? | Notes |
| --- |  ---                              |  ---  |    ---|
| 0.1 | `.env` no BOM, `DATABASE_URL` set | [x]   |       |
| 0.2 | DB reachable, users exist         | [x]   | it have a 30 users, maybe because it was seeded but it is ideal to have it empty.|
| 0.3 | `face_recognition` importable     | [x]   |       |
| 0.4 | Shape predictor ~95 MB            | [x]   |it printed 100MB  |
| 0.5 | `reportlab` 4.2.2                 | [x]   |       |

---

## 1. Server Startup

```bash
py -3.11 serve.py
# For LAN/projector access with camera:
py -3.11 serve.py --ssl
```

| # | Expected log line | Pass? |
|---|---|---|
| 1.1 | `SmartFace \| Production \| Waitress WSGI` | [x] |
| 1.2 | `load_known_faces: loaded N encoding(s)` | [x] |
| 1.3 | `Shape predictor loaded — liveness detection active` | [x] |
| 1.4 | No `SyntaxError` / `ImportError` | [x] |

---

## 2. Authentication

| # | Test | Expected | Pass? |
|---|---|---|---|
| 2.1 | Login `admin@sacli.edu.ph` / `Admin123` | Redirect to `/dashboard` | [x] |
| 2.2 | Wrong password | Generic "Invalid credentials." message | [F] |
| 2.3 | 3 wrong attempts | "Locked for 30 second(s)." | [ ] |
| 2.4 | Logout → Cancel | Stays logged in | [ ] |
| 2.5 | Logout → Confirm | Redirects to `/login` | [ ] |
| 2.6 | Leave idle 30 min, refresh | Still logged in (8-hour session) | [ ] |

---

## 3. Enrollment (`/enroll`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 3.1 | Page loads | Webcam feed appears | [ ] |
| 3.2 | Face enters frame | Green corner brackets + oval overlay, "Face detected ✓" pill | [ ] |
| 3.3 | Capture button | Pulses green when face detected | [ ] |
| 3.4 | Blurry/shaky image | Error: "image too blurry" | [ ] |
| 3.5 | Stand far from camera | Error: "face too small — move closer" | [ ] |
| 3.6 | 5 good samples + form filled | Success toast, user appears in `/users` | [ ] |
| 3.7 | Duplicate email | Error: "A user with that email already exists." | [ ] |

---

## 4. Kiosk (`/kiosk`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 4.1 | Page loads | No vertical scrollbar, video fills space | [ ] |
| 4.2 | Face in frame | Scan line animation + mesh overlay | [ ] |
| 4.3 | No blink yet | Face detected (brackets) but NOT matched | [ ] |
| 4.4 | Blink naturally | Name + confidence % appears immediately | [ ] |
| 4.5 | Unknown person | Red "Unknown" label and bounding box | [ ] |
| 4.6 | Check `/dashboard` after recognition | Name in Today's Attendance table | [ ] |
| 4.7 | Return within 30s | Recognized again, time_out updates, no new row | [ ] |
| 4.8 | Success match | Ascending chime plays | [ ] |
| 4.9 | Unknown face | Lower fail tone plays | [ ] |
| 4.10 | Cover lens / dim lights | Orange brightness warning banner | [ ] |

---

## 5. Dashboard (`/dashboard`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 5.1 | 4 summary cards | Present / Late / Absent / Registered Users | [ ] |
| 5.2 | 7-day bar chart | Green (Present) + Gold (Late) bars | [ ] |
| 5.3 | Today's donut chart | Present/Late/Absent with % labels | [ ] |
| 5.4 | Keep open while kiosk runs | Table updates without page refresh (every 3s) | [ ] |
| 5.5 | Confidence ≥ 90% | Green bar + green text | [ ] |
| 5.6 | Confidence 70–89% | Gold bar + gold text | [ ] |
| 5.7 | Confidence < 70% | Red bar + red text | [ ] |

---

## 6. User Management (`/users`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 6.1 | Enrolled user | Green "✓ N samples" badge | [ ] |
| 6.2 | Unenrolled user | Red "✗ Not enrolled" badge | [ ] |
| 6.3 | Search by name | Table filters correctly | [ ] |
| 6.4 | Search clear button | All users shown again | [ ] |
| 6.5 | Edit → Save | Profile updates, flash message | [ ] |
| 6.6 | Deactivate → Cancel | No change | [ ] |
| 6.7 | Deactivate → Confirm | User shows Inactive badge | [ ] |
| 6.8 | Re-enroll → Confirm | Badge changes to "✗ Not enrolled" | [ ] |
| 6.9 | Delete → Confirm | User removed from list | [ ] |
| 6.10 | Delete own account | Button disabled / blocked | [ ] |

---

## 7. Reports (`/reports`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 7.1 | Filter by date range | Only records in range shown | [ ] |
| 7.2 | Filter by role = Student | All rows have role Student | [ ] |
| 7.3 | Start > End date | Error: "Start date cannot be after end date" | [ ] |
| 7.4 | Export CSV | Downloads `.csv` with correct 9 columns | [ ] |
| 7.5 | Export PDF | Downloads A4 landscape PDF with SACLI header | [ ] |

---

## 8. Audit Log (`/audit`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 8.1 | Entries visible | Rows with timestamp, action, details | [ ] |
| 8.2 | Filter by action | Only selected action type shown | [ ] |
| 8.3 | Filter by date range | Only entries in range shown | [ ] |
| 8.4 | Clear button | All filters reset, full list restored | [ ] |

---

## 9. Student Self-Service (`/my-attendance`)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 9.1 | Login as student, open `/my-attendance` | Only own records visible | [ ] |
| 9.2 | No records exist | "No attendance records found." message | [ ] |

---

## 10. Automated Test Suite

Run each command and verify the expected count:

```bash
# Property-based tests (fastest)
py -3.11 -m pytest tests/test_face_service.py tests/test_attendance_service.py -q
# Expected: 8 passed

py -3.11 -m pytest tests/test_override.py -q
# Expected: 4 passed

py -3.11 -m pytest tests/test_reports.py -q
# Expected: 5 passed

py -3.11 -m pytest tests/test_dashboard.py -q
# Expected: 3 passed

py -3.11 -m pytest tests/test_enrollment.py -q
# Expected: 3 passed

py -3.11 -m pytest tests/test_auth.py -q -k "not property"
# Expected: 3 passed

# Total: 26 passed
```

| Test File | Expected | Actual | Pass? |
|---|---|---|---|
| `test_face_service.py` + `test_attendance_service.py` | 8 | | [ ] |
| `test_override.py` | 4 | | [ ] |
| `test_reports.py` | 5 | | [ ] |
| `test_dashboard.py` | 3 | | [ ] |
| `test_enrollment.py` | 3 | | [ ] |
| `test_auth.py` (unit only) | 3 | | [ ] |

---

## 11. Render Cloud Verification

| # | Test | Expected | Pass? |
|---|---|---|---|
| 11.1 | Open `https://smartface-attendance-fdw0.onrender.com` | Login page loads (may take ~30s to wake) | [ ] |
| 11.2 | Login with `admin@sacli.edu.ph` / `Admin123` | Reaches `/dashboard` | [ ] |
| 11.3 | Dashboard charts load | Cards + charts visible | [ ] |
| 11.4 | Open `/kiosk` | Page loads, "Waiting for face..." (recognition disabled on cloud) | [ ] |
| 11.5 | Reports and Audit pages | Load and filter correctly | [ ] |

---

## 12. Panel Q&A — Know These Answers

**Q: Why does the kiosk require a blink before recognizing?**  
A: Liveness detection via Eye Aspect Ratio (EAR). When EAR < 0.22 for ≥2 consecutive frames, a blink is confirmed. Prevents photo/screen spoofing. See `services/face_service.py` Step 7.

**Q: What is TOLERANCE and why 0.45?**  
A: Euclidean distance threshold for face matching. 0.45 is stricter than dlib's default 0.6 — fewer false positives at the cost of stricter matching. Configurable via `TOLERANCE` env var.

**Q: How does the debounce work?**  
A: First recognition creates `time_in`. Subsequent recognitions within 30 seconds update `time_out` only. Enforced by `last_seen_dict` in memory + `UNIQUE KEY (user_id, date)` at DB level.

**Q: How is RA 10173 compliance handled?**  
A: `consent_given=1` must be set before any face encoding is stored. Validated server-side in `POST /api/enroll` regardless of front-end state.

**Q: Where is the liveness hook?**  
A: `services/face_service.py`, function `recognize_frame()`, Step 7. Comment reads: *"LIVENESS HOOK: Eye Aspect Ratio blink detection implemented here."*

**Q: Why dlib instead of DeepFace/TensorFlow?**  
A: TensorFlow needs ~400MB RAM. Render free tier only has 512MB. `dlib-bin` is pre-compiled, uses ~150MB total, and installs without building from source.

**Q: What if the database is unreachable at startup?**  
A: App starts with an empty encoding cache and logs an error. Recognition returns all faces as Unknown. Non-fatal by design — cache reloads when DB reconnects.

**Q: How are face encodings stored?**  
A: 128-dim `float64` numpy array → `.tobytes()` → 1024-byte `BYTEA` in PostgreSQL. Deserialized with `np.frombuffer(blob, dtype=np.float64)`.

---

## 13. Security — CSRF Protection

CSRF tokens are now generated per-session in `app.py` (`before_request`) and exposed to all templates via a `csrf_token()` context processor. Every state-changing HTML form (login, change-password, users, enroll) includes the token.

| # | Test | Expected | Pass? |
|---|---|---|---|
| 13.1 | Submit login form with the CSRF token removed (use browser dev-tools or curl to omit the `csrf_token` field) | Server returns `403 Forbidden` | [ ] |
| 13.2 | Submit login form normally (token present and valid) | Redirect to `/dashboard` as usual | [ ] |
| 13.3 | Submit `/change-password` form without the CSRF token | Server returns `403 Forbidden` | [ ] |
| 13.4 | Submit `/change-password` form with the correct token | Password updated, success flash message | [ ] |
| 13.5 | Submit user-edit or delete form without the CSRF token | Server returns `403 Forbidden` | [ ] |
| 13.6 | Submit enroll form without the CSRF token | Server returns `403 Forbidden` | [ ] |
| 13.7 | View page source of any state-changing form | `<input type="hidden" name="csrf_token" value="...">` is present | [ ] |

---

## 14. Forced Password Change

The `users` table has a `must_change_password` SMALLINT column. When set to `1`, the user is redirected to `/change-password` immediately after login. After a successful password change, the column is reset to `0`.

| # | Test | Expected | Pass? |
|---|---|---|---|
| 14.1 | In DB, set `must_change_password = 1` for a non-admin test user | — (setup step) | [ ] |
| 14.2 | Log in as that user | After login, browser redirects to `/change-password` instead of `/dashboard` | [ ] |
| 14.3 | Attempt to navigate to `/dashboard` while `must_change_password = 1` | Redirected back to `/change-password` | [ ] |
| 14.4 | Submit `/change-password` with a new valid password | Redirect to `/dashboard`, success flash message | [ ] |
| 14.5 | In DB, verify `must_change_password` for that user after step 14.4 | Column value is `0` | [ ] |
| 14.6 | Log out and log back in as the same user | Goes directly to `/dashboard` with no forced redirect | [ ] |

---

## 15. Liveness — Per-Recognition Reset

The `_liveness` dict is now reset after every accepted match. Each new recognition event requires a fresh blink; a blink from a previous accepted match does not carry over.

| # | Test | Expected | Pass? |
|---|---|---|---|
| 15.1 | Blink in front of kiosk → recognition accepted | Name + confidence appears | [ ] |
| 15.2 | Immediately present same face again (no blink) | Face detected (brackets) but recognition NOT accepted | [ ] |
| 15.3 | Blink again | Recognition accepted a second time | [ ] |
| 15.4 | Person A blinks → accepted; Person B presents face without blinking | Person B is NOT matched | [ ] |
| 15.5 | Person B then blinks | Person B is matched | [ ] |

---

## 16. New Routes

### 16a. `/change-password` (GET/POST, authenticated)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 16.1 | Logged-in user visits `/change-password` | Page loads with status `200`, form displayed | [ ] |
| 16.2 | Unauthenticated visitor visits `/change-password` | Redirect to `/login` | [ ] |
| 16.3 | Submit valid new password with correct CSRF token | Password updated, redirect to `/dashboard` | [ ] |
| 16.4 | Submit mismatched passwords | Error message displayed, stays on form | [ ] |

### 16b. `/accuracy-test` (GET, admin only — FAR/FRR metrics)

| # | Test | Expected | Pass? |
|---|---|---|---|
| 16.5 | Admin visits `/accuracy-test` | Page loads with status `200` | [ ] |
| 16.6 | FAR/FRR metrics table is visible | Table rendered with False Accept Rate and False Reject Rate columns | [ ] |
| 16.7 | Non-admin (student/staff) visits `/accuracy-test` | Returns `403 Forbidden` | [ ] |
| 16.8 | Unauthenticated visitor visits `/accuracy-test` | Redirect to `/login` | [ ] |

### 16c. Route Count

| # | Check | Expected | Pass? |
|---|---|---|---|
| 16.9 | Count registered routes in `app.py` | 23 routes total (up from 21) | [ ] |

---

*Tester: ___________________ | Date: ___________________ | All critical items passed: [ ] YES [ ] NO*