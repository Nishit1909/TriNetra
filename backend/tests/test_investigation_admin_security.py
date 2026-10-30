"""Three views (viewer / investigator / admin), access log, alerts, SMTP and conflict-of-interest checks."""
import os
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

pytestmark = pytest.mark.skipif(not os.getenv("INV_TEST_DSN"), reason="needs disposable INV_TEST_DSN")

ADMIN, INV1, INV2, VIEWER, COI = (f"00000000-0000-4000-a000-00000000000{i}" for i in range(1, 6))


@pytest.fixture
def client(monkeypatch):
    from app import config, audit
    import app.main as main
    monkeypatch.setattr(config.settings, "supabase_database_url", os.environ["INV_TEST_DSN"])
    monkeypatch.setattr(config.settings, "auth_enabled", False)
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "db"))
    import seed_demo_security
    seed_demo_security.main(["--dsn", os.environ["INV_TEST_DSN"]])
    with psycopg.connect(os.environ["INV_TEST_DSN"]) as conn:
        conn.execute("DELETE FROM inv.security_alerts")
        conn.execute("DELETE FROM inv.admin_settings")
    audit._COI_CHECKED.clear()
    # Fixed working hours covering the whole day so time-of-day doesn't make tests flaky.
    monkeypatch.setattr(audit, "DEFAULT_RULES", {**audit.DEFAULT_RULES, "work_hours": [0, 24], "flag_weekends": False})
    with TestClient(main.app) as c:
        yield c


def as_(user):
    return {"X-Demo-User": user}


def db():
    return psycopg.connect(os.environ["INV_TEST_DSN"], row_factory=dict_row)


