-- SmartFace Attendance System — Database Schema
-- Institution: St. Anne College Lucena, Inc. (SACLI)
-- Engine: InnoDB | Charset: utf8mb4_unicode_ci
-- Run: mysql -u <user> -p < database/schema.sql

CREATE DATABASE IF NOT EXISTS smartface_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE smartface_db;

-- ---------------------------------------------------------------------------
-- users
-- Stores all registered system actors: admin, faculty, and student.
-- consent_given enforces RA 10173 (Data Privacy Act) compliance —
-- no face encoding may be created unless this flag is 1.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
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

-- ---------------------------------------------------------------------------
-- face_encodings
-- Stores one row per enrollment sample (3–5 per user).
-- encoding is a raw BLOB of np.ndarray(128, float64).tobytes() — 1024 bytes.
-- Round-trip: np.frombuffer(blob, dtype=np.float64) → shape (128,)
-- ON DELETE CASCADE keeps the table clean when a user is removed.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_encodings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    encoding    BLOB NOT NULL,          -- np.ndarray(128, float64).tobytes()
    sample_no   TINYINT NOT NULL,       -- 1..5 — which capture shot this is
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- attendance
-- One row per user per calendar day (enforced by uniq_user_day).
-- First recognition of the day → INSERT (time_in set, status assigned).
-- Subsequent recognitions → ON DUPLICATE KEY UPDATE time_out only.
-- marked_by NULL = automatic recognition; non-NULL = admin manual override.
-- Late threshold is configurable in config.py (default 08:00:00).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attendance (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NOT NULL,
    date        DATE NOT NULL,
    time_in     TIME,
    time_out    TIME,
    status      ENUM('present','late','absent','manual') NOT NULL DEFAULT 'present',
    confidence  FLOAT,                  -- match confidence 0.0–100.0
    marked_by   INT NULL,               -- NULL = automatic; set = admin override
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_day (user_id, date),   -- DB-level duplicate guard
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- audit_logs
-- Append-only log of security-relevant events:
--   login, logout, enrollment, manual override, user deactivation.
-- user_id is NULL for system events (e.g., failed login with unknown email).
-- ip_address stored as VARCHAR(45) to accommodate both IPv4 and IPv6.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    user_id     INT NULL,               -- NULL for anonymous / system events
    action      VARCHAR(255) NOT NULL,
    details     TEXT,
    ip_address  VARCHAR(45),            -- IPv4 (15) or IPv6 (39) — 45 is safe
    timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
);
