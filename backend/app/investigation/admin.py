"""Admin portal: users and case access, access log, alerts, alert rules, SMTP settings, conflict checks.

Admin role only. Updates use POST so the existing CORS policy (GET/POST) covers them.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

from app import audit
from app.security import get_principal
from .common import connect, json_safe, require_case

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(principal=Depends(get_principal)):
    if not principal.is_admin:
        raise HTTPException(403, "Administrator role required.")
    return principal


def _actor(p):
    return "local developer" if p.local else (p.label or p.user_id)


# ------------------------------------------------------------------ users and case access
class UserIn(BaseModel):
    email: str = Field(pattern=EMAIL, max_length=200)
    display_name: str = Field(min_length=2, max_length=120)
    role: Literal["viewer", "investigator", "admin"]
    phone: str | None = Field(default=None, max_length=30)
    badge_number: str | None = Field(default=None, max_length=30)
    is_demo: bool = False
    user_id: UUID | None = None     # Supabase Auth user id when linking a real login
    password: str | None = Field(default=None, max_length=200)   # initial password for password login


class UserUpdate(BaseModel):
    role: Literal["viewer", "investigator", "admin"] | None = None
    active: bool | None = None


class MemberIn(BaseModel):
    user_id: UUID
    case_id: str
    access_level: Literal["viewer", "editor"]


@router.get("/users")
def list_users(p=Depends(require_admin)):
    with connect() as conn:
        users = conn.execute("""SELECT u.*,
              (SELECT max(at) FROM inv.access_log l WHERE l.user_id=u.user_id) last_access,
              (SELECT count(*) FROM inv.access_log l WHERE l.user_id=u.user_id AND l.at > now()-interval '24 hours') requests_24h,
              (SELECT count(*) FROM inv.security_alerts a WHERE a.user_id=u.user_id AND a.status='open') open_alerts
            FROM inv.app_users u ORDER BY u.role DESC, u.display_name""").fetchall()
        members = conn.execute("SELECT user_id,case_id,access_level FROM inv.case_members ORDER BY case_id").fetchall()
    by_user = {}
    for m in members:
        by_user.setdefault(m["user_id"], []).append({"case_id": m["case_id"], "access_level": m["access_level"]})
    for u in users:
        u["cases"] = "all (admin)" if u["role"] == "admin" else by_user.get(u["user_id"], [])
    return json_safe([_public(u) for u in users])


@router.post("/users")
def create_user(body: UserIn, p=Depends(require_admin)):
    from app.auth import hash_password, password_problems
    pw_hash = None
    if body.password:
        problems = password_problems(body.password)
        if problems:
            raise HTTPException(422, "Password needs " + " and ".join(problems) + ".")
        pw_hash = hash_password(body.password)
    with connect() as conn:
        try:
            row = conn.execute("""INSERT INTO inv.app_users (user_id,email,display_name,role,phone,badge_number,is_demo,password_hash,password_changed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (body.user_id or uuid4(), body.email.lower(), body.display_name, body.role, body.phone, body.badge_number, body.is_demo,
                 pw_hash, datetime.now(timezone.utc) if pw_hash else None)).fetchone()
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(409, "A user with this e-mail or id already exists.")
            raise
    return json_safe(_public(row))


@router.post("/users/{user_id}")
def update_user(user_id: UUID, body: UserUpdate, p=Depends(require_admin)):
    sets, vals = [], []
    if body.role is not None:
        sets.append("role=%s"); vals.append(body.role)
    if body.active is not None:
        sets.append("active=%s"); vals.append(body.active)
    if not sets:
        raise HTTPException(422, "Nothing to update.")
    with connect() as conn:
        row = conn.execute(f"UPDATE inv.app_users SET {','.join(sets)} WHERE user_id=%s RETURNING *", (*vals, user_id)).fetchone()
        if row is not None and (body.active is False or body.role is not None):
            from app.auth import revoke_user_sessions
            revoke_user_sessions(conn, user_id)   # role change or deactivation takes effect immediately
    if row is None:
        raise HTTPException(404, "User not found.")
    return json_safe(_public(row))


class PasswordResetIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)


@router.post("/users/{user_id}/password")
def reset_password(user_id: UUID, body: PasswordResetIn, p=Depends(require_admin)):
    """Admin sets a new password; the user's existing sessions are ended."""
    from app.auth import hash_password, password_problems, revoke_user_sessions
    problems = password_problems(body.password)
    if problems:
        raise HTTPException(422, "Password needs " + " and ".join(problems) + ".")
    with connect() as conn:
        row = conn.execute("UPDATE inv.app_users SET password_hash=%s, password_changed_at=now() WHERE user_id=%s RETURNING user_id",
                           (hash_password(body.password), user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "User not found.")
        ended = revoke_user_sessions(conn, user_id)
    return {"password_reset": True, "sessions_ended": ended}


@router.get("/sessions")
def list_sessions(p=Depends(require_admin)):
    """Active sign-in sessions: who is signed in, since when, from where."""
    with connect() as conn:
        rows = conn.execute("""SELECT s.session_id,s.user_id,u.email,u.display_name,u.role,s.created_at,s.last_seen_at,s.expires_at,
                s.client_ip,s.user_agent FROM inv.auth_sessions s JOIN inv.app_users u USING (user_id)
            WHERE s.revoked_at IS NULL AND s.expires_at > now() ORDER BY s.last_seen_at DESC""").fetchall()
    return json_safe(rows)


@router.post("/sessions/{session_id}/revoke")
def revoke_session(session_id: int, p=Depends(require_admin)):
    with connect() as conn:
        n = conn.execute("UPDATE inv.auth_sessions SET revoked_at=now() WHERE session_id=%s AND revoked_at IS NULL", (session_id,)).rowcount
    if not n:
        raise HTTPException(404, "Active session not found.")
    return {"revoked": True}


def _public(row):
    """Never return password hashes."""
    row = dict(row)
    row["has_password"] = bool(row.pop("password_hash", None))
    return row


@router.post("/case-members")
def set_case_member(body: MemberIn, p=Depends(require_admin)):
    with connect() as conn:
        require_case(body.case_id, conn)
        if conn.execute("SELECT 1 FROM inv.app_users WHERE user_id=%s", (body.user_id,)).fetchone() is None:
            raise HTTPException(404, "User not found.")
        row = conn.execute("""INSERT INTO inv.case_members (case_id,user_id,access_level) VALUES (%s,%s,%s)
            ON CONFLICT (case_id,user_id) DO UPDATE SET access_level=EXCLUDED.access_level RETURNING *""",
            (body.case_id, body.user_id, body.access_level)).fetchone()
    return json_safe(row)


@router.post("/case-members/remove")
def remove_case_member(body: MemberIn, p=Depends(require_admin)):
    with connect() as conn:
        n = conn.execute("DELETE FROM inv.case_members WHERE case_id=%s AND user_id=%s", (body.case_id, body.user_id)).rowcount
    if not n:
        raise HTTPException(404, "Membership not found.")
    return {"removed": True}


# ------------------------------------------------------------------ access log
@router.get("/access-log")
def access_log(user_id: UUID | None = None, case_id: str | None = None, action: str | None = None,
               allowed: bool | None = None, since: datetime | None = None, until: datetime | None = None,
               limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0), p=Depends(require_admin)):
    where, vals = [], []
    for col, v in (("user_id", user_id), ("case_id", case_id), ("action", action), ("allowed", allowed)):
        if v is not None:
            where.append(f"{col}=%s"); vals.append(v)
    if since:
        where.append("at>=%s"); vals.append(since)
    if until:
        where.append("at<%s"); vals.append(until)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        total = conn.execute(f"SELECT count(*) n FROM inv.access_log {w}", vals).fetchone()["n"]
        rows = conn.execute(f"SELECT * FROM inv.access_log {w} ORDER BY at DESC, log_id DESC LIMIT %s OFFSET %s", (*vals, limit, offset)).fetchall()
    return json_safe({"items": rows, "total": total, "limit": limit, "offset": offset})


