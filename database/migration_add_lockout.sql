-- Migration: add server-side login-lockout columns to users table
-- Issue: M2 — login lockout was stored in the Flask session (client-side resettable)
-- Apply in the Supabase SQL Editor (or via psql) before deploying the updated routes/auth.py.
--
-- Idempotent: uses ALTER TABLE … ADD COLUMN IF NOT EXISTS so re-running is safe.

ALTER TABLE users
    ADD COLUMN IF NOT EXISTS login_attempts INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS lockout_until  TIMESTAMP;