def wait_for(fn, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    return fn()


def test_three_views_and_case_permissions(client):
    me = {u: client.get("/api/auth/me", headers=as_(u)).json() for u in (ADMIN, INV1, VIEWER)}
    assert [me[u]["view"] for u in (ADMIN, INV1, VIEWER)] == ["admin", "investigator", "viewer"]
    assert {c["case_id"] for c in me[VIEWER]["cases"]} == {"CASE_VAST_GASTECH", "CASE_CAVIAR"}
    assert all(c["access_level"] == "viewer" for c in me[VIEWER]["cases"])

    # viewer: can read assigned case, cannot edit, cannot open unassigned case or admin portal
    assert client.get("/api/cases/CASE_VAST_GASTECH/summary", headers=as_(VIEWER)).status_code == 200
    assert client.post("/api/cases/CASE_VAST_GASTECH/analysis", json={"mode": "observed_only"}, headers=as_(VIEWER)).status_code == 403
    assert client.get("/api/cases/CASE_NOORDIN/summary", headers=as_(VIEWER)).status_code == 403
    assert client.get("/api/admin/users", headers=as_(VIEWER)).status_code == 403
    # investigator: edits where editor, read-only where viewer
    assert client.post("/api/cases/CASE_CAVIAR/analysis", json={"mode": "observed_only"}, headers=as_(INV2)).json()["run"]["status"] == "completed"
    assert client.post("/api/cases/CASE_VAST_GASTECH/analysis", json={"mode": "observed_only"}, headers=as_(INV2)).status_code == 403
    assert client.get("/api/admin/alerts", headers=as_(INV1)).status_code == 403
    # admin: everything
    assert client.get("/api/cases/CASE_NOORDIN/summary", headers=as_(ADMIN)).status_code == 200
    assert client.get("/api/admin/users", headers=as_(ADMIN)).status_code == 200
    # unknown demo user
    assert client.get("/api/cases", headers=as_("00000000-0000-4000-a000-0000000000ff")).status_code == 401


def test_access_log_alerts_and_summary(client):
    client.get("/api/cases/CASE_VAST_GASTECH/persons/P0001", headers=as_(VIEWER))
    client.get("/api/cases/CASE_NOORDIN/summary", headers=as_(VIEWER))           # denied
    log = client.get("/api/admin/access-log", params={"user_id": VIEWER}, headers=as_(ADMIN)).json()
    actions = {(r["action"], r["allowed"], r["case_id"]) for r in log["items"]}
    assert ("view_person", True, "CASE_VAST_GASTECH") in actions
    assert ("view_case", False, "CASE_NOORDIN") in actions or any(not r["allowed"] and r["case_id"] == "CASE_NOORDIN" for r in log["items"])
    row = next(r for r in log["items"] if r["action"] == "view_person")
    assert row["person_id"] == "P0001" and row["user_label"] == "demo.viewer@sih26189.demo" and row["role"] == "viewer"

    alerts = client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"]
    denied = [a for a in alerts if a["rule"] == "denied_access" and a["case_id"] == "CASE_NOORDIN"]
    assert denied and denied[0]["severity"] == "high"
    assert wait_for(lambda: client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"][0]["email_status"] != "not_sent")
    # repeated denial in the same hour doesn't spam
    client.get("/api/cases/CASE_NOORDIN/summary", headers=as_(VIEWER))
    assert len([a for a in client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"]
                if a["rule"] == "denied_access" and a["case_id"] == "CASE_NOORDIN"]) == 1

    r = client.post(f"/api/admin/alerts/{denied[0]['alert_id']}/review", json={"status": "acknowledged", "note": "checked"}, headers=as_(ADMIN))
    assert r.json()["status"] == "acknowledged" and r.json()["reviewed_by"] == "demo.admin@sih26189.demo"

    summary = client.get("/api/admin/access-summary", headers=as_(ADMIN)).json()
    viewer = next(u for u in summary["users"] if u["user_label"] == "demo.viewer@sih26189.demo")
    assert viewer["denied"] >= 1 and viewer["persons_viewed"] >= 1

    with db() as conn:   # access log is append-only
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("DELETE FROM inv.access_log")


def test_conflict_of_interest_and_bulk_viewing(client, monkeypatch):
    client.get("/api/cases/CASE_VAST_GASTECH/summary", headers=as_(COI))
    coi = [a for a in client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"] if a["rule"] == "conflict_of_interest"]
    assert coi and coi[0]["detail"]["matches"][0]["matched_on"] == "name"
    check = client.get("/api/admin/conflicts", headers=as_(ADMIN)).json()
    assert any(c["case_id"] == "CASE_VAST_GASTECH" and c["user"] == "Kanon Herrero" for c in check["conflicts"])
    assert not any(c["user"].startswith("Demo Insp") for c in check["conflicts"])

    client.post("/api/admin/settings/alert-rules", json={"work_hours": [0, 24], "flag_weekends": False,
                "bulk_window_minutes": 10, "bulk_person_views": 3}, headers=as_(ADMIN))
    for pid in ("P0001", "P0002", "P0003", "P0004"):
        client.get(f"/api/cases/CASE_VAST_GASTECH/persons/{pid}", headers=as_(INV1))
    allalerts = client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"]
    bulk = [a for a in allalerts if a["rule"] == "bulk_viewing"]
    assert bulk and bulk[0]["user_label"] == "demo.investigator1@sih26189.demo"


def test_after_hours_rule(client):
    client.post("/api/admin/settings/alert-rules", json={"work_hours": [0, 1], "flag_weekends": True}, headers=as_(ADMIN))
    client.get("/api/cases/CASE_CAVIAR/summary", headers=as_(INV2))
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    alerts = [a for a in client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"] if a["rule"] == "after_hours"]
    assert bool(alerts) == (now.hour >= 1 or now.weekday() >= 5)


def test_smtp_settings_and_email(client, monkeypatch):
    from app import audit
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            self.host = host
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def starttls(self, context=None):
            pass
        def login(self, u, p):
            pass
        def send_message(self, msg):
            sent.append(msg)
    monkeypatch.setattr(audit.smtplib, "SMTP", FakeSMTP)

    bad = client.post("/api/admin/settings/smtp", json={"enabled": True, "host": ""}, headers=as_(ADMIN))
    assert bad.status_code == 422
    ok = client.post("/api/admin/settings/smtp", json={"enabled": True, "host": "smtp.example.org", "port": 587,
                     "username": "alerts", "from_address": "alerts@example.org", "to_addresses": ["admin@example.org"],
                     "min_severity": "medium"}, headers=as_(ADMIN)).json()
    assert ok["smtp"]["enabled"] and "password" not in ok["smtp"] and "password_configured" in ok["smtp"]
    assert client.get("/api/admin/settings", headers=as_(INV1)).status_code == 403
    assert client.post("/api/admin/settings/smtp/test", headers=as_(ADMIN)).json()["sent"] is True

    client.get("/api/cases/CASE_NOORDIN/summary", headers=as_(INV2))      # denied → high alert → e-mail
    assert wait_for(lambda: any("HIGH alert" in m["Subject"] for m in sent))
    alert = wait_for(lambda: next((a for a in client.get("/api/admin/alerts", headers=as_(ADMIN)).json()["items"]
                                   if a["rule"] == "denied_access" and a["email_status"] == "sent"), None))
    assert alert is not None