@router.get("/access-summary")
def access_summary(hours: int = Query(24, ge=1, le=720), p=Depends(require_admin)):
    """Who used the system, when, and what they touched, over the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    with connect() as conn:
        per_user = conn.execute("""SELECT user_id,user_label,max(role) role,count(*) requests,
              count(*) FILTER (WHERE NOT allowed) denied, min(at) first_access, max(at) last_access,
              array_agg(DISTINCT case_id) FILTER (WHERE case_id IS NOT NULL) cases,
              count(DISTINCT person_id) FILTER (WHERE action='view_person') persons_viewed
            FROM inv.access_log WHERE at>=%s GROUP BY user_id,user_label ORDER BY max(at) DESC""", (since,)).fetchall()
        per_case = conn.execute("""SELECT case_id,count(*) requests,count(DISTINCT user_label) users,max(at) last_access
            FROM inv.access_log WHERE at>=%s AND case_id IS NOT NULL GROUP BY case_id ORDER BY requests DESC""", (since,)).fetchall()
        alerts = conn.execute("""SELECT severity,count(*) n FROM inv.security_alerts WHERE status='open' GROUP BY severity""").fetchall()
    return json_safe({"since": since, "users": per_user, "cases": per_case,
                      "open_alerts": {r["severity"]: r["n"] for r in alerts}})


# ------------------------------------------------------------------ alerts
class AlertReview(BaseModel):
    status: Literal["acknowledged", "dismissed"]
    note: str = Field(default="", max_length=1000)


@router.get("/alerts")
def list_alerts(status: Literal["open", "acknowledged", "dismissed", "all"] | None = "open",
                severity: Literal["low", "medium", "high"] | None = None, rule: str | None = None,
                limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), p=Depends(require_admin)):
    where, vals = [], []
    for col, v in (("status", None if status == "all" else status), ("severity", severity), ("rule", rule)):
        if v is not None:
            where.append(f"{col}=%s"); vals.append(v)
    w = ("WHERE " + " AND ".join(where)) if where else ""
    with connect() as conn:
        total = conn.execute(f"SELECT count(*) n FROM inv.security_alerts {w}", vals).fetchone()["n"]
        rows = conn.execute(f"""SELECT * FROM inv.security_alerts {w}
            ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, at DESC LIMIT %s OFFSET %s""",
            (*vals, limit, offset)).fetchall()
    return json_safe({"items": rows, "total": total, "limit": limit, "offset": offset,
                      "note": "Alerts are flags for an administrator to review, not findings about a person."})


@router.post("/alerts/{alert_id}/review")
def review_alert(alert_id: int, body: AlertReview, p=Depends(require_admin)):
    with connect() as conn:
        row = conn.execute("""UPDATE inv.security_alerts SET status=%s,review_note=%s,reviewed_by=%s,reviewed_at=now()
            WHERE alert_id=%s RETURNING *""", (body.status, body.note, _actor(p), alert_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Alert not found.")
    return json_safe(row)


# ------------------------------------------------------------------ conflict of interest
@router.get("/conflicts")
def conflicts(raise_alerts: bool = False, p=Depends(require_admin)):
    """Check every non-admin user against the cases they can open: name or e-mail matching a case subject."""
    out = []
    with connect() as conn:
        users = conn.execute("SELECT * FROM inv.app_users WHERE active AND role<>'admin'").fetchall()
        for u in users:
            cases = [r["case_id"] for r in conn.execute("SELECT case_id FROM inv.case_members WHERE user_id=%s", (u["user_id"],)).fetchall()]
            for cid in cases:
                matches = audit.conflict_matches(conn, u, cid)
                if matches:
                    out.append({"user_id": u["user_id"], "user": u["display_name"], "email": u["email"], "is_demo": u["is_demo"],
                                "case_id": cid, "matches": matches})
                    if raise_alerts:
                        from app.security import Principal
                        audit.raise_alert(conn, "conflict_of_interest", "high",
                                          Principal(str(u["user_id"]), role=u["role"], label=u["email"]),
                                          f"Possible conflict of interest in {cid}", cid,
                                          {"matches": matches, "found_by": "admin check"}, dedupe_key=f"coi:{u['user_id']}:{cid}")
    return json_safe({"conflicts": out, "checked_users": len(users),
                      "rule": "Exact match of the user's name or e-mail with a subject or communication address in a case they can open."})


# ------------------------------------------------------------------ settings: alert rules and SMTP
class RulesIn(BaseModel):
    timezone: str = "Asia/Kolkata"
    work_hours: list[int] = Field(default=[8, 20], min_length=2, max_length=2)
    flag_weekends: bool = True
    bulk_window_minutes: int = Field(default=10, ge=1, le=240)
    bulk_person_views: int = Field(default=40, ge=2, le=10000)
    sensitive_actions: list[Literal["upload", "dismiss_lead", "export", "run_analysis", "review_lead"]] = ["upload", "dismiss_lead", "export"]
    notify_logins: bool = True


class SmtpIn(BaseModel):
    enabled: bool = False
    host: str = Field(default="", max_length=200)
    port: int = Field(default=587, ge=1, le=65535)
    username: str = Field(default="", max_length=200)
    from_address: str = Field(default="", pattern=r"^$|" + EMAIL[1:], max_length=200)
    to_addresses: list[str] = Field(default_factory=list, max_length=20)
    use_starttls: bool = True
    use_ssl: bool = False
    min_severity: Literal["low", "medium", "high"] = "medium"


@router.get("/settings")
def get_settings(p=Depends(require_admin)):
    import os
    with connect() as conn:
        smtp = audit.get_setting(conn, "smtp", audit.DEFAULT_SMTP)
        rules = audit.get_setting(conn, "alert_rules", audit.DEFAULT_RULES)
    smtp["password_configured"] = bool(os.getenv("SMTP_PASSWORD"))
    smtp["password_source"] = "SMTP_PASSWORD environment variable (never stored in the database)"
    return json_safe({"smtp": smtp, "alert_rules": rules})


@router.post("/settings/alert-rules")
def set_rules(body: RulesIn, p=Depends(require_admin)):
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo(body.timezone)
    except Exception:
        raise HTTPException(422, "Unknown timezone.")
    if not (0 <= body.work_hours[0] < body.work_hours[1] <= 24):
        raise HTTPException(422, "work_hours must be [start, end] with 0 <= start < end <= 24.")
    with connect() as conn:
        audit.put_setting(conn, "alert_rules", body.model_dump(), _actor(p))
    return get_settings(p)


@router.post("/settings/smtp")
def set_smtp(body: SmtpIn, p=Depends(require_admin)):
    import re
    if any(not re.match(EMAIL, a) for a in body.to_addresses):
        raise HTTPException(422, "Every recipient must be an e-mail address.")
    if body.enabled and (not body.host or not body.from_address or not body.to_addresses):
        raise HTTPException(422, "To enable e-mail, set host, from address and at least one recipient.")
    with connect() as conn:
        audit.put_setting(conn, "smtp", body.model_dump(), _actor(p))
    return get_settings(p)


@router.post("/settings/smtp/test")
def test_smtp(p=Depends(require_admin)):
    with connect() as conn:
        smtp = audit.get_setting(conn, "smtp", audit.DEFAULT_SMTP)
    try:
        audit.send_email(smtp, "[SIH26189] Test e-mail from the admin portal",
                         f"SMTP is working. Sent by {_actor(p)} at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.")
    except Exception as exc:
        return {"sent": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    return {"sent": True, "to": smtp["to_addresses"]}
