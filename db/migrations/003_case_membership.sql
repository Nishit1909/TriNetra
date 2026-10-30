-- Investigator accounts are Supabase Auth users; they are not investigated persons.
CREATE TABLE IF NOT EXISTS inv.case_members (
    case_id text NOT NULL REFERENCES inv.cases(case_id) ON DELETE CASCADE,
    user_id uuid NOT NULL,
    access_level text NOT NULL CHECK (access_level IN ('viewer','editor')),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(case_id,user_id)
);
CREATE INDEX IF NOT EXISTS case_members_user ON inv.case_members(user_id,case_id);
-- user_id is the external Supabase Auth subject. No passwords or automatic account creation.
