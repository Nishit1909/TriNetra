"""Access logging, alert rules and admin e-mail notifications.

Every API request is written to inv.access_log (append-only). Alert rules run on each logged request
and raise security_alerts for the admin portal. Alerts at or above the configured severity are
e-mailed when SMTP is enabled in the admin portal; the SMTP password only comes from SMTP_PASSWORD.

Alerts are flags for an administrator to review. They are not judgements about a person.
"""
from datetime import datetime, timedelta
from email.message import EmailMessage
import logging
import os
import re
import smtplib
import ssl
import threading
import time
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.investigation.common import connect, json_safe

logger = logging.getLogger(__name__)
SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}
SKIP_PREFIXES = ("/health", "/docs", "/redoc", "/openapi.json", "/favicon")

DEFAULT_RULES = {
    "timezone": "Asia/Kolkata",
    "work_hours": [8, 20],               # local hours; outside = after hours
    "flag_weekends": True,
    "bulk_window_minutes": 10,
    "bulk_person_views": 40,             # distinct person profiles in the window
    "sensitive_actions": ["upload", "dismiss_lead", "export"],
    "notify_logins": True,               # every successful sign-in raises a 'user_login' alert and is e-mailed
}
DEFAULT_SMTP = {
    "enabled": False, "host": "", "port": 587, "username": "", "from_address": "",
    "to_addresses": [], "use_starttls": True, "use_ssl": False, "min_severity": "medium",
}

_COI_CHECKED = {}
_CASE_RE = re.compile(r"^/api/cases/([^/]+)(/.*)?$")


def classify(method, path, query=""):
    """Map a request to (action, case_id, person_id) for the log."""
    case_id = person_id = None
    action = "api"
    m = _CASE_RE.match(path)
    if path.startswith("/api/admin"):
        action = "admin"
    elif path.startswith("/api/case-uploads"):
        action = "upload" if method == "POST" and not path.endswith(("/validate", "/template")) else "upload_check"
    elif path == "/api/cases":
        action = "list_cases"
    elif m:
        case_id, rest = m.group(1), (m.group(2) or "")
        parts = [p for p in rest.split("/") if p]
        if not parts:
            action = "view_case"
        elif parts[0] == "persons" and len(parts) >= 2:
            person_id = parts[1]
            action = {"timeline": "view_timeline", "explain": "view_explanation"}.get(parts[2] if len(parts) > 2 else "", "view_person")
        elif parts[0] == "persons":
            action = "search_persons"
        elif parts[0] == "relationships" and len(parts) == 3:
            action = "view_pair_evidence"
        elif parts[0] == "analysis" and method == "POST":
            action = "run_analysis"
        elif parts[0] == "predicted_links" and method == "POST":
            action = "review_lead"
        elif parts[0] == "document_mentions" and method == "POST":
            action = "review_mention"
        else:
            action = "view_" + parts[0].replace("-", "_")
    return action, case_id, person_id


# ------------------------------------------------------------------ settings
def get_setting(conn, key, default):
    row = conn.execute("SELECT value FROM inv.admin_settings WHERE key=%s", (key,)).fetchone()
    value = dict(default)
    if row:
        value.update(row["value"])
    return value


def put_setting(conn, key, value, actor):
    conn.execute("""INSERT INTO inv.admin_settings (key,value,updated_by) VALUES (%s,%s,%s)
                    ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now(), updated_by=EXCLUDED.updated_by""",
                 (key, Jsonb(value), actor))


