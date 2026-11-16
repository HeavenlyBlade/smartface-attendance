# SQLite Migration Review

**Project:** SmartFace — Flask attendance system  
**Commit:** feat: migrate DB from PostgreSQL to SQLite, add PyInstaller spec  
**Pass:** First review pass

---

## Evidence Summary

### Commit verification results (from commit message)
1. `py -3.11 -c "from app import create_app; app = create_app(); print('OK')"` → OK ✓  
2. `py -3.11 database/seed.py` → SKIP (already seeded, idempotency confirmed) ✓  
3. `sqlite3 query` → 13 users: 1 admin, 1 faculty, 11 BSIT students ✓  
4. Flask test client `POST /login` → STATUS: 302, LOGIN OK ✓  

All 4 required verification checks passed.

---

## Checklist Findings

### 1. models/db.py
- **sqlite3 only**: ✓ — imports `sqlite3`, `threading`; no psycopg2.  
- **threading.local()**: ✓ — `_local = threading.local()` at module level; `get_connection()` stores per-thread conn in `_local.conn`.  
- **execute_query signature**: ✓ — `def execute_query(sql, params=(), fetchone=False, fetchall=False, commit=False)` matches required signature exactly.  
- **Returns lastrowid on INSERT+commit**: ✓ — `db.py` line 70: `return cur.lastrowid` when `commit=True` and `is_insert`.  
- **fetchall returns list of plain dicts**: ✓ — `[dict(r) for r in rows]`.  
- **fetchone returns dict or None**: ✓ — `dict(row) if row else None`.  
- **PRAGMA foreign_keys=ON**: ✓ — `conn.execute("PRAGMA foreign_keys = ON")` on every new connection.

### 2. database/schema.sql
- **SERIAL→INTEGER PRIMARY KEY AUTOINCREMENT**: ✓  
- **SMALLINT→INTEGER, VARCHAR→TEXT, BYTEA→BLOB**: ✓  
- **No RETURNING**: ✓ — not present.  
- **ON CONFLICT clause**: ✓ — `UNIQUE (user_id, date)` in `attendance` table enables it.  
- **No PostgreSQL-specific syntax**: ✓

### 3. database/seed.py
- **No psycopg2 imports**: ✓ — imports only `werkzeug.security`, `models.db`.  
- **? placeholders**: ✓ — all SQL in `_insert_user` and attendance insert uses `?`.  
- **cursor.lastrowid**: ✓ — `_insert_user` uses `cur.lastrowid`.  
- **13 users present**: ✓ — 1 `ADMIN_USER` + 1 `FACULTY_USERS` + 11 `STUDENT_USERS`; commit message reports 13 rows confirmed.  
- **Attendance insert uses ? placeholders**: ✓ — `VALUES (?, ?, ?, ?, ?, ?, ?)`.

### 4. database/init_db.py
- **No psycopg2**: ✓  
- **Uses sqlite3 via get_connection()**: ✓  
- **Uses executescript for DDL**: ✓ — `conn.executescript(sql)`.  
- **Checks sqlite_master for table existence**: ✓ — `SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'`.

### 5. models/user.py, models/attendance.py, models/audit.py
- **All %s replaced with ?**: ✓ — every SQL statement in these files uses `?`.  
- **ILIKE replaced with LOWER(...) LIKE LOWER(...)**: ✓ — `user.py` `list_users()` uses `LOWER(full_name) LIKE LOWER(?)` etc.

### 6. routes/ and services/
- **All %s replaced with ?**: ✓ — all SQL strings in `routes/attendance.py`, `routes/admin.py`, `routes/auth.py`, `services/attendance_service.py`, `services/face_service.py` use `?`.  
- **No RETURNING clauses in DML**: ✓ — grep confirmed zero occurrences.  
- **No psycopg2 imports**: ✓ — no `import psycopg2` or `from psycopg2` anywhere.

### 7. routes/api.py
- **psycopg2 imports removed**: ✓  
- **psycopg2.Binary removed**: ✓ — encoding stored directly as `serialize_encoding(enc)` bytes.  
- **RETURNING id removed**: ✓ — grep confirmed absent.  
- **lastrowid used instead**: ✓ — `new_user_id = cursor.lastrowid` after INSERT.

### 8. config.py
- **DB_HOST/DB_PORT/DB_USER/DB_PASS/DB_NAME removed**: ✓ — none present; only TOLERANCE, LATE_TIME, SECRET_KEY, UPLOAD_DIR, BRIGHTNESS_THRESHOLD remain.

### 9. requirements-local.txt
- **psycopg2-binary removed**: ✓ — not in file.  
- **pyinstaller>=6.0 added**: ✓ — `pyinstaller>=6.0` present.

### 10. launcher.py
- **Exists**: ✓  
- **Starts Flask via waitress in a thread**: ✓ — `threading.Thread(target=_serve, daemon=True)`.  
- **Polls /login**: ✓ — `_wait_for_server()` calls `urllib.request.urlopen(URL + '/login')`.  
- **Opens browser**: ✓ — `webbrowser.open(URL)`.

### 11. smartface.spec
- **Exists**: ✓  
- **onedir build**: ✓ — uses `COLLECT(...)`, not `EXE(..., a.binaries, ...)` single-file.  
- **Correct datas**: ✓ — `('templates', 'templates')`, `('static', 'static')`, `('database/schema.sql', 'database')`.  
- **psycopg2 excluded**: ✓ — `excludes=['psycopg2']`.

---

## Stale Documentation Notes (non-blocking)

- `services/attendance_service.py` module docstring (line 28) reads "All SQL uses %s parameterized placeholders". The actual SQL in the file correctly uses `?`. This is a documentation-only stale remnant — it has no effect on executed code.  
- `attendance_service.py` inline comment line 177 says "PostgreSQL ON CONFLICT syntax". `ON CONFLICT … DO UPDATE` is valid SQLite syntax; the comment is misleading but the SQL executes correctly.  
- `routes/auth.py` has a leftover comment "Run in Supabase SQL Editor: ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password...". This is cosmetic only.

These are pre-existing cosmetic issues, not introduced by the migration, and not blockers.

---

## Verdict

**APPROVED** — All blocking criteria are satisfied. No psycopg2 imports remain. No `%s` SQL placeholders remain. No `RETURNING` clauses in DML. `execute_query` signature is unchanged. All 4 verification checks passed per commit message. `launcher.py` and `smartface.spec` are present and correct. `DB_HOST/PORT/USER/PASS/NAME` are absent from `config.py`.
