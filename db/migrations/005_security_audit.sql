-- Security layer: portal users and roles, access log, alerts, admin settings.
-- Per-case access stays in inv.case_members (viewer / editor). Portal role decides the screens:
--   viewer        read-only on assigned cases
--   investigator  edit (run analysis, review leads, upload) on assigned cases
--   admin         every case + admin portal (users, access log, alerts, SMTP)
SET search_path = inv;

CREATE TABLE IF NOT EXISTS app_users (
    user_id       uuid PRIMARY KEY,
    email         text NOT NULL UNIQUE,
    display_name  text NOT NULL,
    role          text NOT NULL CHECK (role IN ('viewer','investigator','admin')),
    phone         text,
    badge_number  text,
    is_demo       boolean NOT NULL DEFAULT false,   -- demo accounts are labelled as such everywhere
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS access_log (
    log_id        bigserial PRIMARY KEY,
    at            timestamptz NOT NULL DEFAULT now(),
    user_id       uuid,
    user_label    text NOT NULL,
    role          text,
    method        text NOT NULL,
    path          text NOT NULL,
    case_id       text,
    person_id     text,
    action        text NOT NULL,          -- view_case, view_person, run_analysis, upload, review, admin, ...
    status_code   integer NOT NULL,
    allowed       boolean NOT NULL,
    client_ip     text,
    user_agent    text,
    request_id    text,
    duration_ms   integer
);
CREATE INDEX IF NOT EXISTS access_log_at ON access_log (at DESC);
CREATE INDEX IF NOT EXISTS access_log_user ON access_log (user_id, at DESC);
CREATE INDEX IF NOT EXISTS access_log_case ON access_log (case_id, at DESC);

CREATE TABLE IF NOT EXISTS security_alerts (
    alert_id         bigserial PRIMARY KEY,
    at               timestamptz NOT NULL DEFAULT now(),
    rule             text NOT NULL,       -- denied_access, after_hours, bulk_viewing, sensitive_action, conflict_of_interest
    severity         text NOT NULL CHECK (severity IN ('low','medium','high')),
    user_id          uuid,
    user_label       text NOT NULL,
    case_id          text,
    title            text NOT NULL,
    detail           jsonb NOT NULL DEFAULT '{}'::jsonb,
    dedupe_key       text,                -- one open alert per key (e.g. rule:user:case:window)
    status           text NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','dismissed')),
    reviewed_by      text,
    reviewed_at      timestamptz,
    review_note      text,
    email_status     text NOT NULL DEFAULT 'not_sent' CHECK (email_status IN ('not_sent','sent','failed','disabled','below_threshold')),
    email_error      text
);
CREATE UNIQUE INDEX IF NOT EXISTS security_alerts_dedupe ON security_alerts (dedupe_key) WHERE dedupe_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS security_alerts_at ON security_alerts (at DESC);

-- Non-secret settings only. The SMTP password is read from the SMTP_PASSWORD environment variable.
CREATE TABLE IF NOT EXISTS admin_settings (
    key         text PRIMARY KEY,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    updated_by  text NOT NULL
);

-- The access log is evidence about the system itself: append-only.
CREATE OR REPLACE FUNCTION reject_access_log_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Access log records are immutable';
END;
$$;
DROP TRIGGER IF EXISTS immutable_access_log ON access_log;
CREATE TRIGGER immutable_access_log BEFORE UPDATE OR DELETE ON access_log
FOR EACH ROW EXECUTE FUNCTION reject_access_log_mutation();
