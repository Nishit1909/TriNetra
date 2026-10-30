"""Password login with server-side sessions.

- Passwords: scrypt (memory-hard), per-user random salt, constant-time comparison.
- Sessions: random 256-bit token in an HttpOnly, SameSite=Strict cookie; only its SHA-256 is stored.
  Sessions expire (8 h) and are revoked on logout, password change and account deactivation.
- Brute force: 5 failures per e-mail or 30 per IP in 15 minutes locks further attempts for that window.
  Repeated failures raise admin alerts. Error messages never reveal whether an e-mail exists.
- CSRF: cookie-authenticated writes must carry the X-TRACE-CSRF header, which a cross-site form
  cannot send and a cross-origin script cannot send without passing CORS.
"""
import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.config import settings
from app.investigation.common import connect

router = APIRouter(prefix="/api/auth", tags=["authentication"])

SESSION_COOKIE = "trace_session"
CSRF_HEADER = "X-TRACE-CSRF"
SESSION_HOURS = 8
WINDOW_MINUTES = 15
MAX_FAILS_PER_EMAIL = 5
MAX_FAILS_PER_IP = 30
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt, digest = (stored or "").split("$")
        if algo != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# A real hash so unknown e-mails take as long to reject as wrong passwords (no user enumeration by timing).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("at least 10 characters")
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        problems.append("letters and numbers")
    if len(password) > 200:
        problems.append("at most 200 characters")
    return problems


# ------------------------------------------------------------------ sessions
def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def session_user(token: str | None):
    """The active user for a session cookie, or None. Inactive accounts and expired sessions are rejected."""
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            """SELECT u.*, s.session_id FROM inv.auth_sessions s JOIN inv.app_users u USING (user_id)
               WHERE s.token_sha256=%s AND s.revoked_at IS NULL AND s.expires_at > now() AND u.active""",
            (_token_hash(token),),
        ).fetchone()
        if row:
            conn.execute("UPDATE inv.auth_sessions SET last_seen_at=now() WHERE session_id=%s", (row["session_id"],))
    return row


def revoke_user_sessions(conn, user_id) -> int:
    return conn.execute(
        "UPDATE inv.auth_sessions SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL", (user_id,)
    ).rowcount


def _set_cookie(response: Response, token: str, expires: datetime):
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="strict",
        secure=settings.app_env.lower() == "production",
        path="/",
        expires=expires,
    )


# ------------------------------------------------------------------ endpoints
class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