# ------------------------------------------------------------------ e-mail
def send_email(smtp, subject, body):
    """Send one e-mail with the configured SMTP settings. Raises on failure."""
    password = os.getenv("SMTP_PASSWORD", "")
    if not smtp.get("host") or not smtp.get("from_address") or not smtp.get("to_addresses"):
        raise ValueError("SMTP host, from address and at least one recipient are required.")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, smtp["from_address"], ", ".join(smtp["to_addresses"])
    msg.set_content(body)
    port = int(smtp.get("port") or 587)
    if smtp.get("use_ssl"):
        server = smtplib.SMTP_SSL(smtp["host"], port, timeout=15, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(smtp["host"], port, timeout=15)
    with server:
        if smtp.get("use_starttls") and not smtp.get("use_ssl"):
            server.starttls(context=ssl.create_default_context())
        if smtp.get("username"):
            server.login(smtp["username"], password)
        server.send_message(msg)


def _email_alert(alert_id):
    try:
        with connect() as conn:
            alert = None
            for _ in range(25):   # the alert is committed by the caller's transaction; wait for it to be visible
                alert = conn.execute("SELECT * FROM inv.security_alerts WHERE alert_id=%s", (alert_id,)).fetchone()
                if alert:
                    break
                conn.commit()
                time.sleep(0.2)
            if alert is None:
                return
            smtp = get_setting(conn, "smtp", DEFAULT_SMTP)
            rules = get_setting(conn, "alert_rules", DEFAULT_RULES)
        # Sign-in notices are e-mailed whenever login notifications are on, regardless of the severity threshold.
        login_notice = alert["rule"] == "user_login" and rules.get("notify_logins", True)
        if not smtp["enabled"]:
            status, error = "disabled", None
        elif not login_notice and SEVERITY_ORDER[alert["severity"]] < SEVERITY_ORDER.get(smtp["min_severity"], 1):
            status, error = "below_threshold", None
        else:
            body = (f"Security alert ({alert['severity']}): {alert['title']}\n\n"
                    f"User: {alert['user_label']}\nCase: {alert['case_id'] or '-'}\nTime: {alert['at']}\n"
                    f"Rule: {alert['rule']}\nDetails: {json_safe(alert['detail'])}\n\n"
                    "Review it in the admin portal. Alerts are flags for review, not findings about a person.")
            try:
                send_email(smtp, f"[SIH26189] {alert['severity'].upper()} alert: {alert['title']}", body)
                status, error = "sent", None
            except Exception as exc:
                status, error = "failed", f"{type(exc).__name__}: {str(exc)[:200]}"
        with connect() as conn:
            conn.execute("UPDATE inv.security_alerts SET email_status=%s,email_error=%s WHERE alert_id=%s", (status, error, alert_id))
    except Exception:
        logger.exception("Alert e-mail step failed for alert %s", alert_id)


def raise_alert(conn, rule, severity, principal, title, case_id=None, detail=None, dedupe_key=None, notify=True):
    row = conn.execute("""INSERT INTO inv.security_alerts (rule,severity,user_id,user_label,case_id,title,detail,dedupe_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING RETURNING alert_id""",
        (rule, severity, _uuid_or_none(principal), _label(principal), case_id, title, Jsonb(json_safe(detail or {})), dedupe_key)).fetchone()
    if row and notify:
        threading.Thread(target=_email_alert, args=(row["alert_id"],), daemon=True).start()
    return row["alert_id"] if row else None


# ------------------------------------------------------------------ conflict of interest
def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def conflict_matches(conn, user, case_id):
    """Case subjects that share the investigator's name, e-mail or phone. Exact normalised matches only."""
    if user is None:
        return []
    name, email = _norm(user["display_name"]), (user["email"] or "").lower()
    found = []
    people = conn.execute("SELECT person_id,display_name FROM inv.persons WHERE case_id=%s", (case_id,)).fetchall()
    for p in people:
        if name and _norm(p["display_name"]) == name:
            found.append({"person_id": p["person_id"], "display_name": p["display_name"], "matched_on": "name"})
    if email:
        rows = conn.execute("""SELECT DISTINCT source_person_id person_id FROM inv.communication_events
            WHERE case_id=%s AND (lower(sender_address)=%s OR lower(recipient_address)=%s) LIMIT 5""", (case_id, email, email)).fetchall()
        found += [{"person_id": r["person_id"], "matched_on": "email address in case communications"} for r in rows]
    return found


# ------------------------------------------------------------------ logging + rules
def _uuid_or_none(principal):
    if principal is None or principal.local:
        return None
    try:
        from uuid import UUID
        return UUID(principal.user_id)
    except (ValueError, AttributeError):
        return None


def _label(principal):
    if principal is None:
        return "anonymous"
    return "local developer" if principal.local else (principal.label or principal.user_id)


def record_request(method, path, query, status_code, principal, client_ip, user_agent, request_id, duration_ms, action_override=None):
    """Write the access-log row and evaluate alert rules. Never raises into the request."""
    if not path.startswith("/api/") or method == "OPTIONS":
        return
    action, case_id, person_id = classify(method, path, query)
    action = action_override or action
    allowed = status_code < 400 or status_code in (404, 409, 422)
    denied = status_code in (401, 403)
    try:
        with connect() as conn:
            conn.execute("""INSERT INTO inv.access_log (user_id,user_label,role,method,path,case_id,person_id,action,status_code,
                allowed,client_ip,user_agent,request_id,duration_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (_uuid_or_none(principal), _label(principal), getattr(principal, "role", None), method, path[:500], case_id,
                 person_id, action, status_code, not denied and allowed, client_ip, (user_agent or "")[:300], request_id, duration_ms))
            if principal is None or principal.local:
                return   # local developer: logged, no behaviour rules
            rules = get_setting(conn, "alert_rules", DEFAULT_RULES)
            now = datetime.now(ZoneInfo(rules["timezone"]))
            uid = principal.user_id

            if denied:
                raise_alert(conn, "denied_access", "high", principal,
                            (f"Denied {action.replace('_', ' ')} on {case_id}" if case_id else f"Denied access to {path}"), case_id,
                            {"path": path, "status": status_code, "action": action},
                            dedupe_key=f"denied:{uid}:{case_id or path}:{action}:{now:%Y%m%d%H}")
            start, end = rules["work_hours"]
            after_hours = not (start <= now.hour < end) or (rules["flag_weekends"] and now.weekday() >= 5)
            if after_hours and status_code < 400 and case_id:
                raise_alert(conn, "after_hours", "medium", principal,
                            f"After-hours access to {case_id}", case_id,
                            {"local_time": now.strftime("%Y-%m-%d %H:%M"), "work_hours": rules["work_hours"], "action": action},
                            dedupe_key=f"afterhours:{uid}:{case_id}:{now:%Y%m%d}")
            if action == "view_person" and status_code < 400:
                since = now - timedelta(minutes=rules["bulk_window_minutes"])
                n = conn.execute("""SELECT count(DISTINCT case_id||':'||person_id) n FROM inv.access_log
                    WHERE user_id=%s AND action='view_person' AND at >= %s""", (_uuid_or_none(principal), since)).fetchone()["n"]
                if n >= rules["bulk_person_views"]:
                    raise_alert(conn, "bulk_viewing", "high", principal,
                                f"{n} person profiles viewed in {rules['bulk_window_minutes']} minutes", case_id,
                                {"distinct_profiles": n, "window_minutes": rules["bulk_window_minutes"]},
                                dedupe_key=f"bulk:{uid}:{now:%Y%m%d%H}:{now.minute // rules['bulk_window_minutes']}")
            if action in rules["sensitive_actions"] and status_code < 400:
                raise_alert(conn, "sensitive_action", "low", principal, f"Sensitive action: {action.replace('_', ' ')}", case_id,
                            {"path": path, "action": action})
            key = (uid, case_id)
            if case_id and status_code < 400 and (key not in _COI_CHECKED or _COI_CHECKED[key] < time.monotonic() - 300):
                _COI_CHECKED[key] = time.monotonic()      # re-check a user/case pair at most every 5 minutes
                user = conn.execute("SELECT * FROM inv.app_users WHERE user_id=%s", (_uuid_or_none(principal),)).fetchone()
                matches = conflict_matches(conn, user, case_id)
                if matches:
                    raise_alert(conn, "conflict_of_interest", "high", principal,
                                f"Possible conflict of interest in {case_id}", case_id,
                                {"matches": matches, "note": "The user's own details match case subjects. Verify before they continue."},
                                dedupe_key=f"coi:{uid}:{case_id}")
    except Exception:
        logger.exception("Access logging failed for %s %s", method, path)
