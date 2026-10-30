-- Password login for portal users: hashed passwords, server-side sessions, login attempt history.
-- Passwords are stored only as scrypt hashes. Session tokens are stored only as SHA-256 hashes.
SET search_path = inv;

ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash text;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_changed_at timestamptz;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;

CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id    bigserial PRIMARY KEY,
    token_sha256  text NOT NULL UNIQUE,
    user_id       uuid NOT NULL REFERENCES app_users(user_id) ON DELETE CASCADE,
    created_at    timestamptz NOT NULL DEFAULT now(),
    expires_at    timestamptz NOT NULL,
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at    timestamptz,
    client_ip     text,
    user_agent    text
);
CREATE INDEX IF NOT EXISTS auth_sessions_user ON auth_sessions (user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS login_attempts (
    attempt_id  bigserial PRIMARY KEY,
    at          timestamptz NOT NULL DEFAULT now(),
    email       text NOT NULL,
    client_ip   text,
    success     boolean NOT NULL,
    reason      text
);
CREATE INDEX IF NOT EXISTS login_attempts_email_at ON login_attempts (email, at DESC);
CREATE INDEX IF NOT EXISTS login_attempts_ip_at ON login_attempts (client_ip, at DESC);
