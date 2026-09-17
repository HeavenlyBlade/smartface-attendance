-- SmartFace Attendance System -- Database Schema
-- Compatible with managed MySQL (Aiven, PlanetScale, etc.)
-- No CREATE DATABASE or USE statements needed.

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(150) NOT NULL,
    email         VARCHAR(150) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','faculty','student') NOT NULL DEFAULT 'student',
    id_number     VARCHAR(50) UNIQUE,
    department    VARCHAR(100),
    consent_given TINYINT(1) NOT NULL DEFAULT 0,
    is_active     TINYINT(1) NOT NULL DEFAULT 1,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    encoding   BLOB NOT NULL,
    sample_no  TINYINT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attendance (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NOT NULL,
    date       DATE NOT NULL,
    time_in    TIME,
    time_out   TIME,
    status     ENUM('present','late','absent','manual') NOT NULL DEFAULT 'present',
    confidence FLOAT,
    marked_by  INT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_user_day (user_id, date),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT NULL,
    action     VARCHAR(255) NOT NULL,
    details    TEXT,
    ip_address VARCHAR(45),
    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
);