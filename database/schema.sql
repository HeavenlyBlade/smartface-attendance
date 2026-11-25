-- SQLite foreign key enforcement
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT NOT NULL,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student'
                  CHECK (role IN ('admin','faculty','student')),
    id_number     TEXT UNIQUE,
    department    TEXT,
    consent_given INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    encoding   BLOB NOT NULL,
    sample_no  INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student'
                  CHECK (role IN ('student', 'faculty')),
    department    TEXT,
    days_of_week  TEXT NOT NULL DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday',
    start_time    TIME NOT NULL DEFAULT '08:00:00',
    end_time      TIME NOT NULL DEFAULT '17:00:00',
    grace_period_mins INTEGER NOT NULL DEFAULT 15,
    is_default    INTEGER NOT NULL DEFAULT 0,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS attendance (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date          DATE NOT NULL,
    time_in       TIME,
    time_out      TIME,
    status        TEXT NOT NULL DEFAULT 'present'
                  CHECK (status IN ('present','late','absent','manual')),
    confidence    FLOAT,
    marked_by     INT,
    schedule_id   INTEGER REFERENCES schedules(id),
    late_minutes  INTEGER DEFAULT 0,
    late_reason   TEXT DEFAULT '',
    late_remarks  TEXT DEFAULT '',
    scanner_id    TEXT DEFAULT 'Main Kiosk',
    is_excused    INTEGER DEFAULT 0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, date)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INT,
    action     TEXT NOT NULL,
    details    TEXT,
    ip_address TEXT,
    timestamp  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
