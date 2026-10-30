"""Password login: sessions, roles, lockout, CSRF, logout, password changes, admin resets."""
import os
import pathlib
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.skipif(not os.getenv("INV_TEST_DSN"), reason="needs disposable INV_TEST_DSN")

ADMIN = ("demo.admin@sih26189.demo", "Admin@Trace2026")
INVESTIGATOR = ("demo.investigator1@sih26189.demo", "Investigator@2026")
VIEWER = ("demo.viewer@sih26189.demo", "Viewer@Trace2026")
CSRF = {"X-TRACE-CSRF": "1"}


@pytest.fixture
def app(monkeypatch):
    from app import config
    import app.main as main
    dsn = os.environ["INV_TEST_DSN"]
    monkeypatch.setattr(config.settings, "supabase_database_url", dsn)
    monkeypatch.setattr(config.settings, "auth_enabled", False)
    monkeypatch.setattr(config.settings, "login_required", True)
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "db"))
    import seed_demo_security
    seed_demo_security.main(["--dsn", dsn])
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM inv.login_attempts")
        conn.execute("DELETE FROM inv.auth_sessions")
        conn.execute("DELETE FROM inv.security_alerts")
    return main.app


def client(app):
    return TestClient(app)


def signed_in(app, creds):
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"email": creds[0], "password": creds[1]})
    assert r.status_code == 200, r.text
    return c


def test_login_required_and_three_roles(app):
    anon = client(app)
    assert anon.get("/api/cases").status_code == 401
    assert anon.get("/api/cases", headers={"X-Demo-User": "00000000-0000-4000-a000-000000000001"}).status_code == 401

    admin = signed_in(app, ADMIN)
    me = admin.get("/api/auth/me").json()
    assert me["view"] == "admin" and me["display_name"] == "Demo Admin (Cyber Cell)" and me["login_required"] is True
    assert admin.get("/api/admin/users").status_code == 200
    assert all("password_hash" not in u and "has_password" in u for u in admin.get("/api/admin/users").json())

    inv = signed_in(app, INVESTIGATOR)
    assert inv.get("/api/auth/me").json()["view"] == "investigator"
    assert inv.post("/api/cases/CASE_NOORDIN/analysis", json={"mode": "observed_only"}, headers=CSRF).json()["run"]["status"] == "completed"
    assert inv.get("/api/admin/users").status_code == 403

    viewer = signed_in(app, VIEWER)
    assert viewer.get("/api/auth/me").json()["view"] == "viewer"
    assert viewer.get("/api/cases/CASE_VAST_GASTECH/summary").status_code == 200
    assert viewer.post("/api/cases/CASE_VAST_GASTECH/analysis", json={"mode": "observed_only"}, headers=CSRF).status_code == 403
    assert viewer.get("/api/cases/CASE_NOORDIN/summary").status_code == 403


def test_session_cookie_is_httponly_and_strict(app):
    r = client(app).post("/api/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
    cookie = r.headers["set-cookie"].lower()
    assert "trace_session=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    with psycopg.connect(os.environ["INV_TEST_DSN"]) as conn:
        stored = conn.execute("SELECT token_sha256 FROM inv.auth_sessions").fetchone()[0]
    token = r.cookies.get("trace_session")
    assert stored != token and len(stored) == 64          # only the hash is stored


def test_wrong_password_and_unknown_email_look_the_same(app):
    c = client(app)
    a = c.post("/api/auth/login", json={"email": ADMIN[0], "password": "wrong-password-1"})
    b = c.post("/api/auth/login", json={"email": "nobody@example.org", "password": "whatever-123"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Email or password is incorrect."}


def test_lockout_after_five_failures_and_alerts(app):
    c = client(app)
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": VIEWER[0], "password": "bad-guess-123"}).status_code == 401
    # even the right password is refused while locked
    assert c.post("/api/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]}).status_code == 429
    admin = signed_in(app, ADMIN)
    alerts = admin.get("/api/admin/alerts").json()["items"]
    failed = [a for a in alerts if a["rule"] == "failed_login"]
    assert {a["severity"] for a in failed} == {"medium", "high"}


def test_csrf_header_required_for_cookie_writes(app):
    inv = signed_in(app, INVESTIGATOR)
    assert inv.post("/api/cases/CASE_NOORDIN/analysis", json={"mode": "observed_only"}).status_code == 403
    assert inv.get("/api/cases/CASE_NOORDIN/summary").status_code == 200   # reads don't need it


def test_logout_and_session_revocation(app):
    viewer = signed_in(app, VIEWER)
    assert viewer.post("/api/auth/logout").json()["signed_out"] is True
    assert viewer.get("/api/cases").status_code == 401

    viewer = signed_in(app, VIEWER)
    admin = signed_in(app, ADMIN)
    sessions = admin.get("/api/admin/sessions").json()
    sid = next(s["session_id"] for s in sessions if s["email"] == VIEWER[0])
    assert admin.post(f"/api/admin/sessions/{sid}/revoke", headers=CSRF).json()["revoked"] is True
    assert viewer.get("/api/cases").status_code == 401

    viewer = signed_in(app, VIEWER)
    uid = "00000000-0000-4000-a000-000000000004"
    admin.post(f"/api/admin/users/{uid}", json={"active": False}, headers=CSRF)
    assert viewer.get("/api/cases").status_code == 401                     # deactivation ends sessions
    assert client(app).post("/api/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]}).status_code == 401
    admin.post(f"/api/admin/users/{uid}", json={"active": True}, headers=CSRF)


def test_password_change_and_admin_reset(app):
    inv = signed_in(app, INVESTIGATOR)
    weak = inv.post("/api/auth/password", json={"current_password": INVESTIGATOR[1], "new_password": "short"}, headers=CSRF)
    assert weak.status_code == 422
    ok = inv.post("/api/auth/password", json={"current_password": INVESTIGATOR[1], "new_password": "NewSecret2026x"}, headers=CSRF)
    assert ok.json()["changed"] is True
    assert inv.get("/api/cases").status_code == 401                        # signed out everywhere
    assert client(app).post("/api/auth/login", json={"email": INVESTIGATOR[0], "password": INVESTIGATOR[1]}).status_code == 401
    signed_in(app, (INVESTIGATOR[0], "NewSecret2026x"))

    admin = signed_in(app, ADMIN)
    uid = "00000000-0000-4000-a000-000000000002"
    r = admin.post(f"/api/admin/users/{uid}/password", json={"password": INVESTIGATOR[1]}, headers=CSRF)
    assert r.json()["password_reset"] is True
    signed_in(app, INVESTIGATOR)


def test_login_events_in_access_log(app):
    client(app).post("/api/auth/login", json={"email": VIEWER[0], "password": "nope-nope-1"})
    signed_in(app, VIEWER)
    admin = signed_in(app, ADMIN)
    log = admin.get("/api/admin/access-log", params={"limit": 50}).json()["items"]
    actions = {r["action"] for r in log}
    assert {"login", "login_failed"} <= actions
