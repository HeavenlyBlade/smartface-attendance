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

CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       DATE NOT NULL,
    time_in    TIME,
    time_out   TIME,
    status     TEXT NOT NULL DEFAULT 'present'
               CHECK (status IN ('present','late','absent','manual')),
    confidence FLOAT,
    marked_by  INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