def _client_ip(request: Request):
    return request.client.host if request.client else None


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    from app import audit
    from app.security import Principal

    email = body.email.strip().lower()
    ip = _client_ip(request)
    request.state.audit_action = "login_failed"
    since = datetime.now(timezone.utc) - timedelta(minutes=WINDOW_MINUTES)
    failure = None  # (status, message), raised only after the attempt is committed
    with connect() as conn:
        fails_email = conn.execute(
            "SELECT count(*) n FROM inv.login_attempts WHERE email=%s AND NOT success AND at>=%s", (email, since)
        ).fetchone()["n"]
        fails_ip = conn.execute(
            "SELECT count(*) n FROM inv.login_attempts WHERE client_ip IS NOT DISTINCT FROM %s AND NOT success AND at>=%s", (ip, since)
        ).fetchone()["n"]
        user = None
        if fails_email >= MAX_FAILS_PER_EMAIL or fails_ip >= MAX_FAILS_PER_IP:
            conn.execute("INSERT INTO inv.login_attempts (email,client_ip,success,reason) VALUES (%s,%s,false,'locked')", (email, ip))
            failure = (429, f"Too many failed sign-in attempts. Try again in {WINDOW_MINUTES} minutes.")
        else:
            user = conn.execute("SELECT * FROM inv.app_users WHERE lower(email)=%s", (email,)).fetchone()
            ok = verify_password(body.password, user["password_hash"] if user and user["password_hash"] else _DUMMY_HASH)
            if not (user and ok and user["active"] and user["password_hash"]):
                reason = "inactive" if user and ok and not user["active"] else "bad_credentials"
                conn.execute("INSERT INTO inv.login_attempts (email,client_ip,success,reason) VALUES (%s,%s,false,%s)", (email, ip, reason))
                total = fails_email + 1
                if total in (3, MAX_FAILS_PER_EMAIL):
                    who = Principal(str(user["user_id"]), role=user["role"], label=user["email"]) if user else None
                    audit.raise_alert(
                        conn, "failed_login", "high" if total >= MAX_FAILS_PER_EMAIL else "medium", who,
                        f"{total} failed sign-in attempts for {email}", None,
                        {"email": email, "client_ip": ip, "window_minutes": WINDOW_MINUTES, "locked": total >= MAX_FAILS_PER_EMAIL},
                        dedupe_key=f"failedlogin:{email}:{total}:{datetime.now(timezone.utc):%Y%m%d%H}",
                    )
                failure = (401, "Email or password is incorrect.")
            else:
                token = secrets.token_urlsafe(32)
                expires = datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)
                conn.execute(
                    """INSERT INTO inv.auth_sessions (token_sha256,user_id,expires_at,client_ip,user_agent)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (_token_hash(token), user["user_id"], expires, ip, (request.headers.get("user-agent") or "")[:300]),
                )
                conn.execute("UPDATE inv.app_users SET last_login_at=now() WHERE user_id=%s", (user["user_id"],))
                conn.execute("INSERT INTO inv.login_attempts (email,client_ip,success) VALUES (%s,%s,true)", (email, ip))
    if failure:
        raise HTTPException(*failure)

    # Tell the administrator who signed in (alert in the portal + e-mail when SMTP is on).
    try:
        with connect() as conn:
            rules = audit.get_setting(conn, "alert_rules", audit.DEFAULT_RULES)
            if rules.get("notify_logins", True):
                who = Principal(str(user["user_id"]), role=user["role"], label=user["email"], is_demo=user["is_demo"])
                audit.raise_alert(
                    conn, "user_login", "low", who,
                    f"{user['display_name']} signed in ({user['role']})", None,
                    {"email": user["email"], "role": user["role"], "client_ip": ip,
                     "user_agent": (request.headers.get("user-agent") or "")[:160],
                     "at": datetime.now(timezone.utc).isoformat()},
                )
    except Exception:
        pass   # a notification problem must never block sign-in

    request.state.audit_action = "login"
    request.state.principal = Principal(
        str(user["user_id"]), is_admin=user["role"] == "admin", role=user["role"], label=user["email"], is_demo=user["is_demo"]
    )
    _set_cookie(response, token, expires)
    return {"signed_in": True, "expires_at": expires.isoformat(), "role": user["role"], "label": user["email"],
            "display_name": user["display_name"]}


@router.post("/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    request.state.audit_action = "logout"
    if token:
        with connect() as conn:
            conn.execute("UPDATE inv.auth_sessions SET revoked_at=now() WHERE token_sha256=%s AND revoked_at IS NULL", (_token_hash(token),))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"signed_out": True}


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request, response: Response):
    """Signed-in users change their own password; every session (including this one) is ended."""
    user = session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "Sign in required.")
    if request.headers.get(CSRF_HEADER) != "1":
        raise HTTPException(403, "Missing CSRF header.")
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(401, "Current password is incorrect.")
    problems = password_problems(body.new_password)
    if problems:
        raise HTTPException(422, "New password needs " + " and ".join(problems) + ".")
    with connect() as conn:
        conn.execute("UPDATE inv.app_users SET password_hash=%s, password_changed_at=now() WHERE user_id=%s",
                     (hash_password(body.new_password), user["user_id"]))
        revoke_user_sessions(conn, user["user_id"])
    response.delete_cookie(SESSION_COOKIE, path="/")
    request.state.audit_action = "password_change"
    return {"changed": True, "signed_out": True}
