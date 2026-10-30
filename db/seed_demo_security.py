"""Create clearly-labelled DEMO portal users and case access, to show the three views.

    python db/seed_demo_security.py --dsn "$SUPABASE_DATABASE_URL"

Idempotent (fixed IDs). Every account is is_demo = true; all but the last have names starting with "Demo". The last
account deliberately shares a name with a GAStech employee so the conflict-of-interest check has
something to show; that is stated in its badge field. Remove with --remove.

Switch views locally (AUTH_ENABLED=false, localhost) by sending the header  X-Demo-User: <user_id>.
"""
import argparse

import psycopg

USERS = [
    # user_id, email, display_name, role, badge
    ("00000000-0000-4000-a000-000000000001", "demo.admin@sih26189.demo", "Demo Admin (Cyber Cell)", "admin", "DEMO-ADM-01"),
    ("00000000-0000-4000-a000-000000000002", "demo.investigator1@sih26189.demo", "Demo Insp. Kavya Rao", "investigator", "DEMO-INV-01"),
    ("00000000-0000-4000-a000-000000000003", "demo.investigator2@sih26189.demo", "Demo SI Arjun Mehta", "investigator", "DEMO-INV-02"),
    ("00000000-0000-4000-a000-000000000004", "demo.viewer@sih26189.demo", "Demo Analyst Neha Iyer", "viewer", "DEMO-VW-01"),
    # Name matches a GAStech security-department employee, to demonstrate the conflict-of-interest check.
    ("00000000-0000-4000-a000-000000000005", "demo.coi@sih26189.demo", "Kanon Herrero", "investigator", "DEMO-COI: name matches a case subject on purpose"),
]
MEMBERS = [
    ("00000000-0000-4000-a000-000000000002", "CASE_VAST_GASTECH", "editor"),
    ("00000000-0000-4000-a000-000000000002", "CASE_NOORDIN", "editor"),
    ("00000000-0000-4000-a000-000000000003", "CASE_CAVIAR", "editor"),
    ("00000000-0000-4000-a000-000000000003", "CASE_VAST_GASTECH", "viewer"),
    ("00000000-0000-4000-a000-000000000004", "CASE_VAST_GASTECH", "viewer"),
    ("00000000-0000-4000-a000-000000000004", "CASE_CAVIAR", "viewer"),
    ("00000000-0000-4000-a000-000000000005", "CASE_VAST_GASTECH", "editor"),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", required=True)
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args(argv)
    with psycopg.connect(a.dsn) as conn:
        ids = [u[0] for u in USERS]
        conn.execute("DELETE FROM inv.case_members WHERE user_id = ANY(%s::uuid[])", (ids,))
        if a.remove:
            conn.execute("DELETE FROM inv.app_users WHERE user_id = ANY(%s::uuid[]) AND is_demo", (ids,))
            print("demo users removed")
            return 0
        for uid, email, name, role, badge in USERS:
            conn.execute("""INSERT INTO inv.app_users (user_id,email,display_name,role,badge_number,is_demo)
                VALUES (%s,%s,%s,%s,%s,true) ON CONFLICT (user_id) DO UPDATE SET email=EXCLUDED.email,
                display_name=EXCLUDED.display_name, role=EXCLUDED.role, badge_number=EXCLUDED.badge_number, active=true""",
                (uid, email, name, role, badge))
        existing = {r[0] for r in conn.execute("SELECT case_id FROM inv.cases").fetchall()}
        for uid, case_id, level in MEMBERS:
            if case_id in existing:
                conn.execute("INSERT INTO inv.case_members (case_id,user_id,access_level) VALUES (%s,%s,%s)", (case_id, uid, level))
    for uid, email, name, role, _ in USERS:
        print(f"{role:13} {name:28} X-Demo-User: {uid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
